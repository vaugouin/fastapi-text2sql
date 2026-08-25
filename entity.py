import json
import os
import re
import time
import threading
from typing import Any

from language_family import guess_language_family
from rapidfuzz import fuzz
import rapidfuzz_query
import text2sql as t2s
import data_watcher
import json_guardrails
import closed_vocab


def _extract_year_context(entity_extraction):
    """Return a plausible release year (int) from a sibling ``Release_year*``
    placeholder, or None. Used to tighten the embeddings shortlist via a
    ChromaDB ``where={"year": {...}}`` filter when disambiguating same-title
    films (voie B / hybrid)."""
    if not isinstance(entity_extraction, dict):
        return None
    for k, v in entity_extraction.items():
        if isinstance(k, str) and k.startswith("Release_year"):
            try:
                y = int(str(v).strip())
            except (TypeError, ValueError):
                continue
            if 1800 <= y <= 2200:
                return y
    return None


# Descriptor words that can trail a resolved franchise/collection name and get
# duplicated by the answer template (see _collapse_repeated_descriptor).
_DESCRIPTOR_BASE = {
    "collection": "collection", "collections": "collection",
    "saga": "saga", "sagas": "saga",
    "universe": "universe", "universes": "universe",
    "franchise": "franchise", "franchises": "franchise",
    "trilogy": "trilogy", "trilogies": "trilogy",
}
_REPEATED_DESCRIPTOR_RE = re.compile(
    r"\b(" + "|".join(_DESCRIPTOR_BASE) + r")\s+(" + "|".join(_DESCRIPTOR_BASE) + r")\b",
    re.IGNORECASE,
)


def _collapse_repeated_descriptor(text: str) -> str:
    """Collapse a franchise/collection descriptor word repeated back-to-back
    (e.g. "Star Wars Collection collection" -> "Star Wars Collection"), keeping the
    first copy. Only the SAME descriptor is collapsed (singular/plural tolerant);
    mixed wording such as "Dollars Trilogy collection" is left untouched."""
    if not text:
        return text

    def _keep_first(m):
        if _DESCRIPTOR_BASE.get(m.group(1).lower()) == _DESCRIPTOR_BASE.get(m.group(2).lower()):
            return m.group(1)
        return m.group(0)

    return _REPEATED_DESCRIPTOR_RE.sub(_keep_first, text)


strentityextractionprompttemplate = "entity_extraction.md"
strentityresolutionconfigfile = "entity_resolution.json"
strentityextractionmodeldefault = "gpt-4o"

# Populated synchronously by data_watcher.register() below and refreshed
# automatically whenever the underlying files change on disk.
entity_extraction_prompt_template: str = ""
ENTITY_RESOLUTION_CONFIG: list[dict] = []

BKTREE_ENABLED = os.getenv("BKTREE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
_BKTREE_CACHE: dict[tuple[str, str, str], rapidfuzz_query.BKTreeIndex] = {}

# Concurrency for BK-tree construction (FASTAPI-TEXT2SQL-145): the background warm-up
# thread and the lazy build path in resolve_entities() may both need the same tree.
# Per-key locks ensure each tree is built exactly once while different keys still build
# in parallel. BKTREES_READY flips True when the eager warm-up finishes (readiness probe).
_BKTREE_LOCKS_META = threading.Lock()
_BKTREE_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}
BKTREES_READY = False


def _bktree_lock_for(cache_key: tuple[str, str, str]) -> threading.Lock:
    with _BKTREE_LOCKS_META:
        lock = _BKTREE_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _BKTREE_LOCKS[cache_key] = lock
        return lock


def get_or_build_bktree(cache_key, build_fn):
    """Return the cached BK-tree for ``cache_key``, building it once if absent.

    Thread-safe: concurrent callers for the SAME key serialize on a per-key lock so the
    (potentially multi-minute) build runs once; callers for DIFFERENT keys proceed in
    parallel. ``build_fn`` is a no-arg callable returning a BKTreeIndex. Used by both the
    background warm-up (prebuild_bktrees) and the on-demand lazy path in resolve_entities.
    """
    idx = _BKTREE_CACHE.get(cache_key)
    if idx is not None:
        return idx
    with _bktree_lock_for(cache_key):
        idx = _BKTREE_CACHE.get(cache_key)
        if idx is None:
            idx = build_fn()
            _BKTREE_CACHE[cache_key] = idx
        return idx


def _estimate_table_rows(cursor, strtablename: str) -> int:
    """Approximate row count for ``strtablename`` from ``information_schema``.

    Used only to order the BK-tree warm-up (shortest tables first); the optimizer
    estimate is more than precise enough for ordering by magnitude and costs no
    table scan. Returns a large sentinel when the count is unavailable so unknown
    tables build last rather than delaying the confirmed-short ones.
    """
    try:
        cursor.execute(
            "SELECT TABLE_ROWS FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (strtablename,),
        )
        row = cursor.fetchone()
    except Exception:
        return 1 << 62
    if not row:
        return 1 << 62
    value = row.get("TABLE_ROWS") if isinstance(row, dict) else row[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1 << 62


def prebuild_bktrees(connection) -> None:
    """Eagerly build a BK-tree for every RapidFuzz table in ENTITY_RESOLUTION_CONFIG.

    Run in a BACKGROUND thread at startup (FASTAPI-TEXT2SQL-145) so uvicorn serves
    immediately: this warm-up only primes the same cache the lazy path in
    resolve_entities() fills on demand. Each tree is keyed by (table, id, norm_col) —
    the same key used at query time — and built through get_or_build_bktree so a
    concurrent lazy build of the same table does not double-build.

    Build order is **shortest table first** (by approximate row count): the smallest
    trees finish almost immediately, so the entities they back (e.g. collections)
    become resolvable within seconds of warm-up start while the large person tables
    are still building — instead of waiting behind them.

    Failures on individual tables are logged and skipped so a single broken table does
    not block the warm-up. Sets BKTREES_READY when the pass finishes (readiness probe).
    """
    global BKTREES_READY
    if not BKTREE_ENABLED:
        print("[entity] BKTREE_ENABLED=0, skipping BK-tree prebuild")
        BKTREES_READY = True
        return

    seen: set[tuple[str, str, str]] = set()
    cursor = connection.cursor()
    try:
        # Gather the distinct rapidfuzz build tasks declared in the config.
        tasks: list[tuple[str, str, str]] = []
        for entry in ENTITY_RESOLUTION_CONFIG:
            for search_cfg in entry.get("search_list") or []:
                if (search_cfg.get("search_mode") or "").strip().lower() != "rapidfuzz":
                    continue

                strtablename = search_cfg.get("strtablename")
                strtableid = search_cfg.get("strtableid")
                strcolumndesc = search_cfg.get("default_field")
                strcolumndescnorm = search_cfg.get("rapidfuzz_col_norm") or (f"{strcolumndesc}_NORM" if strcolumndesc else None)
                if not strtablename or not strtableid or not strcolumndescnorm:
                    continue

                cache_key = (strtablename, strtableid, strcolumndescnorm)
                if cache_key in seen or cache_key in _BKTREE_CACHE:
                    continue
                seen.add(cache_key)
                tasks.append(cache_key)

        # Order shortest-first so the quickest trees are ready soonest. Ties keep
        # config order (Python's sort is stable). Row-count probing happens up
        # front, before any (slow) build, and reuses the same cursor sequentially.
        row_counts = {cache_key: _estimate_table_rows(cursor, cache_key[0]) for cache_key in tasks}
        tasks.sort(key=lambda cache_key: row_counts[cache_key])
        if tasks:
            order_preview = ", ".join(f"{cache_key[0]}(~{row_counts[cache_key]})" for cache_key in tasks)
            print(f"[entity] BK-tree warm-up order (shortest first): {order_preview}")

        for cache_key in tasks:
            strtablename, strtableid, strcolumndescnorm = cache_key
            t0 = time.perf_counter()
            try:
                bktree_idx = get_or_build_bktree(
                    cache_key,
                    lambda c=cursor, t=strtablename, i=strtableid, n=strcolumndescnorm:
                        rapidfuzz_query.build_bktree_for_config(c, {"table": t, "id": i, "norm": n}),
                )
                print(f"[entity] BK-tree ready for {strtablename}.{strcolumndescnorm}: {bktree_idx.size} entries in {time.perf_counter() - t0:.1f}s")
            except Exception as e:
                print(f"[entity] BK-tree prebuild failed for {strtablename}.{strcolumndescnorm}: {e}")
    finally:
        cursor.close()
        BKTREES_READY = True


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


def _run_extraction_prompt(prompt_template: str, user_question: str, model_to_use: str, cache_label: str):
    """Run one extraction prompt and return its parsed JSON payload.

    Shared by the single-prompt path and by both halves of the split path
    (FASTAPI-TEXT2SQL-200), which differ only by the template they feed in.

    Args:
        prompt_template: Hot-reloaded template carrying a ``{user_question}`` slot.
        user_question: The raw, non-anonymized question.
        model_to_use: Already-normalized LLM model name.
        cache_label: Pipeline step name, used to tag prompt-cache observations.

    Returns:
        The parsed payload (``{"question": ..., "<Key>": value}``) or an
        ``{"error": ...}`` dict, which every caller already knows how to handle.
    """
    try:
        try:
            formatted_prompt = prompt_template.replace("{user_question}", user_question)
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
                cache_label=cache_label,
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
            # JSON guardrail (FASTAPI-TEXT2SQL-038): validate the output shape.
            ok, guard_error = json_guardrails.validate_llm_json(entity_extraction, "entity_extraction")
            if not ok:
                print(f"JSON guardrail failed in entity extraction: {guard_error}")
                return {"error": f"JSON guardrail: {guard_error}", "raw_content": json_content}
            return entity_extraction
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in entity extraction: {str(json_error)}")
            print(f"Raw response content: '{json_content}'")
            print(f"Cleaned content: '{cleaned_content}'")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}

    except Exception as e:
        print(f"Error in entity extraction: {str(e)}")
        return {"error": str(e)}


def f_entity_extraction(user_question: str, strentityextractionmodel: str = "default"):
    """Extract placeholders and an anonymized question from the raw user question."""
    print("Entity extraction")
    print("User question:", user_question)
    model_to_use = t2s._normalize_llm_model(strentityextractionmodel, strentityextractionmodeldefault)
    print("Entity extraction LLM model:", model_to_use)
    return _run_extraction_prompt(entity_extraction_prompt_template, user_question, model_to_use, "entity_extraction")


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


# Genre canonical maps live in closed_vocab and are loaded from the prompt at
# startup (see closed_vocab.init). Status_name and Serie_type canonicals are
# loaded from the database at startup. Aliases for all three live in
# data/closed_vocabularies.json and hot-reload via data_watcher.


# Regex-validated placeholders (numeric or string ID literals).
# Each entry: (placeholder_prefix, regex_pattern, is_numeric).
#   is_numeric=True  -> substitute as bare number (works for INT columns)
#   is_numeric=False -> substitute as a quoted SQL string literal (VARCHAR columns)
# More specific prefixes must come before less specific ones because dispatch
# uses startswith() on the placeholder key (e.g. IMDb_person_ID before IMDb_ID).
_REGEX_PLACEHOLDER_RULES: list[tuple[str, str, bool]] = [
    ("Release_year",         r"\d{4}", True),
    ("Birth_year",           r"\d{4}", True),
    ("Death_year",           r"\d{4}", True),
    ("IMDb_person_ID",       r"nm\d+", False),
    ("IMDb_ID",              r"tt\d+", False),
    ("Wikidata_property_ID", r"P\d+",  False),
    ("Wikidata_ID",          r"Q\d+",  False),
    ("TMDb_ID",              r"\d+",   True),
    ("Criterion_spine_ID",   r"\d+",   True),
]


def _match_regex_placeholder_rule(key: str) -> tuple[str, str, bool] | None:
    """Return the first regex rule whose prefix matches the placeholder key."""
    if not isinstance(key, str):
        return None
    for prefix, pattern, is_numeric in _REGEX_PLACEHOLDER_RULES:
        if key.startswith(prefix):
            return prefix, pattern, is_numeric
    return None



class _PlannedEntity:
    """One extracted entity, resolved as far as the SQL is not needed.

    Produced by :func:`plan_entity_resolutions` (the expensive half: regex checks,
    closed-vocabulary lookups, ChromaDB, RapidFuzz, row lookups) and consumed by
    :func:`apply_entity_resolutions` (the cheap half: string substitution into the
    SQL, the justification and the answer). Keeping the two apart is what lets the
    resolution run while the text-to-SQL call is still in flight
    (FASTAPI-TEXT2SQL-201).

    Attributes:
        key: The extracted placeholder key, e.g. ``Person_name1``.
        placeholder: The literal ``{{key}}`` token.
        messages: Diagnostics recorded while deciding, replayed in order at apply time.
        substitution: ``fn(sql, justification, answer) -> (sql, justification, answer)``,
            or None when nothing could be resolved.
        final_message: Diagnostic emitted right after a successful substitution.
        require_present: When True, the substitution and its ``final_message`` only
            apply if the placeholder actually occurs in one of the three texts.
    """

    __slots__ = ("key", "placeholder", "messages", "substitution", "final_message", "require_present", "is_raw_fallback")

    def __init__(self, key: str, placeholder: str):
        self.key = key
        self.placeholder = placeholder
        self.messages = []
        self.substitution = None
        self.final_message = None
        self.require_present = False
        # True when every configured strategy failed and the user's own words were
        # substituted instead. FASTAPI-TEXT2SQL-156 needs this: substituting the raw value
        # REMOVES the placeholder, so ambiguous_question_for_text2sql drops back to 0 at the
        # exact moment resolution failed, and the caller loses the only signal it had.
        self.is_raw_fallback = False

    def note(self, text: str) -> None:
        """Record a diagnostic to be replayed when the plan is applied."""
        self.messages.append(text)

    def resolve_with(self, substitution, final_message=None, require_present: bool = False, is_raw_fallback: bool = False) -> None:
        """Attach the substitution that resolves this placeholder."""
        self.substitution = substitution
        self.final_message = final_message
        self.require_present = require_present
        self.is_raw_fallback = is_raw_fallback


def _substitute_literal(placeholder: str, sql_value: str, text_value: str):
    """Build a substitution replacing ``placeholder`` by a bare SQL literal.

    Two regex passes so a quoted placeholder (``'{{X}}'``) and a bare one both go,
    which is how an integer id lands unquoted in an INT comparison.
    """
    def _apply(sql_query: str, justification: str, answer: str):
        """Apply the literal substitution to the three texts."""
        sql_query = re.sub(rf"'{re.escape(placeholder)}'", sql_value, sql_query, flags=re.IGNORECASE)
        sql_query = re.sub(rf"{re.escape(placeholder)}", sql_value, sql_query, flags=re.IGNORECASE)
        return sql_query, justification.replace(placeholder, text_value), answer.replace(placeholder, text_value)

    return _apply


def _substitute_plain(placeholder: str, sql_value: str, text_value: str):
    """Build a substitution using plain string replacement (generic / raw fallback)."""
    def _apply(sql_query: str, justification: str, answer: str):
        """Apply the plain substitution to the three texts."""
        return (
            sql_query.replace(placeholder, sql_value),
            justification.replace(placeholder, text_value),
            answer.replace(placeholder, text_value),
        )

    return _apply


def _substitute_entity_row(placeholder: str, target_col: str, strfieldnamenew: str, multi_cols: list, record_value):
    """Build the substitution for a row matched by embeddings or RapidFuzz.

    Voie B: when ``multi_cols`` is set, rewrite "COL = 'X'" into a language-agnostic
    OR predicate across every title column, so a film whose match-language column
    differs from the typed language is still reached (e.g. Varda's "Le Bonheur" is
    stored as MOVIE_TITLE='Happiness', MOVIE_TITLE_FR='Le Bonheur'). The query's
    other constraints (director, year) then pick the right homonym. An optional
    table qualifier (e.g. "T_WC_T2S_MOVIE.") is captured and re-applied to each OR
    term. Otherwise the target column is swapped for the match-language one.
    """
    record_value_sql = _sql_escape_literal(record_value)

    def _apply(sql_query: str, justification: str, answer: str):
        """Apply the resolved row's value to the three texts."""
        if multi_cols:
            def _or_group(match):
                """Expand one column equality into an OR across every title column."""
                qual = match.group("qual") or ""
                terms = " OR ".join(
                    f"{qual}{col} = '{record_value_sql}'" for col in multi_cols
                )
                return f"({terms})"

            qual_re = r"(?P<qual>(?:\w+\s*\.\s*)?)"
            sql_query = re.sub(
                qual_re + rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'",
                _or_group,
                sql_query,
                flags=re.IGNORECASE,
            )
            sql_query = re.sub(
                qual_re + rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}",
                _or_group,
                sql_query,
                flags=re.IGNORECASE,
            )
        else:
            sql_query = re.sub(
                rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'",
                f"{strfieldnamenew} = '{record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )
            sql_query = re.sub(
                rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}",
                f"{strfieldnamenew} = '{record_value_sql}'",
                sql_query,
                flags=re.IGNORECASE,
            )
        sql_query = re.sub(
            rf"'{re.escape(placeholder)}'",
            f"'{record_value_sql}'",
            sql_query,
            flags=re.IGNORECASE,
        )
        sql_query = re.sub(
            rf"{re.escape(placeholder)}",
            f"'{record_value_sql}'",
            sql_query,
            flags=re.IGNORECASE,
        )
        return (
            sql_query,
            justification.replace(placeholder, str(record_value)),
            answer.replace(placeholder, str(record_value)),
        )

    return _apply


def _substitute_canonical(placeholder: str, target_col: str, canonical_value, justification_value: str):
    """Build the substitution for a RapidFuzz AKA match resolved to its canonical value."""
    canonical_value_sql = _sql_escape_literal(str(canonical_value))

    def _apply(sql_query: str, justification: str, answer: str):
        """Apply the canonical value to the SQL and the AKA wording to the prose."""
        sql_query = re.sub(
            rf"\b{re.escape(target_col)}\b\s*=\s*'{re.escape(placeholder)}'",
            f"{target_col} = '{canonical_value_sql}'",
            sql_query,
            flags=re.IGNORECASE,
        )
        sql_query = re.sub(
            rf"\b{re.escape(target_col)}\b\s*=\s*{re.escape(placeholder)}",
            f"{target_col} = '{canonical_value_sql}'",
            sql_query,
            flags=re.IGNORECASE,
        )
        sql_query = re.sub(rf"'{re.escape(placeholder)}'", f"'{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
        sql_query = re.sub(rf"{re.escape(placeholder)}", f"'{canonical_value_sql}'", sql_query, flags=re.IGNORECASE)
        try:
            justification = justification.replace(placeholder, justification_value)
            answer = answer.replace(placeholder, justification_value)
        except Exception:
            pass
        return sql_query, justification, answer

    return _apply


def _plan_entity_row_substitution(*, cursor, planned: _PlannedEntity, cfg: dict, docid, doclang: str, message: str) -> bool:
    """Load the row behind a resolved document id and attach its substitution.

    Returns True when the row exists and the substitution was recorded. A missing
    row means the embeddings collection has drifted from the SQL table; that is
    reported as a diagnostic and treated as unresolved, so the next strategy runs.
    """
    if docid is None:
        return False

    languages_map = cfg.get("languages", {}) or {}
    strfieldnamenew = languages_map.get(doclang) or languages_map.get("*") or cfg.get("default_field")

    strtablename = cfg.get("strtablename")
    strtableid = cfg.get("strtableid")
    if not strtablename or not strtableid:
        return False

    strsql_query = "SELECT * FROM " + strtablename + " WHERE " + strtableid + " = %s"
    cursor.execute(strsql_query, (docid,))
    sql_query_results = cursor.fetchall()
    if not sql_query_results:
        planned.note(
            f"Entity resolution: embeddings returned docid={docid} (lang={doclang}) for {planned.placeholder}, "
            f"but no row exists in table {strtablename}.{strtableid}. Embeddings collection may be out of sync with the underlying table."
        )
        return False

    first_record = sql_query_results[0]
    first_record_value = first_record.get(strfieldnamenew, "")

    target_col = cfg.get("default_field")
    if not target_col:
        return False

    multi_cols = []
    if cfg.get("multi_language_match"):
        seen = set()
        for col in languages_map.values():
            if col and col not in seen:
                seen.add(col)
                multi_cols.append(col)

    planned.resolve_with(
        _substitute_entity_row(planned.placeholder, target_col, strfieldnamenew, multi_cols, first_record_value),
        final_message=message.format(placeholder=planned.placeholder, resolved=first_record_value),
    )
    return True


def plan_entity_resolutions(
    *,
    connection,
    entity_extraction,
    chromadb_collections_by_name: dict,
) -> dict[str, Any]:
    """Resolve every extracted entity as far as the generated SQL is not needed.

    This is the whole expensive half of entity resolution: regex validation,
    closed-vocabulary lookups, ChromaDB shortlists, RapidFuzz matching and the row
    lookups behind them. None of it reads the SQL, the justification or the answer,
    so it can run while the text-to-SQL call is still in flight
    (FASTAPI-TEXT2SQL-201). The SQL only appears in
    :func:`apply_entity_resolutions`, which is pure string substitution.

    Args:
        connection: Open database connection used for the resolution lookups.
        entity_extraction: Extraction payload, ``{"question": ..., "<Key>": value}``.
        chromadb_collections_by_name: Embeddings collections, keyed by name.

    Returns:
        dict with ``entities`` (list of :class:`_PlannedEntity`, in extraction
        order) and ``planning_time`` (seconds spent here, for the timing breakdown).
    """
    planning_start_time = time.time()
    # Every candidate weighed by an embeddings or rapidfuzz strategy, accepted or not
    # (FASTAPI-TEXT2SQL-206). Only Collection_name carries a threshold today, so twelve of the
    # fourteen resolvers accept their nearest neighbour however far it sits. Calibrating a
    # threshold needs the distribution of those distances, which nothing recorded until now.
    match_scores: list = []
    planned_entities: list[_PlannedEntity] = []

    if isinstance(entity_extraction, dict):
        with connection.cursor() as cursor:
            for key, value in entity_extraction.items():
                if key == "question":
                    continue

                placeholder = "{{" + str(key) + "}}"
                planned = _PlannedEntity(str(key), placeholder)
                planned_entities.append(planned)

                regex_rule = _match_regex_placeholder_rule(key)
                if regex_rule is not None:
                    prefix, pattern, is_numeric = regex_rule
                    raw_value = "" if value is None else str(value).strip()
                    if raw_value == "" or not re.fullmatch(pattern, raw_value):
                        planned.note(
                            f"Entity resolution: {placeholder} -> rejected '{raw_value}' "
                            f"(does not match expected pattern {pattern} for {prefix}); leaving placeholder unresolved"
                        )
                        continue

                    if is_numeric:
                        sub_sql = raw_value
                        kind = "numeric"
                    else:
                        sub_sql = f"'{_sql_escape_literal(raw_value)}'"
                        kind = "regex string"

                    planned.resolve_with(
                        _substitute_literal(placeholder, sub_sql, raw_value),
                        final_message=f"Entity resolution: {placeholder} -> {raw_value} ({kind})",
                    )
                    continue

                if isinstance(key, str) and (key.startswith("Movie_genre") or key.startswith("Serie_genre")):
                    raw_value = "" if value is None else str(value).strip()
                    if raw_value == "":
                        continue

                    if key.startswith("Movie_genre"):
                        genre_id = closed_vocab.resolve_movie_genre(raw_value)
                        side = "movie genre"
                    else:
                        genre_id = closed_vocab.resolve_serie_genre(raw_value)
                        side = "serie genre"
                    if genre_id is None:
                        planned.note(f"Entity resolution: {placeholder} -> unknown {side} '{raw_value}'; leaving placeholder unresolved")
                        continue

                    genre_id_str = str(genre_id)
                    planned.resolve_with(
                        _substitute_literal(placeholder, genre_id_str, raw_value),
                        final_message=f"Entity resolution: {placeholder} -> {genre_id_str} ({raw_value}) ({side})",
                    )
                    continue

                if isinstance(key, str) and key.startswith("Technical_format"):
                    raw_value = "" if value is None else str(value).strip()
                    if raw_value == "":
                        continue

                    technical_id = closed_vocab.resolve_technical(raw_value)
                    if technical_id is None:
                        planned.note(f"Entity resolution: {placeholder} -> unknown technical format '{raw_value}'; leaving placeholder unresolved")
                        continue

                    technical_id_str = str(technical_id)
                    planned.resolve_with(
                        _substitute_literal(placeholder, technical_id_str, raw_value),
                        final_message=f"Entity resolution: {placeholder} -> {technical_id_str} ({raw_value}) (technical_format)",
                    )
                    continue

                if isinstance(key, str) and (
                    key.startswith("Status_name")
                    or key.startswith("Serie_type")
                    or key.startswith("Department_name")
                ):
                    raw_value = "" if value is None else str(value).strip()
                    if raw_value == "":
                        continue

                    if key.startswith("Status_name"):
                        entity_name = "Status_name"
                    elif key.startswith("Serie_type"):
                        entity_name = "Serie_type"
                    else:
                        entity_name = "Department_name"
                    canonical = closed_vocab.resolve(entity_name, raw_value)
                    if canonical is None:
                        planned.note(
                            f"Entity resolution: {placeholder} -> unknown {entity_name} value '{raw_value}'; "
                            "leaving placeholder unresolved"
                        )
                        continue

                    canonical_sql = _sql_escape_literal(str(canonical))
                    planned.resolve_with(
                        _substitute_literal(placeholder, f"'{canonical_sql}'", str(canonical)),
                        final_message=f"Entity resolution: {placeholder} -> {canonical} ({raw_value}) ({entity_name})",
                    )
                    continue

                cfg = _find_entity_config(key)
                if cfg is None:
                    raw_value = "" if value is None else str(value)
                    if raw_value.strip() == "":
                        continue
                    raw_value_sql = _sql_escape_literal(raw_value)
                    planned.resolve_with(
                        _substitute_plain(placeholder, raw_value_sql, raw_value),
                        final_message=f"Entity resolution: {placeholder} -> {raw_value} (generic)",
                        require_present=True,
                    )
                    continue

                raw_value = "" if value is None else str(value)
                if raw_value.strip() == "":
                    continue

                raw_value_sql = _sql_escape_literal(raw_value)
                searches = _iter_entity_searches(cfg)
                resolved = False
                language_family = None
                if isinstance(key, str) and key.startswith("Person_name"):
                    try:
                        language_family = guess_language_family(raw_value)
                    except Exception:
                        language_family = None
                    planned.note(f"Entity resolution: {placeholder} guessed language family = {language_family or 'unknown'}")

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
                            planned.note(f"Entity resolution: {placeholder} searching with RapidFuzz in table {strtablename} (language family: {language_family or 'unknown'})")

                        try:
                            has_fulltext = rapidfuzz_query.db_has_fulltext(cursor, strtablename, strcolumndescnorm)
                            bktree_idx = None
                            if BKTREE_ENABLED:
                                cache_key = (strtablename, strtableid, strcolumndescnorm)
                                was_cached = cache_key in _BKTREE_CACHE
                                try:
                                    bktree_idx = get_or_build_bktree(
                                        cache_key,
                                        lambda: rapidfuzz_query.build_bktree_for_config(
                                            cursor,
                                            {
                                                "table": strtablename,
                                                "id": strtableid,
                                                "norm": strcolumndescnorm,
                                            },
                                        ),
                                    )
                                    if not was_cached and bktree_idx is not None:
                                        print(f"[entity] BK-tree loaded on-demand for RapidFuzz search on {strtablename}.{strcolumndescnorm}: {bktree_idx.size} entries")
                                except Exception:
                                    bktree_idx = None
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
                                bktree=bktree_idx,
                                # Neutralize generic franchise words (collections): "Star Wars
                                # universe" ~ "Star Wars Collection". Applied to the query and,
                                # in-memory, to each candidate NORM, so no stored-column backfill
                                # is required. Opt-in per strategy in entity_resolution.json.
                                strip_stopwords=bool(search_cfg.get("strip_franchise_stopwords")),
                            )
                        except Exception:
                            continue

                        best = (rapidfuzz_result or {}).get("best")
                        if not isinstance(best, dict):
                            continue

                        # Same measurement as the embeddings path (FASTAPI-TEXT2SQL-206), and
                        # deliberately the same metric: fuzz.ratio between the sought value and
                        # the matched text, which is exactly what min_fuzz_ratio gates on. Using
                        # rapidfuzz's own internal score instead would produce two scales that
                        # cannot be compared when calibrating.
                        try:
                            _matched_text = str(best.get(strcolumndesc) or "") if strcolumndesc else ""
                            _sought_norm = raw_value.strip().lower()
                            _matched_norm = _matched_text.strip().lower()
                            _rf_ratio = fuzz.ratio(_sought_norm, _matched_norm) if _matched_norm else 0.0
                            match_scores.append({
                                "placeholder": placeholder,
                                "search_mode": "rapidfuzz",
                                "collection": search_cfg.get("collection"),
                                "sought": raw_value,
                                "candidate": _matched_text,
                                "distance": None,
                                "fuzz_ratio": round(float(_rf_ratio), 1),
                                "exact_match": _sought_norm == _matched_norm,
                                "rejected": False,
                                "auto": bool((rapidfuzz_result or {}).get("auto")),
                                "min_fuzz_ratio": search_cfg.get("min_fuzz_ratio"),
                            })
                        except Exception:
                            pass

                        # Confidence gate (FASTAPI-TEXT2SQL-062): when `require_confident`
                        # is set, only accept an exact / high-confidence auto-correct
                        # (rapidfuzz `auto` True) so a low-confidence lexical guess falls
                        # through to the next strategy (e.g. embeddings) instead of
                        # substituting a wrong entity. Off by default so existing
                        # Person_name strategies keep their always-resolve behaviour.
                        if search_cfg.get("require_confident") and not (rapidfuzz_result or {}).get("auto"):
                            planned.note(
                                f"Entity resolution: {placeholder} -> RapidFuzz best match not confident "
                                f"({(rapidfuzz_result or {}).get('reason')}); falling through to next strategy"
                            )
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
                                planned.note(f"Entity resolution: {placeholder} -> {aka_value} (rapidfuzz; canonical lookup failed, using AKA value)")
                                canonical_value = aka_value

                            target_col = search_cfg.get("default_field") or strcolumndesc
                            if target_col:
                                justification_value = str(aka_value)
                                if str(canonical_value) != str(aka_value):
                                    justification_value = f"{aka_value} ({canonical_value})"
                                    final_message = f"Entity resolution: {placeholder} -> {canonical_value} (SQL canonical), {aka_value} ({canonical_value}) (justification AKA + canonical) (rapidfuzz, source table: {strtablename})"
                                else:
                                    final_message = f"Entity resolution: {placeholder} -> {canonical_value} (SQL canonical and justification) (rapidfuzz, source table: {strtablename})"
                                planned.resolve_with(
                                    _substitute_canonical(placeholder, target_col, canonical_value, justification_value),
                                    final_message=final_message,
                                )
                                resolved = True
                                break
                            continue

                        if _plan_entity_row_substitution(
                            cursor=cursor,
                            planned=planned,
                            cfg=search_cfg,
                            docid=docid,
                            doclang="*",
                            message=f"Entity resolution: {{placeholder}} -> {{resolved}} (rapidfuzz, source table: {strtablename})",
                        ):
                            resolved = True
                            break
                        continue

                    if search_mode != "embeddings":
                        continue

                    collection_name = search_cfg.get("collection")
                    current_collection = chromadb_collections_by_name.get(collection_name)
                    if current_collection is None:
                        continue

                    # Hybrid (voie B): when this entity carries year metadata and a
                    # sibling Release_year is present, tighten the shortlist with a
                    # ChromaDB metadata filter. Falls back to an unfiltered search if
                    # the filter yields nothing (e.g. before the year backfill has run,
                    # or for movies whose RELEASE_YEAR is NULL) so behaviour never regresses.
                    results = None
                    if search_cfg.get("year_metadata_filter"):
                        _year_ctx = _extract_year_context(entity_extraction)
                        if _year_ctx is not None:
                            try:
                                _filtered = current_collection.query(
                                    query_texts=[raw_value],
                                    n_results=10,
                                    where={"year": {"$gte": _year_ctx - 1, "$lte": _year_ctx + 1}},
                                )
                                if (_filtered.get("documents", [[]]) or [[]])[0] or []:
                                    results = _filtered
                            except Exception:
                                results = None
                    if results is None:
                        results = current_collection.query(query_texts=[raw_value], n_results=10)
                    documents = (results.get("documents", [[]]) or [[]])[0] or []
                    ids = (results.get("ids", [[]]) or [[]])[0] or []
                    distances = (results.get("distances", [[]]) or [[]])[0] or []
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
                    if not found_match and target_value_norm:
                        # Typo-tolerant rerank of the shortlist (voie B): pick the
                        # candidate whose title is lexically closest to the typed value
                        # (e.g. "le bonnheur" -> "Le Bonheur"). Falls back to the
                        # embedding top-1 if nothing scores.
                        best_score = -1.0
                        for i, document in enumerate(documents):
                            if not isinstance(document, str):
                                continue
                            score = fuzz.WRatio(target_value_norm, document.strip().lower())
                            if score > best_score:
                                best_score = score
                                matched_result_position = i

                    # Confidence gate (FASTAPI-TEXT2SQL-062): when the chosen
                    # candidate is not an exact normalized match, optionally reject
                    # it so a degraded / near-miss shortlist yields "unresolved"
                    # (safe) rather than a confidently wrong entity. Opt-in per
                    # strategy via `max_distance` and/or `min_fuzz_ratio`; an exact
                    # match always passes. `fuzz.ratio` (edit distance) is used, not
                    # WRatio, because titles sharing a common suffix (e.g.
                    # "... Collection") inflate WRatio's token_set component and let
                    # unrelated entries through (observed: "Mad Max collection" ->
                    # "Max und die Wilde 7 Collection", WRatio=85 but ratio=62).
                    max_distance = search_cfg.get("max_distance")
                    min_fuzz_ratio = search_cfg.get("min_fuzz_ratio")
                    # Measured unconditionally now, where it used to be computed only when a
                    # threshold was configured. Without a threshold there was no gate, so no
                    # reason to score; but that is exactly why no distribution existed to set
                    # one from. The gate below keeps its former semantics to the letter: with
                    # both thresholds absent, distance_ok and ratio_ok stay True and nothing is
                    # ever rejected, as before.
                    chosen_doc = documents[matched_result_position] if matched_result_position < len(documents) else ""
                    chosen_doc_norm = chosen_doc.strip().lower() if isinstance(chosen_doc, str) else ""
                    # Certaines collections indexent "nom<sep>description", ce qui aide beaucoup
                    # la recherche semantique et ruine la comparaison lexicale : mesure du
                    # 2026-08-25, "Blaxploitation" contre "Blaxploitation: Here is the list of..."
                    # note 2,3 alors que c'est une correspondance PARFAITE. La description a sa
                    # place dans l'espace vectoriel et rien a faire dans un ratio d'edition.
                    # Declare par entite, jamais globalement : un nom peut legitimement contenir
                    # le separateur ("Star Trek: The Next Generation"), et decouper a l'aveugle le
                    # tronquerait. Le nom nu sert AUSSI de candidat rapporte, pour que le banc et
                    # les journaux montrent ce qui a reellement ete compare.
                    _name_separator = search_cfg.get("document_name_separator")
                    if _name_separator and _name_separator in chosen_doc_norm:
                        chosen_doc_norm = chosen_doc_norm.split(_name_separator, 1)[0].strip()
                        if isinstance(chosen_doc, str) and _name_separator in chosen_doc:
                            chosen_doc = chosen_doc.split(_name_separator, 1)[0].strip()
                    chosen_distance = None
                    if matched_result_position < len(distances):
                        try:
                            chosen_distance = float(distances[matched_result_position])
                        except (TypeError, ValueError):
                            chosen_distance = None
                    # Neutralize the entity's own descriptor words on BOTH sides before scoring
                    # (FASTAPI-TEXT2SQL-206). A word shared by the sought value and the candidate
                    # inflates the similarity without carrying any identifying signal: measured
                    # 2026-08-24, "wagonlit collection" against "life collection" scores 76.5 and
                    # cleared the threshold of 72, where "wagonlit" against "life" scores 33.3.
                    # Moving from WRatio to fuzz.ratio had already been tried against this family
                    # of defect and was not enough: the descriptor survives the change of metric,
                    # only removing it works. Per-entity list, since what is generic for a
                    # collection is identifying for an award ("Academy Award for Best Picture"
                    # minus "award" and "best" is not the same name any more).
                    _score_stopwords = search_cfg.get("score_stopwords")
                    _sought_scored, _candidate_scored = target_value_norm, chosen_doc_norm
                    if _score_stopwords:
                        try:
                            _sought_scored = rapidfuzz_query.strip_franchise_words(
                                target_value_norm, _score_stopwords)
                            _candidate_scored = rapidfuzz_query.strip_franchise_words(
                                chosen_doc_norm, _score_stopwords)
                        except Exception:
                            _sought_scored, _candidate_scored = target_value_norm, chosen_doc_norm
                    chosen_ratio = fuzz.ratio(_sought_scored, _candidate_scored) if _candidate_scored else 0.0
                    # Kept for calibration: what the score would have been without stripping, so
                    # the bench can weigh the two and the effect stays auditable.
                    chosen_ratio_raw = fuzz.ratio(target_value_norm, chosen_doc_norm) if chosen_doc_norm else 0.0

                    distance_ok = (max_distance is None) or (chosen_distance is None) or (chosen_distance <= max_distance)
                    ratio_ok = (min_fuzz_ratio is None) or (chosen_ratio >= min_fuzz_ratio)
                    rejected = (not found_match) and not (distance_ok and ratio_ok)
                    match_scores.append({
                        "placeholder": placeholder,
                        "search_mode": "embeddings",
                        "collection": collection_name,
                        "sought": raw_value,
                        "candidate": chosen_doc if isinstance(chosen_doc, str) else "",
                        "distance": chosen_distance,
                        "fuzz_ratio": round(float(chosen_ratio), 1),
                        "fuzz_ratio_raw": round(float(chosen_ratio_raw), 1),
                        "stopwords_applied": bool(_score_stopwords),
                        "exact_match": bool(found_match),
                        "rejected": bool(rejected),
                        "max_distance": max_distance,
                        "min_fuzz_ratio": min_fuzz_ratio,
                    })

                    if rejected:
                        shortlist_parts = []
                        for j in range(min(len(ids), 5)):
                            dtxt = ""
                            if j < len(distances):
                                try:
                                    dtxt = f" d={float(distances[j]):.3f}"
                                except (TypeError, ValueError):
                                    dtxt = ""
                            shortlist_parts.append(f"{ids[j]}{dtxt}")
                        planned.note(
                            f"Entity resolution: {placeholder} -> rejected best embeddings candidate "
                            f"'{chosen_doc}' (distance={chosen_distance}, fuzz_ratio={chosen_ratio:.0f}) "
                            f"below confidence threshold (max_distance={max_distance}, min_fuzz_ratio={min_fuzz_ratio}); "
                            f"shortlist: {', '.join(shortlist_parts)}"
                        )
                        continue

                    first_record_id = ids[matched_result_position]
                    parts = str(first_record_id).split("_")
                    docid = parts[1] if len(parts) > 1 else None
                    doclang = parts[2] if len(parts) > 2 else "*"
                    if docid is None:
                        continue

                    if _plan_entity_row_substitution(
                        cursor=cursor,
                        planned=planned,
                        cfg=search_cfg,
                        docid=docid,
                        doclang=doclang,
                        message=f"Entity resolution: {{placeholder}} -> {{resolved}} (lang={doclang})",
                    ):
                        resolved = True
                        break

                if resolved:
                    continue

                planned.resolve_with(
                    _substitute_plain(placeholder, raw_value_sql, raw_value),
                    final_message=f"Entity resolution: {placeholder} -> {raw_value} (raw fallback)",
                    require_present=True,
                    is_raw_fallback=True,
                )

    return {
        "entities": planned_entities,
        "planning_time": time.time() - planning_start_time,
        "match_scores": match_scores,
    }


def apply_entity_resolutions(
    *,
    plan: dict,
    sql_query,
    justification,
    answer="",
    position_counter: int,
    text_message_cls,
    messages: list,
) -> dict[str, Any]:
    """Apply a resolution plan to the SQL, the justification and the answer.

    The cheap half of entity resolution: string substitution plus the diagnostics
    recorded while planning. Microseconds of work, which is why the expensive half
    can be started before the SQL even exists (FASTAPI-TEXT2SQL-201).

    Args:
        plan: The dict returned by :func:`plan_entity_resolutions`.
        sql_query: Generated SQL still carrying ``{{Placeholder}}`` tokens.
        justification: Justification text carrying the same tokens.
        answer: Answer template carrying the same tokens.
        position_counter: Next free position in the response ``messages`` array.
        text_message_cls: The ``TextMessage`` model used to append diagnostics.
        messages: The response message list, appended to in place.

    Returns:
        The resolved texts, the advanced ``position_counter``, the message list and
        ``ambiguous_question_for_text2sql`` (1 when placeholders survive in the SQL).
    """
    sql_query = sql_query or ""
    justification = justification or ""
    answer = answer or ""

    def add_message(text: str):
        """Append a positional diagnostic message to the response message list."""
        nonlocal position_counter
        messages.append(text_message_cls(position=position_counter, text=text))
        position_counter += 1

    ambiguous_question_for_text2sql = 0
    raw_fallback_count = 0

    for planned in (plan or {}).get("entities", []) or []:
        for text in planned.messages:
            add_message(text)

        if planned.substitution is None:
            continue

        if planned.require_present:
            placeholder = planned.placeholder
            if placeholder not in sql_query and placeholder not in justification and placeholder not in answer:
                continue

        sql_query, justification, answer = planned.substitution(sql_query, justification, answer)
        if planned.is_raw_fallback:
            raw_fallback_count += 1
        if planned.final_message:
            add_message(planned.final_message)

    unresolved_placeholders = re.findall(r"{{[^}]+}}", sql_query or "")
    if unresolved_placeholders:
        ambiguous_question_for_text2sql = 1
        unresolved_preview = ", ".join(unresolved_placeholders[:10])
        if len(unresolved_placeholders) > 10:
            unresolved_preview += ", ..."
        add_message(f"Unresolved placeholders remain in SQL after entity resolution: {unresolved_preview}")

    # NOTE: the repeated-descriptor collapse (_collapse_repeated_descriptor) is applied
    # once in main.py at response assembly, so it also covers the exact-question cache-hit
    # path that bypasses this function. Not applied here to avoid a second, redundant pass.
    return {
        "sql_query": sql_query,
        "justification": justification,
        "answer": answer,
        "position_counter": position_counter,
        "messages": messages,
        "ambiguous_question_for_text2sql": ambiguous_question_for_text2sql,
        # How many entities ended up with their raw words substituted because no configured
        # strategy matched. A non-zero count means the empty result that may follow is a
        # resolution failure, not a fact about the data (FASTAPI-TEXT2SQL-156).
        "raw_fallback_count": raw_fallback_count,
    }


def resolve_entities(
    *,
    connection,
    entity_extraction,
    sql_query,
    justification,
    answer="",
    position_counter: int,
    text_message_cls,
    messages: list,
    chromadb_collections_by_name: dict,
) -> dict[str, Any]:
    """Resolve extracted entities into concrete SQL, justification and answer substitutions.

    Sequential form: plan, then apply, back to back. Callers able to overlap the
    planning with another call (the text-to-SQL step) use the two halves directly.
    """
    plan = plan_entity_resolutions(
        connection=connection,
        entity_extraction=entity_extraction,
        chromadb_collections_by_name=chromadb_collections_by_name,
    )
    return apply_entity_resolutions(
        plan=plan,
        sql_query=sql_query,
        justification=justification,
        answer=answer,
        position_counter=position_counter,
        text_message_cls=text_message_cls,
        messages=messages,
    )
