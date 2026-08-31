import json
import os
import re
import time
import threading
import unicodedata
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

    __slots__ = ("key", "placeholder", "messages", "substitution", "final_message", "require_present", "is_raw_fallback", "is_unmatchable_raw_fallback")

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
        # True when that raw fallback carries no Latin letter, so the equality it produces
        # against a canonical name column cannot match anything (FASTAPI-TEXT2SQL-226).
        self.is_unmatchable_raw_fallback = False

    def note(self, text: str) -> None:
        """Record a diagnostic to be replayed when the plan is applied."""
        self.messages.append(text)

    def resolve_with(self, substitution, final_message=None, require_present: bool = False, is_raw_fallback: bool = False, is_unmatchable_raw_fallback: bool = False) -> None:
        """Attach the substitution that resolves this placeholder."""
        self.substitution = substitution
        self.final_message = final_message
        self.require_present = require_present
        self.is_raw_fallback = is_raw_fallback
        self.is_unmatchable_raw_fallback = is_unmatchable_raw_fallback


# FASTAPI-TEXT2SQL-225 / -226: a Latin letter anywhere means the value can plausibly match a
# canonical TMDb name column; none means it cannot.
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_INNER_WHITESPACE_RE = re.compile(r"\s+")


def fold_for_exactness(value: str) -> str:
    """Fold typographic variants so two spellings of the SAME name compare equal.

    FASTAPI-TEXT2SQL-225. `fuzz.ratio` on two strings of length `n` differing by `k`
    characters is `(n-k)/n`, so a single difference caps at 66.7 on a three-character name
    against a gate of 87.8. A name in Han characters is two to four characters long and a
    name in Hangul is three, which makes the fuzzy gate strict equality in disguise exactly
    where variant spellings are the rule.

    **The obvious fix is refused, and the data says why.** A length-scaled edit-distance
    tolerance would accept any one-character difference on a short name. But 黑澤明 (Akira
    Kurosawa) and 黑澤清 (Kiyoshi Kurosawa) are both directors, both in this database, and
    differ by exactly one character. Any such tolerance merges them.

    So this folding is wired into the EXACTNESS test only, never into the score. It can turn
    a near-miss into an exact match; it can never soften a partial one, and it cannot bring
    two genuinely different characters together. What it covers, measured:

    - a space inside a Han name, "宮崎 駿" against "宮崎駿", where the space carries no meaning
    - the full-width Latin forms, "ＡＫＩＲＡ" against "akira"
    - the CJK compatibility ideographs that carry an NFKC decomposition

    Two classes are NOT covered, both deliberately, and both measured rather than assumed:

    - the simplified/traditional and shinjitai/traditional pairs, 黒 (U+9ED2) against 黑
      (U+9ED1), 张艺谋 against 張藝謀, which are distinct unified ideographs
    - the compatibility ideographs Unicode left WITHOUT a decomposition, 﨑 (U+FA11) among
      them, which NFKC therefore leaves untouched

    Both would need a Unihan-derived table (kTraditionalVariant) or an OpenCC-class
    dependency. That is a decision to take deliberately, not a line to slip into this
    function, and the alias table already carries both spellings for many people, which may
    well make it moot.
    """
    if not value:
        return ""
    folded = unicodedata.normalize("NFKC", value).strip().lower()
    if not _LATIN_LETTER_RE.search(folded):
        folded = _INNER_WHITESPACE_RE.sub("", folded)
    return folded


def is_unmatchable_against_canonical(value: str) -> bool:
    """True when substituting `value` raw into a canonical Latin name column cannot match.

    FASTAPI-TEXT2SQL-226. When every configured strategy fails, the raw value is substituted
    as-is, which yields `WHERE T_WC_T2S_PERSON.PERSON_NAME = '<value>'`. That column holds the
    canonical TMDb name; the non-Latin spellings live in `T_WC_TMDB_PERSON_ALSO_KNOWN_AS` by
    design. A value carrying no Latin letter at all therefore cannot match, and the execution
    that follows is a guaranteed empty round trip before the stronger-model retry.

    A single Latin letter is enough to keep the old behaviour: "宮崎 Hayao" stays executable,
    and so does every misspelt Latin name, whose raw fallback does sometimes hit.
    """
    return bool(value) and not _LATIN_LETTER_RE.search(value)


def strip_declared_descriptors(value: str, search_cfg: dict) -> str:
    """Neutralise the generic descriptor words this strategy declares, if it declares any.

    FASTAPI-TEXT2SQL-227. `Collection_name` asks its rapidfuzz SEARCH to neutralise
    "collection" (`strip_franchise_stopwords`), and the search obeys: it ranks on
    COLLECTION_NAME_NORM, a generated column that is itself franchise-stripped. The GATE then
    scored the untouched display column, so it judged a pair of strings the search had never
    compared. Measured 2026-08-28 on "Who directed both jaws and the Indiana jones movie?":

        fuzz.ratio('indiana jones', 'indiana jones collection') = 70.27  against a gate of 72
        the same pair, descriptors neutralised                   = 100.0

    The search found the right collection and the gate turned it away over 1.73 points, which
    sent a correct SQL query into a raw fallback, zero rows, and a stronger-model retry.

    Read from `score_stopwords`, exactly like the embeddings branch does, so one entity type
    cannot hold two meanings for the same word across its own strategies. Falls back to the
    default franchise set when a strategy declares only `strip_franchise_stopwords`, so a gate
    can never again lag behind the search that same strategy configured.
    """
    words = search_cfg.get("score_stopwords")
    if words:
        return rapidfuzz_query.strip_franchise_words(value, words)
    if search_cfg.get("strip_franchise_stopwords"):
        return rapidfuzz_query.strip_franchise_words(value)
    return value


def resolution_key(value: str, search_cfg: dict) -> str:
    """Descriptors first, then typography: the key the confidence escape compares.

    Order matters. `strip_declared_descriptors` splits on whitespace, so it has to run before
    a fold that may remove whitespace. Monotone with respect to `fold_for_exactness`: two
    values equal after folding are still equal here, so FASTAPI-TEXT2SQL-225 keeps its
    behaviour to the letter and this can only ever admit more.
    """
    return fold_for_exactness(strip_declared_descriptors(value, search_cfg))


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

    # ---- TRACE COMPLETE DES BRANCHEMENTS (2026-08-30) --------------------------------
    #
    # OBJECTIF : la trace doit permettre de REJOUER le traitement d'une question a
    # posteriori. Toute decision qui change le sort d'un placeholder laisse donc un
    # `planned.note`, y compris, et surtout, les echecs.
    #
    # CE QUI A MOTIVE CET AUDIT. Le 2026-08-30, la resolution de {{Collection_name1}}
    # tombait en repli brut sans qu'on puisse savoir pourquoi : la branche RapidFuzz
    # sortait par `except Exception: continue` et par `best n'est pas un dict: continue`,
    # toutes deux MUETTES, et son seul message d'entree etait conditionne a Person_name.
    # L'absence de message ne distinguait donc pas trois situations opposees : la
    # strategie n'a pas tourne, elle a plante, elle n'a rien trouve. Un diagnostic a ete
    # construit sur cette ambiguite, puis dementi. Une sortie muette ne coute pas un
    # silence, elle coute une fausse conclusion.
    #
    # CE QUI RESTE VOLONTAIREMENT SANS NOTE, et c'est un choix, pas un oubli. Huit
    # sorties de boucle qui ne decident rien du sort du placeholder : la cle "question"
    # qui n'est pas un placeholder, le rang 0 de la shortlist deja juge comme `best`, les
    # `break`/`continue` qui suivent `resolved = True` et dont le succes est trace par le
    # `final_message` de `resolve_with`, et le parcours de rerang dont seul le verdict est
    # publie. Les tracer noierait la trace utile sous de la mecanique, ce qui reviendrait
    # au meme resultat qu'un trou : une trace qu'on ne lit plus.
    # ----------------------------------------------------------------------------------

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
                        planned.note(f"Entity resolution: {placeholder} -> empty value from extraction; placeholder left unresolved")
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
                        planned.note(f"Entity resolution: {placeholder} -> empty value from extraction; placeholder left unresolved")
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
                    planned.note(f"Entity resolution: {placeholder} has no strategy in entity_resolution.json; substituting the raw value")
                    raw_value = "" if value is None else str(value)
                    if raw_value.strip() == "":
                        planned.note(f"Entity resolution: {placeholder} -> empty value from extraction; placeholder left unresolved")
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
                    planned.note(f"Entity resolution: {placeholder} -> empty value from extraction; placeholder left unresolved")
                    continue

                raw_value_sql = _sql_escape_literal(raw_value)
                searches = _iter_entity_searches(cfg)
                resolved = False
                language_family = None
                if isinstance(key, str) and key.startswith("Person_name"):
                    try:
                        language_family = guess_language_family(raw_value)
                    except Exception as _exc:
                        planned.note(f"Entity resolution: {placeholder} language-family guess raised {type(_exc).__name__}: {_exc}; treating as unknown")
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
                            planned.note(f"Entity resolution: {placeholder} skipped a RapidFuzz strategy declaring no strtablename/strtableid; check entity_resolution.json")
                            continue

                        strcolumndesc = search_cfg.get("default_field")
                        strcolumndescnorm = search_cfg.get("rapidfuzz_col_norm") or (f"{strcolumndesc}_NORM" if strcolumndesc else None)
                        strcolumndesckey = search_cfg.get("rapidfuzz_col_key") or (f"{strcolumndesc}_KEY" if strcolumndesc else None)
                        strcolumnpopularity = search_cfg.get("rapidfuzz_col_popularity") or search_cfg.get("order_by") or "POPULARITY"
                        if not strcolumndesc or not strcolumndescnorm or not strcolumndesckey:
                            planned.note(f"Entity resolution: {placeholder} skipped the RapidFuzz strategy on {strtablename}: missing default_field / _NORM / _KEY column names")
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
                                except Exception as _exc:
                                    planned.note(f"Entity resolution: {placeholder} BK-tree unavailable for {strtablename}.{strcolumndescnorm} ({type(_exc).__name__}: {_exc}); the lexical search runs without it")
                                    bktree_idx = None
                            _rf_args = (
                                cursor,
                                strtablename,
                                strtableid,
                                strcolumndesc,
                                strcolumndescnorm,
                                strcolumndesckey,
                                strcolumnpopularity,
                            )
                            rapidfuzz_result = rapidfuzz_query.search_first_match(
                                *_rf_args,
                                raw=raw_value,
                                has_fulltext=has_fulltext,
                                timings_enabled=False,
                                bktree=bktree_idx,
                                # FASTAPI-TEXT2SQL-214 / -218: the metric is declared by the
                                # entity, and the SAME one is used to rank here and to judge
                                # below. Absent from a strategy, it falls back to `ratio`, so
                                # every strategy that says nothing keeps its old behaviour.
                                score_metric=search_cfg.get("score_metric"),
                                max_extra_tokens=int(
                                    search_cfg.get("max_extra_tokens", rapidfuzz_query.DEFAULT_MAX_EXTRA_TOKENS)
                                ),
                                # FASTAPI-TEXT2SQL-218, Do #3. Declared only by strategies whose
                                # table has no popularity of its own (the alias table), so a tie
                                # is broken by the person's real popularity instead of by their
                                # TMDb id, which ranked the most recently added first.
                                popularity_join=search_cfg.get("popularity_join"),
                                # Neutralize generic franchise words (collections): "Star Wars
                                # universe" ~ "Star Wars Collection". Applied to the query and,
                                # in-memory, to each candidate NORM, so no stored-column backfill
                                # is required. Opt-in per strategy in entity_resolution.json.
                                strip_stopwords=bool(search_cfg.get("strip_franchise_stopwords")),
                            )
                        except Exception as _exc:
                            planned.note(f"Entity resolution: {placeholder} RapidFuzz search on {strtablename} RAISED {type(_exc).__name__}: {_exc}; falling through to the next strategy")
                            continue

                        # Le repli A (2026-08-30) a ete RETIRE le 2026-08-31, et la raison
                        # merite d'etre gardee. Il rejouait la recherche avec
                        # strip_stopwords=False quand la premiere revenait vide, sur l'idee que
                        # le descripteur aiderait a TROUVER. La lecture de fetch_candidates dit
                        # le contraire sur cette implementation : le plein texte est CONJONCTIF
                        # (+token* sur chacun des trois tokens les plus longs) et le LIKE de
                        # dernier recours ne garde que tokens[0], le mot le plus LONG. Rejouer
                        # sans neutralisation EXIGE donc un mot de plus et, sur « collection
                        # criterion », deplace le LIKE de '%criterion%' vers '%collection%'.
                        # Le repli ne pouvait pas elargir, il ne pouvait que nuire.
                        #
                        # Ce que le repli visait vraiment est traite en amont desormais : la
                        # correspondance exacte et la cle de prefixe lisent la forme complete
                        # (rapidfuzz_query.py, -236), et le garde empty_query teste cette meme
                        # forme, si bien qu'une valeur faite uniquement de descripteurs garde
                        # ses canaux au lieu de ne rien rendre.
                        if not isinstance(best, dict):
                            planned.note(f"Entity resolution: {placeholder} -> no RapidFuzz candidate at all in {strtablename} for '{raw_value}'; falling through to the next strategy")
                            continue

                        # Same measurement as the embeddings path (FASTAPI-TEXT2SQL-206), and
                        # deliberately the same metric: fuzz.ratio between the sought value and
                        # the matched text, which is exactly what min_fuzz_ratio gates on. Using
                        # rapidfuzz's own internal score instead would produce two scales that
                        # cannot be compared when calibrating.
                        #
                        # FASTAPI-TEXT2SQL-218 completes that reasoning. It was right about the
                        # SCALE and silent about the CHOICE: ranking still ran on WRatio, so the
                        # gate measured, correctly, a candidate that had been selected by another
                        # rule. `rank_candidates` now ranks with this same metric, and the
                        # strategy declares which one. The strings compared are deliberately
                        # unchanged (raw value against the display column, both lowercased, not
                        # the NORM column the ranker uses), so the thresholds calibrated by -206
                        # keep the meaning they were measured with.
                        # Initialises avant le try : le garde ci-dessous les lit, et un echec
                        # precoce du bloc les laisserait indefinis.
                        _matched_text = ""
                        _sought_norm = ""
                        _matched_norm = ""
                        _sought_fold = ""
                        _matched_fold = ""
                        _sought_key = ""
                        _matched_key = ""
                        _rf_ratio = None
                        try:
                            _matched_text = str(best.get(strcolumndesc) or "") if strcolumndesc else ""
                            _sought_norm = raw_value.strip().lower()
                            _matched_norm = _matched_text.strip().lower()
                            # FASTAPI-TEXT2SQL-225: exactness only, never the score.
                            _sought_fold = fold_for_exactness(_sought_norm)
                            _matched_fold = fold_for_exactness(_matched_norm)
                            # FASTAPI-TEXT2SQL-227: same escape, one step wider.
                            _sought_key = resolution_key(_sought_norm, search_cfg)
                            _matched_key = resolution_key(_matched_norm, search_cfg)
                            _rf_metric = rapidfuzz_query.resolve_score_metric(search_cfg.get("score_metric"))
                            _rf_max_extra = int(
                                search_cfg.get("max_extra_tokens", rapidfuzz_query.DEFAULT_MAX_EXTRA_TOKENS)
                            )
                            # FASTAPI-TEXT2SQL-236, volet 1. La garde notait les colonnes
                            # d'AFFICHAGE pendant que le classement comparait des chaines
                            # neutralisees : elle jugeait un couple que la recherche n'avait
                            # jamais compare. Mesure du 2026-08-30 sur Criterion :
                            # ratio('collection criterion', 'the criterion collection') = 54,5
                            # contre une garde a 72, alors que le meme couple neutralise vaut
                            # 81,8. Le candidat etait le BON et il partait en repli brut.
                            #
                            # Le sens du deplacement est connu et va dans le bon sens : un vrai
                            # positif MONTE (54,5 vers 81,8) et un faux positif DESCEND
                            # ("wagonlit collection" contre "life collection" tombe de 76,5 a
                            # 33,3, mesure du 2026-08-24). La garde devient donc plus
                            # discriminante, pas plus laxiste. C'est aussi pourquoi les seuils
                            # doivent etre recalibres au banc plutot que deduits de deux points.
                            _rf_ratio = (
                                _rf_metric(
                                    strip_declared_descriptors(_sought_norm, search_cfg),
                                    strip_declared_descriptors(_matched_norm, search_cfg),
                                    max_extra_tokens=_rf_max_extra,
                                )
                                if _matched_norm
                                else 0.0
                            )
                            match_scores.append({
                                "placeholder": placeholder,
                                "search_mode": "rapidfuzz",
                                "collection": search_cfg.get("collection"),
                                # La table, et pas seulement la collection : les deux strategies
                                # Person_name declarent toutes deux `persons`, seule la table les
                                # distingue (T_WC_T2S_PERSON contre la table des alias). Sans elle
                                # on ne peut pas savoir laquelle a produit un score, ce qui est
                                # indispensable pour calibrer la seconde (FASTAPI-TEXT2SQL-206).
                                "table": search_cfg.get("strtablename"),
                                "sought": raw_value,
                                "candidate": _matched_text,
                                "distance": None,
                                "fuzz_ratio": round(float(_rf_ratio), 1),
                                "exact_match": _sought_norm == _matched_norm,
                                # Same test after typographic folding, recorded separately so the
                                # bench can weigh what the folding admits (FASTAPI-TEXT2SQL-225).
                                "exact_match_folded": _sought_fold == _matched_fold,
                                # And once the declared descriptors are neutralised too, which
                                # is what the escape actually tests (FASTAPI-TEXT2SQL-227).
                                "exact_match_descriptors": _sought_key == _matched_key,
                                "rejected": False,
                                "auto": bool((rapidfuzz_result or {}).get("auto")),
                                "min_fuzz_ratio": search_cfg.get("min_fuzz_ratio"),
                                # FASTAPI-TEXT2SQL-214: the bench compares distributions, and two
                                # metrics produce two distributions. A score without the name of
                                # the rule that produced it cannot be calibrated against anything.
                                "score_metric": (search_cfg.get("score_metric") or rapidfuzz_query.DEFAULT_SCORE_METRIC),
                            })
                        except Exception as _exc:
                            planned.note(f"Entity resolution: {placeholder} could not score the RapidFuzz candidate ({type(_exc).__name__}: {_exc}); confidence judged without a ratio")
                            _rf_ratio = None

                        # Confidence gate, rapidfuzz side (FASTAPI-TEXT2SQL-206). `min_fuzz_ratio`
                        # existed but was read ONLY in the embeddings branch, so declaring it on a
                        # rapidfuzz strategy did strictly nothing. That is why Person_name, which
                        # is rapidfuzz-only, could never fail: it always returned its best match
                        # however far, and invented names resolved to real people
                        # ("Zamboni-Trask" -> "Massimo Zamboni" at 50.0).
                        #
                        # Same semantics as the embeddings gate, to the letter: an exact
                        # normalized match always passes, a rejection falls through to the next
                        # strategy and, failing that, to the raw fallback the complex-question
                        # retry then catches.
                        # FASTAPI-TEXT2SQL-225 and -227: the exactness escape runs on a key that
                        # neutralises the descriptors this strategy declares, then folds
                        # typographic variants. **The score itself is deliberately untouched.**
                        # The comment above is right that -206 calibrated every threshold on the
                        # raw display column, and moving that scale would invalidate all of them
                        # at once. Widening the ESCAPE costs the calibration nothing, because an
                        # escape admits equality and never a near miss. It is also what keeps
                        # 黑澤明 and 黑澤清 apart: neither folding nor stripping ever turns one
                        # character into another.
                        if (
                            _sought_key
                            and _sought_key == _matched_key
                            and _sought_norm != _matched_norm
                        ):
                            planned.note(
                                f"Entity resolution: {placeholder} -> exact once descriptors and "
                                f"typography are neutralised ('{raw_value}' = '{_matched_text}'), "
                                f"confidence gate skipped"
                            )
                        _rf_min = search_cfg.get("min_fuzz_ratio")
                        _rf_rejected = (
                            _rf_min is not None
                            and _rf_ratio is not None
                            and _sought_key != _matched_key
                            and _rf_ratio < _rf_min
                        )
                        # FASTAPI-TEXT2SQL-224. The gate read `ranked[0]` and gave up, while
                        # `search_first_match` returns a shortlist of ten. Walking it changes
                        # nothing about WHAT the gate accepts, every candidate facing the same
                        # threshold and the same folding escape of -225; it changes how many
                        # candidates the gate is allowed to see. Rank order is preserved, so the
                        # first that passes wins, exactly as if it had been ranked first.
                        if _rf_rejected:
                            for _rank, _cand in enumerate((rapidfuzz_result or {}).get("ranked") or []):
                                if _rank == 0 or not isinstance(_cand, dict):
                                    continue
                                try:
                                    _cand_text = str(_cand.get(strcolumndesc) or "") if strcolumndesc else ""
                                    _cand_norm = _cand_text.strip().lower()
                                    if not _cand_norm:
                                        planned.note(f"Entity resolution: {placeholder} shortlist rank {_rank + 1} carries no comparable text; candidate skipped")
                                        continue
                                    _cand_fold = fold_for_exactness(_cand_norm)
                                    # FASTAPI-TEXT2SQL-227: the shortlist walk judges by the same
                                    # rule as the first entry, descriptors included, otherwise a
                                    # candidate could be accepted at rank 1 and refused at rank 4
                                    # on a difference the strategy itself declared meaningless.
                                    _cand_key = resolution_key(_cand_norm, search_cfg)
                                    # Meme echelle que la garde ci-dessus (-236) : sans cela un
                                    # candidat serait accepte au rang 1 et refuse au rang 4 sur
                                    # une difference que la strategie declare non identifiante.
                                    _cand_ratio = float(_rf_metric(
                                        strip_declared_descriptors(_sought_norm, search_cfg),
                                        strip_declared_descriptors(_cand_norm, search_cfg),
                                        max_extra_tokens=_rf_max_extra))
                                except Exception as _exc:
                                    planned.note(f"Entity resolution: {placeholder} could not score shortlist rank {_rank + 1} ({type(_exc).__name__}: {_exc}); candidate skipped")
                                    continue
                                if (_sought_key and _sought_key == _cand_key) or _cand_ratio >= _rf_min:
                                    best = _cand
                                    _matched_text, _matched_norm, _matched_fold = _cand_text, _cand_norm, _cand_fold
                                    _matched_key = _cand_key
                                    _rf_ratio = _cand_ratio
                                    _rf_rejected = False
                                    if match_scores and match_scores[-1].get("search_mode") == "rapidfuzz":
                                        match_scores[-1].update({
                                            "candidate": _cand_text,
                                            "fuzz_ratio": round(_cand_ratio, 1),
                                            "rescued_rank": _rank,
                                        })
                                    planned.note(
                                        f"Entity resolution: {placeholder} -> top RapidFuzz candidate refused, "
                                        f"accepted '{_cand_text}' found at rank {_rank + 1} of the shortlist "
                                        f"(fuzz_ratio={_cand_ratio:.0f}, min_fuzz_ratio={_rf_min}) in {strtablename}"
                                    )
                                    break
                        if _rf_rejected:
                            if match_scores and match_scores[-1].get("search_mode") == "rapidfuzz":
                                match_scores[-1]["rejected"] = True
                            planned.note(
                                f"Entity resolution: {placeholder} -> rejected best RapidFuzz candidate "
                                f"'{_matched_text}' (fuzz_ratio={_rf_ratio:.0f}) below confidence "
                                f"threshold (min_fuzz_ratio={_rf_min}) in {strtablename}"
                            )
                            continue

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
                            except Exception as _exc:
                                planned.note(f"Entity resolution: {placeholder} canonical lookup raised {type(_exc).__name__}: {_exc}")
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
                        planned.note(f"Entity resolution: {placeholder} skipped a strategy declaring an unknown search_mode '{search_mode}'; check entity_resolution.json")
                        continue

                    collection_name = search_cfg.get("collection")
                    current_collection = chromadb_collections_by_name.get(collection_name)
                    if current_collection is None:
                        planned.note(f"Entity resolution: {placeholder} skipped the embeddings strategy: ChromaDB collection '{collection_name}' is not loaded")
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
                            except Exception as _exc:
                                planned.note(f"Entity resolution: {placeholder} year-filtered search raised {type(_exc).__name__}: {_exc}; falling back to the unfiltered search")
                                results = None
                    if results is None:
                        results = current_collection.query(query_texts=[raw_value], n_results=10)
                    documents = (results.get("documents", [[]]) or [[]])[0] or []
                    ids = (results.get("ids", [[]]) or [[]])[0] or []
                    distances = (results.get("distances", [[]]) or [[]])[0] or []
                    if not documents or not ids:
                        planned.note(f"Entity resolution: {placeholder} -> ChromaDB collection '{collection_name}' returned no candidate for '{raw_value}'; falling through to the next strategy")
                        continue

                    matched_result_position = 0
                    found_match = False
                    # FASTAPI-TEXT2SQL-228. Ce que le rerang a compare, garde pour la trace.
                    # Initialise ici et pas dans la branche qui le remplit : la trace se lit
                    # apres, et une liste absente y ferait une NameError, exactement le defaut
                    # de 2026-08-29 ou une variable deplacee avait laisse son lecteur derriere.
                    _rerank_scores = []
                    _rerank_cut = False
                    try:
                        target_value_norm = raw_value.strip().lower()
                    except Exception as _exc:
                        planned.note(f"Entity resolution: {placeholder} could not normalise the sought value ({type(_exc).__name__}: {_exc}); exact-match pass disabled")
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
                        # FASTAPI-TEXT2SQL-224: coupe au meme separateur que le garde. Ce rerang
                        # est une comparaison LEXICALE, et l'argument de -206 vaut ici mot pour
                        # mot : la description a sa place dans l'espace vectoriel et rien a faire
                        # dans une mesure d'edition. Mesure du 2026-08-29 sur « flamenco trilogy »,
                        # le document indexe etant « The Flamenco Trilogy: One of Spanish cinema's
                        # great auteurs... » : sur le document entier il note 90, a egalite avec
                        # « Carlos Saura's Flamenco trilogy », donc le premier rencontre gagnait ;
                        # sur le nom seul il note 95 et gagne. Sans separateur declare, rien ne
                        # change, la coupe etant opt-in par entite.
                        _rerank_sep = search_cfg.get("document_name_separator")
                        best_score = -1.0
                        for i, document in enumerate(documents):
                            if not isinstance(document, str):
                                planned.note(f"Entity resolution: {placeholder} rerank skipped rank {i + 1}: the ChromaDB document is not text")
                                continue
                            _doc_cmp = document.strip().lower()
                            if _rerank_sep and _rerank_sep in _doc_cmp:
                                _doc_cmp = _doc_cmp.split(_rerank_sep, 1)[0].strip()
                                _rerank_cut = True
                            score = fuzz.WRatio(target_value_norm, _doc_cmp)
                            _rerank_scores.append((i, _doc_cmp, float(score)))
                            if score > best_score:
                                best_score = score
                                matched_result_position = i

                    # FASTAPI-TEXT2SQL-228. Dire COMMENT le candidat a ete choisi, pas seulement
                    # lequel. Trois etages decident sur cette voie, la correspondance exacte, le
                    # rerang lexical et le garde, et jusqu'ici seul le dernier parlait. Le cas
                    # « flamenco trilogy » du 2026-08-29 a ete repare par le DEUXIEME, invisible :
                    # la trace montrait la bonne reponse sans montrer qui l'avait choisie, ce qui
                    # rend un correctif indistinguable d'un autre au moment de lire un journal.
                    def _doc_short(_t, _n=48):
                        _t = str(_t or "")
                        return _t if len(_t) <= _n else _t[: _n - 1] + "…"

                    if found_match:
                        planned.note(
                            f"Entity resolution: {placeholder} -> embeddings shortlist of "
                            f"{len(documents)} candidates, exact document match at rank "
                            f"{matched_result_position + 1} "
                            f"('{_doc_short(documents[matched_result_position])}'); gate skipped"
                        )
                    elif _rerank_scores:
                        _ranked = sorted(_rerank_scores, key=lambda t: (-t[2], t[0]))
                        _win = next((t for t in _rerank_scores if t[0] == matched_result_position), None)
                        _runner = next((t for t in _ranked if t[0] != matched_result_position), None)
                        _msg = (
                            f"Entity resolution: {placeholder} -> embeddings returned "
                            f"{len(documents)} candidates ordered by vector distance; lexical "
                            f"rerank picked rank {matched_result_position + 1} "
                            f"'{_doc_short(_win[1]) if _win else ''}' (WRatio={_win[2]:.0f})"
                            if _win else
                            f"Entity resolution: {placeholder} -> embeddings returned "
                            f"{len(documents)} candidates"
                        )
                        if _runner and _win:
                            _msg += (
                                f", ahead of rank {_runner[0] + 1} '{_doc_short(_runner[1])}' "
                                f"(WRatio={_runner[2]:.0f})"
                            )
                        if _rerank_cut:
                            # Sans cette mention, un document coupe et un document court se
                            # ressemblent dans le journal, alors que la coupe est justement ce
                            # qui a change le classement le 2026-08-29.
                            _msg += (
                                f"; documents cut at '{search_cfg.get('document_name_separator')}' "
                                f"before scoring"
                            )
                        planned.note(_msg)

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
                    # Lu une seule fois, au niveau exterieur, parce que DEUX endroits en ont
                    # besoin : la closure ci-dessous pour scorer, et `match_scores` plus bas pour
                    # tracer `stopwords_applied`. Le refactor de -224 l'avait deplace dans la
                    # closure sous le nom `_stop` en laissant la trace pointer sur l'ancien nom,
                    # d'ou une NameError sur toute resolution par embeddings, donc un 500 sur
                    # chaque question atteignant cette branche. Une seule source, deux lecteurs.
                    _score_stopwords = search_cfg.get("score_stopwords")

                    # FASTAPI-TEXT2SQL-224. Scoring moved into a function because it is now
                    # applied to more than one candidate. Same computation as before, to the
                    # letter; only the number of candidates it is called on changes.
                    def _score_candidate(pos):
                        _doc = documents[pos] if pos < len(documents) else ""
                        _doc_norm = _doc.strip().lower() if isinstance(_doc, str) else ""
                        # Certaines collections indexent "nom<sep>description", ce qui aide beaucoup
                        # la recherche semantique et ruine la comparaison lexicale : mesure du
                        # 2026-08-25, "Blaxploitation" contre "Blaxploitation: Here is the list of..."
                        # note 2,3 alors que c'est une correspondance PARFAITE. La description a sa
                        # place dans l'espace vectoriel et rien a faire dans un ratio d'edition.
                        # Declare par entite, jamais globalement : un nom peut legitimement contenir
                        # le separateur ("Star Trek: The Next Generation"), et decouper a l'aveugle le
                        # tronquerait. Le nom nu sert AUSSI de candidat rapporte, pour que le banc et
                        # les journaux montrent ce qui a reellement ete compare.
                        _sep = search_cfg.get("document_name_separator")
                        _doc_shown = _doc
                        if _sep and _doc_norm and _sep in _doc_norm:
                            _doc_norm = _doc_norm.split(_sep, 1)[0].strip()
                            if isinstance(_doc_shown, str) and _sep in _doc_shown:
                                _doc_shown = _doc_shown.split(_sep, 1)[0].strip()
                        _dist = None
                        if pos < len(distances):
                            try:
                                _dist = float(distances[pos])
                            except (TypeError, ValueError) as _exc:
                                planned.note(f"Entity resolution: {placeholder} unreadable ChromaDB distance at rank {pos + 1} ({type(_exc).__name__}); scored without it")
                                _dist = None
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
                        _stop = _score_stopwords
                        _sought_s, _cand_s = target_value_norm, _doc_norm
                        if _stop:
                            try:
                                _sought_s = rapidfuzz_query.strip_franchise_words(target_value_norm, _stop)
                                _cand_s = rapidfuzz_query.strip_franchise_words(_doc_norm, _stop)
                            except Exception as _exc:
                                planned.note(f"Entity resolution: {placeholder} descriptor neutralisation failed at rank {pos + 1} ({type(_exc).__name__}: {_exc}); scored on the raw strings, which INFLATES a shared descriptor")
                                _sought_s, _cand_s = target_value_norm, _doc_norm
                        _ratio = fuzz.ratio(_sought_s, _cand_s) if _cand_s else 0.0
                        # Kept for calibration: what the score would have been without stripping, so
                        # the bench can weigh the two and the effect stays auditable.
                        _ratio_raw = fuzz.ratio(target_value_norm, _doc_norm) if _doc_norm else 0.0
                        _dist_ok = (max_distance is None) or (_dist is None) or (_dist <= max_distance)
                        _ratio_ok = (min_fuzz_ratio is None) or (_ratio >= min_fuzz_ratio)
                        return {
                            "pos": pos, "doc": _doc_shown, "doc_norm": _doc_norm, "distance": _dist,
                            "ratio": _ratio, "ratio_raw": _ratio_raw,
                            "passes": bool(_dist_ok and _ratio_ok),
                        }

                    _top = _score_candidate(matched_result_position)
                    _chosen = _top
                    _rescued_rank = None
                    if not found_match and not _top["passes"]:
                        # FASTAPI-TEXT2SQL-224. The gate used to read the first candidate and give
                        # up. Measured 2026-08-28 on "Movies in the flamenco trilogy": the vector
                        # search ranked "Carlos Saura's Flamenco trilogy" first (d=0.360, ratio 52,
                        # refused) and "The Flamenco Trilogy" second (d=0.516, ratio 80), which
                        # would have passed the same threshold of 72. The right answer was in the
                        # shortlist, one row down, and nobody looked.
                        #
                        # Walking the rest of the shortlist cannot loosen anything: every candidate
                        # is judged by the SAME thresholds, so this only turns rejections into
                        # acceptances that the gate itself approves. What changes is how many
                        # candidates the gate is allowed to see, not what it accepts.
                        for _pos in range(len(documents)):
                            if _pos == matched_result_position:
                                continue
                            _try = _score_candidate(_pos)
                            if _try["passes"]:
                                _chosen, _rescued_rank = _try, _pos
                                matched_result_position = _pos
                                break

                    chosen_doc = _chosen["doc"]
                    chosen_distance = _chosen["distance"]
                    chosen_ratio = _chosen["ratio"]
                    chosen_ratio_raw = _chosen["ratio_raw"]
                    distance_ok = (max_distance is None) or (chosen_distance is None) or (chosen_distance <= max_distance)
                    ratio_ok = (min_fuzz_ratio is None) or (chosen_ratio >= min_fuzz_ratio)
                    rejected = (not found_match) and not (distance_ok and ratio_ok)
                    match_scores.append({
                        "placeholder": placeholder,
                        "search_mode": "embeddings",
                        "collection": collection_name,
                        "table": search_cfg.get("strtablename"),
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
                        # FASTAPI-TEXT2SQL-224: rank at which the accepted candidate was found,
                        # None when it was the first. The bench needs it to answer the only
                        # question that matters here, how often the right answer was NOT first.
                        "rescued_rank": _rescued_rank,
                    })

                    if _rescued_rank is not None:
                        planned.note(
                            f"Entity resolution: {placeholder} -> top embeddings candidate refused, "
                            f"accepted '{chosen_doc}' found at rank {_rescued_rank + 1} of the shortlist "
                            f"(distance={chosen_distance}, fuzz_ratio={chosen_ratio:.0f}, "
                            f"min_fuzz_ratio={min_fuzz_ratio})"
                        )

                    # FASTAPI-TEXT2SQL-228. L'acceptation etait muette sur ses chiffres, et c'est
                    # l'asymetrie qui coute : un refus disait pourquoi, une acceptation ne disait
                    # rien. Or la question « de combien est-on passe » se pose autant dans un cas
                    # que dans l'autre, et c'est elle qui permet de regler un seuil sans deviner.
                    if _rescued_rank is None and not rejected and not found_match:
                        _bits = [f"fuzz_ratio={chosen_ratio:.0f}"]
                        if min_fuzz_ratio is not None:
                            _bits.append(f"min={min_fuzz_ratio}")
                        if chosen_distance is not None:
                            _bits.append(f"distance={chosen_distance:.3f}")
                        if max_distance is not None:
                            _bits.append(f"max_distance={max_distance}")
                        if _score_stopwords:
                            # Le score brut vaut d'etre montre a cote du score retenu : l'ecart
                            # entre les deux EST l'effet du retrait des descripteurs, mesurable
                            # au lieu d'etre suppose.
                            _bits.append(f"before_stopwords={chosen_ratio_raw:.0f}")
                        planned.note(
                            f"Entity resolution: {placeholder} -> gate accepted rank "
                            f"{matched_result_position + 1} '{_doc_short(chosen_doc)}' "
                            f"({', '.join(_bits)})"
                        )

                    if rejected:
                        shortlist_parts = []
                        for j in range(min(len(ids), 5)):
                            dtxt = ""
                            if j < len(distances):
                                try:
                                    dtxt = f" d={float(distances[j]):.3f}"
                                except (TypeError, ValueError):
                                    dtxt = ""
                            # FASTAPI-TEXT2SQL-224: the TEXT that was compared, not only its id.
                            # The shortlist listed ids and distances, so a rejection could not be
                            # re-derived from the trace: reading it required guessing what the
                            # collection had indexed. On 2026-08-29 that guess was wrong, the
                            # documents turned out not to be the bare names, and a whole diagnosis
                            # rested on it. An id says which row, the document says what the gate
                            # actually scored, and only the second explains a refusal.
                            _dj = documents[j] if j < len(documents) else ""
                            _dj = _dj.strip() if isinstance(_dj, str) else ""
                            if len(_dj) > 60:
                                _dj = _dj[:57] + "..."
                            shortlist_parts.append(f"{ids[j]}{dtxt} '{_dj}'")
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

                # FASTAPI-TEXT2SQL-226. Only reached when a resolver WAS configured for this
                # key and every one of its strategies failed; an unconfigured key takes the
                # 'generic' path above and never lands here. So the target really is a
                # canonical name column, and a value with no Latin letter cannot match it.
                _unmatchable = is_unmatchable_against_canonical(raw_value)
                planned.resolve_with(
                    _substitute_plain(placeholder, raw_value_sql, raw_value),
                    final_message=(
                        f"Entity resolution: {placeholder} -> {raw_value} (raw fallback"
                        + (", unmatchable against a canonical Latin name column)" if _unmatchable else ")")
                    ),
                    require_present=True,
                    is_raw_fallback=True,
                    is_unmatchable_raw_fallback=_unmatchable,
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
    raw_fallback_unmatchable_count = 0

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
            if planned.is_unmatchable_raw_fallback:
                raw_fallback_unmatchable_count += 1
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
        # Of those, how many carry no Latin letter at all, so the equality they produce
        # against a canonical name column is a guaranteed empty round trip
        # (FASTAPI-TEXT2SQL-226).
        "raw_fallback_unmatchable_count": raw_fallback_unmatchable_count,
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
