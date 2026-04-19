import json
import os
import re
from typing import Any

from language_family import guess_language_family
import rapidfuzz_query
import text2sql as t2s
import data_watcher


strentityextractionprompttemplate = "entity_extraction.md"
strentityresolutionconfigfile = "entity_resolution.json"
strentityextractionmodeldefault = "gpt-4o"

# Populated synchronously by data_watcher.register() below and refreshed
# automatically whenever the underlying files change on disk.
entity_extraction_prompt_template: str = ""
ENTITY_RESOLUTION_CONFIG: list[dict] = []


def _validate_entity_resolution_config(config: Any) -> list[dict]:
    if not isinstance(config, list):
        raise ValueError("ENTITY_RESOLUTION_CONFIG must be a list of objects.")
    for config_item in config:
        if not isinstance(config_item, dict):
            raise ValueError("Each entity resolution config entry must be an object.")
        if not isinstance(config_item.get("search_list"), list):
            raise ValueError("Each entity resolution config entry must contain a search_list array.")
    return config


def _on_entity_extraction_prompt_change(content: str) -> None:
    global entity_extraction_prompt_template
    entity_extraction_prompt_template = content


def _on_entity_resolution_config_change(content: str) -> None:
    global ENTITY_RESOLUTION_CONFIG
    try:
        parsed = json.loads(content)
        ENTITY_RESOLUTION_CONFIG = _validate_entity_resolution_config(parsed)
    except Exception as e:
        # Keep the previous valid config rather than crashing the running app.
        print(f"[entity] Failed to reload entity_resolution.json, keeping previous config: {e}")


data_watcher.register(strentityextractionprompttemplate, _on_entity_extraction_prompt_change)
data_watcher.register(strentityresolutionconfigfile, _on_entity_resolution_config_change)


def f_entity_extraction(user_question: str, strentityextractionmodel: str = "default"):
    """Extract placeholders and an anonymized question from the raw user question."""
    print("Entity extraction")
    print("User question:", user_question)
    model_to_use = t2s._normalize_llm_model(strentityextractionmodel, strentityextractionmodeldefault)
    print("Entity extraction LLM model:", model_to_use)

    try:
        try:
            formatted_prompt = entity_extraction_prompt_template.replace("{user_question}", user_question)
        except Exception as format_error:
            print(f"Error formatting prompt template: {str(format_error)}")
            print(f"User question: '{user_question}'")
            return {"error": f"Prompt formatting failed: {str(format_error)}"}

        try:
            json_content = t2s._call_chat_llm(
                model=model_to_use,
                system_prompt="You are a powerful entity extraction tool. Respond only with the JSON content, no explanations.",
                user_prompt=formatted_prompt,
                temperature=0,
            ).strip()
        except Exception as api_error:
            print(f"LLM API call failed: {str(api_error)}")
            print(f"API error type: {type(api_error)}")
            return {"error": f"LLM API call failed: {str(api_error)}"}

        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()

        print(f"Raw API response: '{json_content}'")
        print(f"Response length: {len(json_content)}")
        print(f"Response type: {type(json_content)}")

        cleaned_content = json_content.strip().strip("\n").strip("\r").strip("\n")
        if not cleaned_content.startswith("{") or not cleaned_content.endswith("}"):
            print("WARNING: Response doesn't look like complete JSON")
            if cleaned_content.startswith('"question"'):
                cleaned_content = "{" + cleaned_content + "}"
                print(f"Attempting to fix malformed JSON: {cleaned_content}")
            else:
                return {"error": "Incomplete JSON response from API", "raw_content": json_content}

        try:
            entity_extraction = json.loads(cleaned_content)
            print(f"Successfully parsed JSON: {entity_extraction}")
            return entity_extraction
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in entity extraction: {str(json_error)}")
            print(f"Raw response content: '{json_content}'")
            print(f"Cleaned content: '{cleaned_content}'")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}

    except Exception as e:
        print(f"Error in entity extraction: {str(e)}")
        return {"error": str(e)}


def _find_entity_config(placeholder_key: str):
    """Return the first resolution config whose placeholder prefix matches the key."""
    for cfg in ENTITY_RESOLUTION_CONFIG:
        if isinstance(placeholder_key, str) and placeholder_key.startswith(cfg.get("placeholder_prefix", "")):
            return cfg
    return None



def _iter_entity_searches(cfg: dict):
    """Return the validated list of search configurations for a placeholder config."""
    searches = cfg.get("search_list")
    if not isinstance(searches, list):
        return []
    return [search for search in searches if isinstance(search, dict)]



def _sql_escape_literal(v: str) -> str:
    """Escape a string literal for safe inlined SQL replacement."""
    return str(v).replace("'", "''")


# Closed-vocabulary genre lookups. These must stay in sync with the genre
# reference sections of data/text_to_sql.md (T_WC_T2S_MOVIE_GENRE and
# T_WC_T2S_SERIE_GENRE). Keys are normalized to lowercase.
MOVIE_GENRE_NAME_TO_ID: dict[str, int] = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "science fiction": 878,
    "sci-fi": 878,
    "thriller": 53,
    "tv movie": 10770,
    "war": 10752,
    "western": 37,
}

SERIE_GENRE_NAME_TO_ID: dict[str, int] = {
    "animation": 16,
    "drama": 18,
    "comedy": 35,
    "history": 36,
    "western": 37,
    "crime": 80,
    "mystery": 9648,
    "romance": 10749,
    "family": 10751,
    "action & adventure": 10759,
    "kids": 10762,
    "news": 10763,
    "reality": 10764,
    "sci-fi & fantasy": 10765,
    "soap": 10766,
    "talk": 10767,
    "war & politics": 10768,
}


def _resolve_genre_id(raw_value: str, sql_query: str) -> int | None:
    """Map a genre name to its integer ID using movie/serie context from the SQL."""
    norm = (raw_value or "").strip().lower()
    if not norm:
        return None
    sql_upper = (sql_query or "").upper()
    mentions_serie_genre = "SERIE_GENRE" in sql_upper
    mentions_movie_genre = "MOVIE_GENRE" in sql_upper
    if mentions_serie_genre and not mentions_movie_genre:
        return SERIE_GENRE_NAME_TO_ID.get(norm) or MOVIE_GENRE_NAME_TO_ID.get(norm)
    if mentions_movie_genre and not mentions_serie_genre:
        return MOVIE_GENRE_NAME_TO_ID.get(norm) or SERIE_GENRE_NAME_TO_ID.get(norm)
    return MOVIE_GENRE_NAME_TO_ID.get(norm) or SERIE_GENRE_NAME_TO_ID.get(norm)



def resolve_entities(
    *,
    connection,
    entity_extraction,
    sql_query,
    justification,
    position_counter: int,
    text_message_cls,
    messages: list,
    chromadb_collections_by_name: dict,
) -> dict[str, Any]:
    """Resolve extracted entities into concrete SQL and justification substitutions."""
    def add_message(text: str):
        """Append a positional diagnostic message to the response message list."""
        nonlocal position_counter
        messages.append(text_message_cls(position=position_counter, text=text))
        position_counter += 1

    def apply_entity_match_from_docid(*, cursor, key: str, cfg: dict, docid, doclang: str, message: str, current_sql_query: str, current_justification: str):
        """Apply a resolved document ID by loading the row and replacing placeholders."""
        if docid is None:
            return False, current_sql_query, current_justification

        languages_map = cfg.get("languages", {}) or {}
        strfieldnamenew = languages_map.get(doclang) or languages_map.get("*") or cfg.get("default_field")
        strtableidlookup = strfieldnamenew

        strtablename = cfg.get("strtablename")
        strtableid = cfg.get("strtableid")
        if not strtablename or not strtableid:
            return False, current_sql_query, current_justification

        strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strtableid + " = %s"
        cursor.execute(strsql_query, (docid,))
        sql_query_results = cursor.fetchall()
        if not sql_query_results:
            placeholder = "{{" + str(key) + "}}"
            add_message(
                f"Entity resolution: embeddings returned docid={docid} (lang={doclang}) for {placeholder}, "
                f"but no row exists in table {strtablename}.{strtableid}. Embeddings collection may be out of sync with the underlying table."
            )
            return False, current_sql_query, current_justification
        first_record = sql_query_results[0]

        first_record_value = first_record.get(strtableidlookup, "")
        first_record_value_sql = _sql_escape_literal(first_record_value)

        placeholder = "{{" + str(key) + "}}"
        target_col = cfg.get("default_field")
        if not target_col:
            return False, current_sql_query, current_justification

        current_sql_query = re.sub(
            rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'",
            f"{strfieldnamenew} = '{first_record_value_sql}'",
            current_sql_query,
            flags=re.IGNORECASE,
        )
        current_sql_query = re.sub(
            rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}",
            f"{strfieldnamenew} = '{first_record_value_sql}'",
            current_sql_query,
            flags=re.IGNORECASE,
        )
        current_sql_query = re.sub(
            rf"'{re.escape(placeholder)}'",
            f"'{first_record_value_sql}'",
            current_sql_query,
            flags=re.IGNORECASE,
        )
        current_sql_query = re.sub(
            rf"{re.escape(placeholder)}",
            f"'{first_record_value_sql}'",
            current_sql_query,
            flags=re.IGNORECASE,
        )

        current_justification = current_justification.replace(placeholder, str(first_record_value))
        add_message(message.format(placeholder=placeholder, resolved=first_record_value))
        return True, current_sql_query, current_justification

    ambiguous_question_for_text2sql = 0

    if isinstance(entity_extraction, dict):
        with connection.cursor() as cursor:
            for key, value in entity_extraction.items():
                if key == "question":
                    continue

                if isinstance(key, str) and key.startswith("Release_year"):
                    raw_value = "" if value is None else str(value).strip()
                    if raw_value == "" or not re.fullmatch(r"\d{4}", raw_value):
                        continue

                    placeholder = "{{" + key + "}}"
                    sql_query = re.sub(rf"'{re.escape(placeholder)}'", raw_value, sql_query, flags=re.IGNORECASE)
                    sql_query = re.sub(rf"{re.escape(placeholder)}", raw_value, sql_query, flags=re.IGNORECASE)
                    justification = justification.replace(placeholder, raw_value)
                    add_message(f"Entity resolution: {placeholder} -> {raw_value} (numeric)")
                    continue

                if isinstance(key, str) and key.startswith("Genre_name"):
                    raw_value = "" if value is None else str(value).strip()
                    placeholder = "{{" + key + "}}"
                    if raw_value == "":
                        continue

                    genre_id = _resolve_genre_id(raw_value, sql_query)
                    if genre_id is None:
                        add_message(f"Entity resolution: {placeholder} -> unknown genre name '{raw_value}'; leaving placeholder unresolved")
                        continue

                    genre_id_str = str(genre_id)
                    sql_query = re.sub(rf"'{re.escape(placeholder)}'", genre_id_str, sql_query, flags=re.IGNORECASE)
                    sql_query = re.sub(rf"{re.escape(placeholder)}", genre_id_str, sql_query, flags=re.IGNORECASE)
                    justification = justification.replace(placeholder, raw_value)
                    add_message(f"Entity resolution: {placeholder} -> {genre_id_str} ({raw_value}) (genre)")
                    continue

                cfg = _find_entity_config(key)
                if cfg is None:
                    raw_value = "" if value is None else str(value)
                    if raw_value.strip() == "":
                        continue
                    placeholder = "{{" + str(key) + "}}"
                    raw_value_sql = _sql_escape_literal(raw_value)
                    if placeholder in sql_query or placeholder in justification:
                        sql_query = sql_query.replace(placeholder, raw_value_sql)
                        justification = justification.replace(placeholder, raw_value)
                        add_message(f"Entity resolution: {placeholder} -> {raw_value} (generic)")
                    continue

                raw_value = "" if value is None else str(value)
                if raw_value.strip() == "":
                    continue

                placeholder = "{{" + str(key) + "}}"
                raw_value_sql = _sql_escape_literal(raw_value)
                searches = _iter_entity_searches(cfg)
                resolved = False
                language_family = None
                if isinstance(key, str) and key.startswith("Person_name"):
                    try:
                        language_family = guess_language_family(raw_value)
                    except Exception:
                        language_family = None
                    add_message(f"Entity resolution: {placeholder} guessed language family = {language_family or 'unknown'}")

                for search_cfg in searches:
                    apply_when_language_family_in = search_cfg.get("apply_when_language_family_in")
                    if isinstance(apply_when_language_family_in, list):
                        if language_family is None or language_family not in apply_when_language_family_in:
                            continue

                    apply_when_language_family_not_in = search_cfg.get("apply_when_language_family_not_in")
                    if isinstance(apply_when_language_family_not_in, list):
                        if language_family is not None and language_family in apply_when_language_family_not_in:
                            continue

                    search_mode = (search_cfg.get("search_mode") or "").strip().lower()

                    if search_mode == "rapidfuzz":
                        strtablename = search_cfg.get("strtablename")
                        strtableid = search_cfg.get("strtableid")
                        if not strtablename or not strtableid:
                            continue

                        strcolumndesc = search_cfg.get("default_field")
                        strcolumndescnorm = search_cfg.get("rapidfuzz_col_norm") or (f"{strcolumndesc}_NORM" if strcolumndesc else None)
                        strcolumndesckey = search_cfg.get("rapidfuzz_col_key") or (f"{strcolumndesc}_KEY" if strcolumndesc else None)
                        strcolumnpopularity = search_cfg.get("rapidfuzz_col_popularity") or search_cfg.get("order_by") or "POPULARITY"
                        if not strcolumndesc or not strcolumndescnorm or not strcolumndesckey:
                            continue

                        if isinstance(key, str) and key.startswith("Person_name"):
                            add_message(f"Entity resolution: {placeholder} searching with RapidFuzz in table {strtablename} (language family: {language_family or 'unknown'})")

                        try:
                            has_fulltext = rapidfuzz_query.db_has_fulltext(cursor, strtablename, strcolumndescnorm)
                            rapidfuzz_result = rapidfuzz_query.search_first_match(
                                cursor,
                                strtablename,
                                strtableid,
                                strcolumndesc,
                                strcolumndescnorm,
                                strcolumndesckey,
                                strcolumnpopularity,
                                raw=raw_value,
                                has_fulltext=has_fulltext,
                                timings_enabled=False,
                            )
                        except Exception:
                            continue

                        best = (rapidfuzz_result or {}).get("best")
                        if not isinstance(best, dict):
                            continue

                        docid = best.get(strtableid)
                        if docid is None:
                            continue

                        resolve_to_canonical = search_cfg.get("resolve_to_canonical")
                        if isinstance(resolve_to_canonical, dict):
                            aka_value = best.get(strcolumndesc) if strcolumndesc else None
                            if aka_value is None:
                                aka_value = raw_value

                            canonical_value = None
                            try:
                                from_col = resolve_to_canonical.get("from_column")
                                canonical_table = resolve_to_canonical.get("table")
                                canonical_id_col = resolve_to_canonical.get("id_column")
                                canonical_value_col = resolve_to_canonical.get("value_column")
                                canonical_id_val = best.get(from_col) if from_col else None
                                if canonical_id_val is not None and canonical_table and canonical_id_col and canonical_value_col:
                                    cursor.execute(
                                        f"SELECT `{canonical_value_col}` FROM `{canonical_table}` WHERE `{canonical_id_col}` = %s LIMIT 1",
                                        (canonical_id_val,),
                                    )
                                    row = cursor.fetchone()
                                    if isinstance(row, dict):
                                        canonical_value = row.get(canonical_value_col)
                            except Exception:
                                canonical_value = None

                            if canonical_value is None or str(canonical_value).strip() == "":
                                add_message(f"Entity resolution: {placeholder} -> {aka_value} (rapidfuzz; canonical lookup failed, using AKA value)")
                                canonical_value = aka_value

                            canonical_value_sql = _sql_escape_literal(str(canonical_value))
                            target_col = search_cfg.get("default_field") or strcolumndesc
                            if target_col:
                                placeholder_before = (placeholder in sql_query) or (placeholder in justification)
                                sql_query = re.sub(rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'", f"{target_col} = '{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
                                sql_query = re.sub(rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}", f"{target_col} = '{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
                                sql_query = re.sub(rf"'{re.escape(placeholder)}'", f"'{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
                                sql_query = re.sub(rf"{re.escape(placeholder)}", f"'{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
                                justification_value = str(aka_value)
                                if str(canonical_value) != str(aka_value):
                                    justification_value = f"{aka_value} ({canonical_value})"
                                try:
                                    justification = justification.replace(placeholder, justification_value)
                                except Exception:
                                    pass
                                if str(canonical_value) != str(aka_value):
                                    add_message(f"Entity resolution: {placeholder} -> {canonical_value} (SQL canonical), {aka_value} ({canonical_value}) (justification AKA + canonical) (rapidfuzz, source table: {strtablename})")
                                else:
                                    add_message(f"Entity resolution: {placeholder} -> {canonical_value} (SQL canonical and justification) (rapidfuzz, source table: {strtablename})")
                                placeholder_after = (placeholder in sql_query) or (placeholder in justification)
                                if placeholder_before and not placeholder_after:
                                    resolved = True
                                    break
                            continue

                        placeholder_before = (placeholder in sql_query) or (placeholder in justification)
                        resolved_docid, sql_query, justification = apply_entity_match_from_docid(
                            cursor=cursor,
                            key=str(key),
                            cfg=search_cfg,
                            docid=docid,
                            doclang="*",
                            message=f"Entity resolution: {{placeholder}} -> {{resolved}} (rapidfuzz, source table: {strtablename})",
                            current_sql_query=sql_query,
                            current_justification=justification,
                        )
                        placeholder_after = (placeholder in sql_query) or (placeholder in justification)
                        if resolved_docid and placeholder_before and not placeholder_after:
                            resolved = True
                            break
                        continue

                    if search_mode != "embeddings":
                        continue

                    collection_name = search_cfg.get("collection")
                    current_collection = chromadb_collections_by_name.get(collection_name)
                    if current_collection is None:
                        continue

                    results = current_collection.query(query_texts=[raw_value], n_results=10)
                    documents = (results.get("documents", [[]]) or [[]])[0] or []
                    ids = (results.get("ids", [[]]) or [[]])[0] or []
                    if not documents or not ids:
                        continue

                    matched_result_position = 0
                    found_match = False
                    try:
                        target_value_norm = raw_value.strip().lower()
                    except Exception:
                        target_value_norm = ""

                    for i, document in enumerate(documents):
                        if isinstance(document, str) and document.strip().lower() == target_value_norm:
                            matched_result_position = i
                            found_match = True
                            break
                    if not found_match:
                        for i, document in enumerate(documents):
                            if isinstance(document, str) and document.strip().lower().startswith(target_value_norm):
                                matched_result_position = i
                                found_match = True
                                break

                    first_record_id = ids[matched_result_position]
                    parts = str(first_record_id).split("_")
                    docid = parts[1] if len(parts) > 1 else None
                    doclang = parts[2] if len(parts) > 2 else "*"
                    if docid is None:
                        continue

                    placeholder_before = (placeholder in sql_query) or (placeholder in justification)
                    resolved_docid, sql_query, justification = apply_entity_match_from_docid(
                        cursor=cursor,
                        key=str(key),
                        cfg=search_cfg,
                        docid=docid,
                        doclang=doclang,
                        message=f"Entity resolution: {{placeholder}} -> {{resolved}} (lang={doclang})",
                        current_sql_query=sql_query,
                        current_justification=justification,
                    )
                    placeholder_after = (placeholder in sql_query) or (placeholder in justification)
                    if resolved_docid and placeholder_before and not placeholder_after:
                        resolved = True
                        break

                if resolved:
                    continue

                if placeholder in sql_query or placeholder in justification:
                    sql_query = sql_query.replace(placeholder, raw_value_sql)
                    justification = justification.replace(placeholder, raw_value)
                    add_message(f"Entity resolution: {placeholder} -> {raw_value} (raw fallback)")

    unresolved_placeholders = re.findall(r"{{[^}]+}}", sql_query or "")
    if unresolved_placeholders:
        ambiguous_question_for_text2sql = 1
        unresolved_preview = ", ".join(unresolved_placeholders[:10])
        if len(unresolved_placeholders) > 10:
            unresolved_preview += ", ..."
        add_message(f"Unresolved placeholders remain in SQL after entity resolution: {unresolved_preview}")

    return {
        "sql_query": sql_query,
        "justification": justification,
        "position_counter": position_counter,
        "messages": messages,
        "ambiguous_question_for_text2sql": ambiguous_question_for_text2sql,
    }
