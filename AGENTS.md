# AGENTS.md - Agent Guide for FastAPI Text2SQL

This file gives you the agentic context you need to work on this codebase safely. For project overview, features, install / deploy steps, API request / response examples, sample queries, and human-facing security / performance / troubleshooting material, read @README.md — that file is canonical and not duplicated here.

This is the single canonical guide for autonomous coding agents in this repository. Assistant-specific files such as @CLAUDE.md, and any future tool-specific guide such as `GEMINI.md`, should only point here and should not duplicate repository instructions.

Deeper specs live in their own files:
- @MCP.md — full MCP integration guide (tool code, resource reference, client setup, bearer token, end-to-end flow)
- @RAPIDFUZZ.md — RapidFuzz setup and SQL schema requirements
- @eval/README.md — evaluation harness
- @doc/sql/*.sql — reference DDL for the database schema; treat these files as read-only unless the user explicitly asks you to edit schema documentation

- For any project update, keep documentation aligned:
  - Update `README.md` for user-facing behavior, configuration, setup, deployment, troubleshooting, or verification changes.
  - Update also docstrings for API endpoints documentation when there are changes in the API. 
  - Update this file only when agent workflow or safety context changes.

---

## Related repositories (project ecosystem)

`fastapi-text2sql` is one stage of **Agent BBB**, a multi-repository movie/TV database system owned by GitHub user `vaugouin`. All sibling repos live under `%USERPROFILE%/Code/<repo>` and at `github.com/vaugouin/<repo>`; they are interdependent stages of one pipeline that converges on a shared MySQL/MariaDB database (`T_WC_*` tables) and a ChromaDB vector store. The canonical roster of sibling repositories is kept in `doc/related-repositories/related-repositories.txt` in the `tmdb-front` repo.

Pipeline stages:
- **Infrastructure** — `python` (shared crawler base image), `chromadb` (vector service), `reverseproxy` (NGINX TLS ingress), `chromadb-security-test` (firewall validation).
- **Acquisition** — `tmdb-crawler`, `imdb-crawler`, `sparql-crawler`, `sparql-movies-persons`, `wikidata-crawler`, `wikipedia-crawler`, `selenium-tmdb`, `download-images`, `sqlite-plex-to-tmdb`, `movieparadise`.
- **Preprocessing → `T_WC_T2S_*`** — `tmdb-movie-preprocess`, `tmdb-person-preprocess`, `keywords-processing`.
- **Semantic index & name resolution** — `embedding-update`, `embedding-query`, `rapidfuzz_query`.
- **Serving** — `fastapi-text2sql` (NL→SQL API + MCP server), `voice-agent`, `tmdb-front` (PHP web front-end).
- **Evaluation** — `eval-text2sql`, `extract-movie-questions`.
- **Maintenance & tooling** — `plex-duplicates`, `subtitle-translate`, `powershell`, `playwright-test`.
- **Monitoring & observability** — `data-monitoring`.

**This repository's role:** Serving stage and the engine of the system. A REST API (plus an MCP server) that converts natural-language questions into SQL over the `T_WC_T2S_*` read-model, resolving entities via the ChromaDB collections (`embedding-update`) and the `rapidfuzz_query` person-name module. It is the backend behind `tmdb-front`'s `text2sql-search.php` and the `voice-agent` conversational client, and the target scored by `eval-text2sql`.

---

## Where things live (file → role)

Edit at the right layer; the architecture is intentionally split.

**[main.py](main.py)** (~2460 lines) — FastAPI app, ChromaDB / DB startup, request orchestration only.
- Version utilities: `format_api_version()` ([main.py:33](main.py#L33)), `compare_versions()` ([main.py:38](main.py#L38))
- `strapiversion` lives at [main.py:105](main.py#L105) (also drives Blue/Green port parity and `MCP_INTERNAL_BASE_URL`)
- `Text2SQLRequest` / `Text2SQLResponse` Pydantic models around [main.py:214-269](main.py#L214-L269)
- `POST /search/text2sql` — main pipeline endpoint
- 17 entity detail endpoints (movies, series, seasons, episodes, persons, companies, networks, collections, topics, lists, movements, technicals, groups, deaths, awards, nominations, locations). `seasons` and `episodes` are keyed on composite paths (`/seasons/{id_serie}/{season_number}`, `/episodes/{id_serie}/{season_number}/{episode_number}`) and currently read from `T_WC_TMDB_*` source tables — see [SEASONS_AND_EPISODES.md](SEASONS_AND_EPISODES.md) §6.1.
- FastMCP instance + 16 MCP tools (`sql_search` + 15 entity tools), 1 resource (`context://database-scope`), bearer-token middleware, `app.mount("", mcp_app)` at root. The `seasons` and `episodes` HTTP endpoints do not yet have MCP wrappers (tracked in [SEASONS_AND_EPISODES.md](SEASONS_AND_EPISODES.md) §3 "MCP coverage")

**[text2sql.py](text2sql.py)** — core LLM logic.
- `_call_chat_llm()` — unified multi-provider dispatcher (OpenAI / Anthropic / Google). Routes on prefix: `gpt-*`/`o1*`/`o3*` → OpenAI; `claude-*` → Anthropic; `gemini-*` → Google.
- `f_text2sql(user_question, model, ui_language)` — text-to-SQL conversion; replaces `{ui_language}` in the prompt template so the LLM generates the `answer` field in the requested language.
- `f_resolve_complex_question()` / `f_resolve_complex_question_retry_payload()` — complex-question simplification via stronger model.
- `f_build_retry_question_from_reasoning()` — deterministic retry-question composer (typed entities + years).
- `f_answer_single_value()` — direct-answer path for single-cell zero-count results.
- Hot-reloads `text_to_sql.md` and `complex_question.md` via `data_watcher`.

**[entity.py](entity.py)** — entity extraction + resolution.
- `f_entity_extraction()` — LLM-based extraction + anonymization.
- `resolve_entities()` — main resolver: regex-validated branch → closed-vocab branches → embeddings/RapidFuzz from `entity_resolution.json` → raw fallback.
- `_match_regex_placeholder_rule()` — dispatch helper for regex placeholders.
- `_REGEX_PLACEHOLDER_RULES` — list of `(prefix, regex, is_numeric)` tuples; **order matters** (uses `startswith()`).
- Hot-reloads `entity_extraction.md` and `entity_resolution.json` via `data_watcher`.

**[closed_vocab.py](closed_vocab.py)** — closed-vocabulary lookups (DB canonicals + JSON aliases + RapidFuzz typo tolerance).
- `init(connection)` — loads canonicals at startup. Called once from `main.py` startup.
- `resolve(entity, raw_value)` — string-canonical lookup (`Status_name`, `Serie_type`, `Department_name`).
- `resolve_genre(raw)` / `resolve_technical(raw)` — integer-ID lookups (`ID_GENRE`, `ID_TECHNICAL`).
- Aliases hot-reload from [data/closed_vocabularies.json](data/closed_vocabularies.json).

**[rapidfuzz_query.py](rapidfuzz_query.py)** — lexical matching.
- `search_first_match()` — exact-norm → key prefix → FULLTEXT → LIKE last resort, ranked with `fuzz.WRatio`.
- Thresholds: `AUTO_SCORE = 90`, `MIN_MARGIN = 5`, `TOP_K = 10`.
- Requires `*_NORM` / `*_KEY` generated columns and (optional) FULLTEXT index — see [RAPIDFUZZ.md](RAPIDFUZZ.md).

**[sql_cache.py](sql_cache.py)** — cache helpers.
- `search_sql_cache_by_question_hash()`, `search_sql_cache_by_question_text()`, `write_sql_cache_entry()` — all take the **formatted** API version (`XXX.YYY.ZZZ`).
- `_normalize_cache_row()` — picks `SQL_QUERY` over `SQL_PROCESSED` when needed to preserve a smaller LLM-defined `LIMIT` (see `used_raw_query_to_preserve_limit`).

**[cleanup.py](cleanup.py)** — version-scoped purge utilities (off by default; see `intcleanupenabled` at [main.py:70-71](main.py#L70-L71)).

**[auth.py](auth.py)** — `get_api_key()` Security dependency. Multi-key via `API_KEYS` (comma-separated); `secrets.compare_digest()` for constant-time comparison.

**[data_watcher.py](data_watcher.py)** — `register(filename, callback)`; daemon thread polls `./data/` every 5 s on mtime; logs hot reloads via `logs.log_hot_reload()`.

**[language_family.py](language_family.py)** — `guess_language_family()` from Unicode code points (Latin / Hangul / Japanese / Chinese / Cyrillic / Arabic / Hebrew / Devanagari / etc.).

**[logs.py](logs.py)** — `log_usage(endpoint, content, strapiversion)` and `log_hot_reload(filename)`. Filenames are `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`; never overwrite existing files.

**[data/](data/)** — hot-reloaded prompts and config:
- `text_to_sql.md` — main Text2SQL prompt (loaded by [text2sql.py](text2sql.py))
- `complex_question.md` — complex-question resolver prompt (loaded by [text2sql.py](text2sql.py))
- `entity_extraction.md` — entity extraction prompt (loaded by [entity.py](entity.py))
- `entity_resolution.json` — per-placeholder resolution strategy list (loaded by [entity.py](entity.py))
- `closed_vocabularies.json` — alias dictionaries (loaded by [closed_vocab.py](closed_vocab.py))

---

## Runtime dependencies

The app loads environment variables from `.env` via `python-dotenv`.

- MariaDB: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
- API auth: `API_KEYS` (comma-separated) or legacy `API_KEY`.
- LLMs: `OPENAI_API_KEY` for `gpt-*`, `o1*`, `o3*`, and embeddings; `ANTHROPIC_API_KEY` for `claude-*`; `GOOGLE_API_KEY` for `gemini-*`; `OPENROUTER_API_KEY` for OpenRouter-routed models.
- ChromaDB: `CHROMADB_HOST`, `CHROMADB_PORT`.
- Blue/Green and MCP: `API_PORT_BLUE`, `API_PORT_GREEN`, `MCP_API_KEY`, `MCP_INTERNAL_API_KEY`, `MCP_INTERNAL_BASE_URL`.

Important startup constraint: `OPENAI_API_KEY` is required at import/startup because `main.py` initializes the OpenAI embedding function for ChromaDB even if the request-time text model is Anthropic or Google.

---

## ChromaDB collections

`main.py` creates or opens 15 entity collections: `persons`, `movies`, `series`, `companies`, `networks`, `topics`, `locations`, `groups`, `characters`, `lists`, `collections`, `deaths`, `awards`, `nominations`, `movements`.

The `anonymizedqueries` collection is separate and is used for the optional embeddings-based anonymized-question cache. If schema, entity IDs, collection document IDs, or language-routed fields change, assume the relevant ChromaDB collection may need to be rebuilt or resynced; stale embeddings can resolve to IDs that no longer exist in the SQL tables.

---

## Hot-reloaded vs restart-required

**Hot-reloaded (no restart)** — picked up within ~5 s of mtime change:
- Anything under `data/` (the five files above).

**Restart required** — consider whether a user-requested `strapiversion` bump is also needed so the cache key flips and the Blue/Green parity moves:
- Any change to `*.py`.
- Any new placeholder (it must dispatch through `entity.py`).
- New `closed_vocab` canonical loader or query (touched in `closed_vocab.py`).

Do not bump `strapiversion` automatically. If the user explicitly asks for a version bump, update `strapiversion`; otherwise, mention when a prompt/config change may be shadowed by old cached SQL and let the user decide.

---

## Placeholder dispatch order

Inside `entity.resolve_entities()`, the dispatch order is fixed and matters:

1. **Regex-validated** ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`) — uses `startswith()`, so more specific prefixes must come first:
   - `Release_year`, `Birth_year`, `Death_year` — `\d{4}`, numeric (bare integer)
   - `IMDb_person_ID` (before `IMDb_ID`) — `nm\d+`, quoted string
   - `IMDb_ID` — `tt\d+`, quoted string
   - `Wikidata_property_ID` (before `Wikidata_ID`) — `P\d+`, quoted string
   - `Wikidata_ID` — `Q\d+`, quoted string
   - `TMDb_ID`, `Criterion_spine_ID` — `\d+`, numeric
   - **Malformed values are rejected** → placeholder left unresolved → question marked ambiguous.
2. **Closed-vocabulary branches** — handled by name-prefix `if/elif`:
   - `Movie_genre*` → `closed_vocab.resolve_movie_genre()` → integer `ID_GENRE` (no quotes in SQL); restricted to genres with `APPLIES_TO_MOVIE = 1` in `T_WC_TMDB_GENRE`.
   - `Serie_genre*` → `closed_vocab.resolve_serie_genre()` → integer `ID_GENRE` (no quotes in SQL); restricted to genres with `APPLIES_TO_SERIE = 1` in `T_WC_TMDB_GENRE`.
   - `Technical_format*` → `closed_vocab.resolve_technical()` → integer `ID_TECHNICAL` (no quotes in SQL).
   - `Status_name*` / `Serie_type*` / `Department_name*` → `closed_vocab.resolve(entity, raw)` → canonical string (single-quoted in SQL).
3. **Embeddings / RapidFuzz** — driven by `data/entity_resolution.json` `search_list` strategies; per-strategy language-family gating is supported.
4. **Raw fallback** — any unmatched placeholder gets the raw extracted value SQL-escaped and substituted directly. If anything is still left after the loop, `ambiguous_question_for_text2sql = 1` is set.

---

## Adding a new placeholder

Pick the right kind, then follow the canonical pattern:

| Kind | Where the resolver lives | What goes in `entity.py` | Schema edits |
|---|---|---|---|
| Regex (year, ID-style literal) | `_REGEX_PLACEHOLDER_RULES` tuple | nothing — dispatcher handles it | none |
| Closed-vocab string (Status-shape) | `closed_vocab._XXX_QUERY` + `init()` block | name-prefix branch in `resolve_entities()` calling `closed_vocab.resolve("XXX", raw)` | optional aliases entry in `data/closed_vocabularies.json` |
| Closed-vocab integer ID (Genre-shape) | `closed_vocab._XXX_CANONICALS_QUERY` + `init()` block + `resolve_xxx()` function (mirrors `resolve_genre`/`resolve_technical`) | name-prefix branch substituting the integer (no quotes) | aliases JSON; optional `_LANG` companion table |
| Embeddings / RapidFuzz (open-vocab name) | new entry in `data/entity_resolution.json` (`search_list` with `embeddings` and/or `rapidfuzz` strategies) | nothing — config-driven | new ChromaDB collection + initialization in [main.py:124-143](main.py#L124-L143) for embeddings |

Always also:
1. Add the placeholder definition + examples to `data/entity_extraction.md`.
2. Add a placeholder reference (and any column-picking rule) to `data/text_to_sql.md`.
3. Update [closed-vocab-entity-checklist.csv](closed-vocab-entity-checklist.csv) if it's a closed-vocab entity.
4. Bump `strapiversion` only when explicitly requested; otherwise warn that current-version cache rows may shadow the new behavior.

---

## Code conventions

- **Hungarian notation** for variables (legacy style):
  - `str` — strings (`strtablename`, `strapiversion`)
  - `lng` — integers (`lngpage`, `lngrowsperpage`)
  - `dbl` — floats (`dblavailableram`)
  - `arr` — lists / arrays
  - `int` — boolean-like flags (`intcleanupenabled`, `intentity`)
- **Function naming**: public pipeline entry points use `f_` (`f_text2sql`, `f_entity_extraction`, `f_resolve_complex_question`, `f_answer_single_value`, `f_hello_world`); private helpers use `_` (`_call_chat_llm`, `_normalize_llm_model`).
- **Docstrings**: Google-style on public functions.
- **Error handling**: broad try/except with console logging; surface failures via the `error` response field and the `messages` trace. Database execution errors are not returned directly to clients — they go through the complex-question retry path when enabled.
- **JSON serialization**: use `logs.decimal_serializer()` for `Decimal` and `datetime`.

---

## SQL handling rules

**Escaping** — SQL-style doubled single quotes, NOT backslash. `entity._sql_escape_literal()` centralizes this:
```python
"O'Brien".replace("'", "\\'")  # WRONG — breaks MariaDB
"O'Brien".replace("'", "''")   # CORRECT → 'O''Brien'
```

**Pagination** — three regexes detect and strip LLM-emitted `LIMIT`/`OFFSET` clauses (`LIMIT n OFFSET m`, `LIMIT m, n`, `LIMIT n`); a smaller LLM-defined limit is respected when smaller than `rows_per_page`. Code at [main.py:1010-1046](main.py#L1010-L1046).

**Ambiguous questions** — when the LLM cannot produce a valid query *or* entity resolution leaves unresolved placeholders, set `ambiguous_question_for_text2sql = True`, skip execution, and surface the LLM's explanation in `error`. The legacy `##AMBIGUOUS##` marker is gone — do not reintroduce it.

---

## Text-to-SQL ↔ entity endpoint coherence

[data/text_to_sql.md](data/text_to_sql.md) (drives LLM-generated SQL for `/search/text2sql`) and the 17 entity detail endpoints in [main.py](main.py) (hand-written SQL for `/movies/{id}`, `/persons/{id}`, `/seasons/{id_serie}/{season_number}`, etc., plus their MCP `get_*` proxies where they exist) are two independent SQL surfaces over the same data. They are kept in sync by hand, not enforced by code.

When working on either side, scan the other for divergence and **surface any discrepancy to the user** — do not silently patch one to match the other, and do not treat this as an automatic refactor target. Default expectation: `data/text_to_sql.md` is the spec; the endpoints should match unless the user says otherwise. Categories of drift to watch for:

- **Filter predicates** — e.g. the `CAST_CHARACTER NOT IN (...)` exclusion for non-documentary movie cast ([data/text_to_sql.md:850-851](data/text_to_sql.md#L850-L851)), `IS_DOCUMENTARY` / `IS_MOVIE` toggles, Criterion Collection criteria, technical / genre / aspect-ratio filters.
- **Sort order** — the "Default Sorting" section (around line 876+) governs both: `ORDER BY` inside endpoint SQL, and the directional rules (e.g. movies-for-a-person vs persons-for-a-movie) that drive what the text-to-SQL prompt emits.
- **Included related lists and their key order** — the order in which related-entity lists appear in entity detail responses should track the order of rules in the "Default Sorting" section.
- **Result columns** — the `Result Columns` section (around line 768+) specifies which columns each entity surface should expose.

When you spot a divergence, describe it (which side has which behavior, where in the spec/code), and let the user decide which side is authoritative for the fix.

### Entity endpoint localization (`ui_language`)

Every entity detail endpoint and its MCP `get_*` proxy take a `ui_language` parameter (query param for REST, tool arg for MCP), normalized by `normalize_ui_language()` to `en`/`fr` (default/fallback `en`). Responses are localized by `localize_response()`, which recursively collapses each `<COL>`/`<COL>_FR` pair into the single canonical `<COL>` (French value when present, English fallback) and drops the `_FR` keys — on both the primary entity and nested related rows. The real localizable columns are `MOVIE_TITLE`, `SERIE_TITLE`, `TOPIC_NAME`, `LIST_NAME`, `COLLECTION_NAME`, `MOVEMENT_NAME`, `AWARD_NAME`, `NOMINATION_NAME`, `GROUP_NAME`, `DEATH_NAME`, `ITEM_LABEL`, and technical `DESCRIPTION`; person `BIOGRAPHY` and company `DESCRIPTION` have no `_FR` variant. `SERIE_TITLE_FR` exists on `T_WC_T2S_SERIE` (and is collapsed into `SERIE_TITLE`): the base `/series/{id}` row picks it up via `SELECT *`, and every nested series SELECT (parent-series nav stubs in `/seasons` & `/episodes`, and the series lists in `/persons`, `/companies`, `/networks`, `/collections`, `/movements`, `/awards`, `/nominations`, `/locations`) explicitly selects `SERIE_TITLE_FR` alongside `SERIE_TITLE`. `_fetch_wikipedia_images` / `_fetch_wikipedia_content` filter by `ui_language` with English fallback. When adding a nested related-entity SELECT that exposes a localizable name/description column, also select its `_FR` variant so `localize_response()` can resolve it. Usage logs (`logs.log_usage`) capture the pre-localization row, so logged responses retain both language columns.

`apply_localized_main_image()` ([main.py](main.py)) is the image counterpart to `localize_response()`: image paths have no `_FR` column, so for a non-default `ui_language` it overrides the **top-level** entity's canonical main-picture path with the `IMAGE_PATH` of the main (lowest `DISPLAY_ORDER`) related image whose `LANG` matches the requested language, falling back to the canonical path when no localized image exists. It runs after `logs.log_usage` (so logs keep the canonical path) and before `localize_response`. Wired on the entities that carry a language-tagged image array: `/movies/{id}`, `/series/{id}`, and `/seasons/{...}` (`posters` → `POSTER_PATH`) and `/persons/{id}` (`portraits` → `PROFILE_PATH`).

`apply_localized_related_images(conn, grouped_rows, ui_language)` ([main.py](main.py)) extends the same idea to **nested related rows** (the "collections" embedded in each detail response — `cast`, `crew`, `movie_cast`, `movies`, `series`, `persons`, the parent-series/season nav stubs, the `seasons` array, …). Nested rows carry a main image path but not their own image array, so the localized path is fetched in one batched query per entity kind. `grouped_rows` maps a kind in `_RELATED_IMAGE_SOURCES` (`movie` → `T_WC_T2S_MOVIE_IMAGE`/`ID_MOVIE`/`poster`/`POSTER_PATH`; `serie` → `T_WC_T2S_SERIE_IMAGE`/`ID_SERIE`/`poster`/`POSTER_PATH`; `person` → `T_WC_T2S_PERSON_IMAGE`/`ID_PERSON`/`profile`/`PROFILE_PATH`; `season` → `T_WC_TMDB_SEASON_IMAGE`/`ID_SEASON`/`poster`/`POSTER_PATH`) to a list of row collections (each a list of dicts, or a single dict stub). For each id it keeps the lowest-`DISPLAY_ORDER` image in the requested `LANG`, overwriting the row's path field (canonical kept as fallback). It runs in the same slot as `apply_localized_main_image` (after `logs.log_usage`, before `localize_response`) and is a no-op for the default language. Wired on every detail endpoint that returns localizable person/movie/serie/season nested rows. When adding a nested array of movie/serie/person/season rows, add it to that endpoint's `apply_localized_related_images` call so its main picture is localized too. Episodes are excluded — `STILL_PATH` frames are not language-specific.

### Entity endpoint collection pagination (`collection` / `page` / `rows_per_page`)

Every entity detail endpoint (and its MCP `get_*` proxy) paginates its **related-entity lists** so large results stay bounded. Each endpoint declares a local `pcollections` registry mapping `collection_name -> (sql, params, image_kind)`; the shared driver `_run_collections()` ([main.py](main.py)) runs it. The registry is the single source of truth and is used for both modes:

- **Untargeted** (`collection is None`): every list is fetched at page 1 (using the requested `rows_per_page`); the response is assembled as before plus a top-level `pagination` block (`name -> {total, page, rows_per_page, returned}`). Non-paginated extras (scalar lists, image arrays, `videos`, Wikipedia arrays) are fetched only in this branch.
- **Targeted** (`?collection=<name>`): only that list is fetched at the requested `page`; `_targeted_collection_response()` returns a lean payload (identifier echo + that one list + its `pagination`), then runs the usual `apply_localized_related_images` / `localize_response`. An unknown name → HTTP 400.

Each registry SQL **must** select `COUNT(*) OVER() AS _TOTAL_COUNT` (one-query window total, stripped by `_paginate_collection`), carry a deterministic `ORDER BY` with a unique tiebreaker (usually the related entity `ID_*`), and omit its own `LIMIT`/semicolon (the helper appends `LIMIT %s OFFSET %s`). `cast`/`crew` (movies/series/seasons/episodes) and `movie_cast`/`movie_crew`/`series_cast`/`series_crew` (persons) are split into separate per-`CREDIT_TYPE` queries with the `CAST_CHARACTER_EXCLUSIONS` filter pushed into SQL (movies: only when non-documentary; persons `movie_cast`: per-row on the host movie's `IS_DOCUMENTARY`). The `image_kind` (a `_RELATED_IMAGE_SOURCES` key or `None`) drives related-image localization via `_localized_image_groups()`. Constants `COLLECTION_ROWS_PER_PAGE_DEFAULT` (50) / `COLLECTION_ROWS_PER_PAGE_MAX` (200) live near the helpers. **When adding a new nested related-entity list, add it to the endpoint's `pcollections` registry** (not as a one-off `cursor.execute`) so it is paginated and localized consistently. Note: `COUNT(*) OVER()` requires MariaDB ≥ 10.2.

---

## Entity-resolution config schema (`data/entity_resolution.json`)

Each entry has a `placeholder_prefix` and a `search_list`. Each search entry can define:
- `search_mode`: `"embeddings"` or `"rapidfuzz"`
- `apply_when_language_family_in` / `apply_when_language_family_not_in`: gate by script family
- `strtablename`, `strtableid`, `default_field`: SQL table / PK / display column
- `collection`: ChromaDB collection name (embeddings mode)
- `languages`: `{ "en": FIELD, "fr": FIELD, "*": FIELD }` for language-routed column selection on document IDs formatted as `{entity}_{id}_{lang}`
- `rapidfuzz_col_norm`, `rapidfuzz_col_key`, `rapidfuzz_col_popularity`: generated/norm columns for lexical matching
- `resolve_to_canonical`: when an AKA table returns a row, look up the canonical value in another table (e.g., `T_WC_TMDB_PERSON_ALSO_KNOWN_AS.ID_PERSON` → `T_WC_T2S_PERSON.PERSON_NAME`)

ChromaDB document ID format is always `{entity}_{id}_{lang}` (e.g., `movie_12345_fr`). Language drives the SQL field via the `languages` map.

---

## Messages array invariant

Every processing step appends `TextMessage(position=int, text=str)` with a monotonically increasing `position_counter`:
```python
messages.append(TextMessage(position=position_counter, text="..."))
position_counter += 1
```
When delegating to `entity.resolve_entities()` or `_retry_with_resolved_complex_question()`, the updated counter is threaded through the return dict. On complex-question retry, the messages from the outer and inner runs are renumbered and merged (see [main.py:879-891](main.py#L879-L891)).

---

## Cache API-version filtering

All cache reads and writes must pass `strapiversionformatted` (`XXX.YYY.ZZZ`), never the raw `strapiversion`. The `sql_cache` helpers already take the formatted version as a parameter — pass it through, do not recompute.

Cache lookups also filter by `UI_LANGUAGE` (with `OR UI_LANGUAGE IS NULL` for backward compatibility). Lookups that hit prefer `SQL_PROCESSED`; raw `SQL_QUERY` is used only when it preserves a smaller LLM-defined `LIMIT`.

---

## Version management workflow

When updating prompt templates, schema, or resolver behavior:
1. Edit the hot-reloaded file in `data/` directly — no versioned filename suffix; hot-reload picks the change up within ~5 s without a restart.
2. Bump `strapiversion` in [main.py:105](main.py#L105) only when the user explicitly asks for a version bump. This also flips Blue/Green port parity when the patch number changes.
3. Restart only if you also touched `*.py`.
4. If `intcleanupenabled = True`, startup cleanup will purge old cached queries for the previous version.
5. If you do not bump the version after a prompt/config change, tell the user that existing cache rows for the current formatted version may still shadow the new behavior.

Filenames registered at module import time are static:
- `text_to_sql.md`, `complex_question.md` (registered in [text2sql.py:36,40](text2sql.py#L36))
- `entity_extraction.md`, `entity_resolution.json` (registered in [entity.py:12-13](entity.py#L12-L13))
- `closed_vocabularies.json` (registered in [closed_vocab.py](closed_vocab.py))

Version format: input `"1.1.16"` → stored `"001.001.016"` via `format_api_version()` (in both [main.py:33](main.py#L33) and [cleanup.py:5](cleanup.py#L5)).

---

## Verification workflow

Pick verification based on blast radius:

- For small Python-only changes, run the narrowest relevant smoke test or command available in the repo.
- For prompt, placeholder, resolver, cache, or schema-facing changes, run representative `/search/text2sql` questions when credentials and services are available.
- For evaluation-sensitive changes, use @eval/README.md and prefer a focused evaluator subset before a full run.
- For RapidFuzz behavior, check @RAPIDFUZZ.md and the relevant `doc/sql/*-rapidfuzz.sql` generated-column/index requirements.
- If you cannot run verification because MariaDB, ChromaDB, API keys, or model quota are unavailable, say exactly what was not run and why.

Do not silently populate caches during ad hoc testing when the goal is behavior inspection; use request options such as `store_to_cache=false` where appropriate.

---

## Common gotchas (do NOT step on these)

### Gotcha #1 — SQL Quote Escaping
Use `''`, never `\'`. Centralize via `entity._sql_escape_literal()`. Backslash escaping breaks MariaDB.

### Gotcha #2 — Cache API Version Filtering
Always pass `strapiversionformatted` (`XXX.YYY.ZZZ`), never raw `strapiversion`, to `sql_cache` helpers.

### Gotcha #3 — ChromaDB Document IDs
Format `{entity}_{id}_{lang}` (e.g., `movie_12345_fr`). Language drives the SQL field via the `languages` map in `entity_resolution.json`:
```
"languages": { "en": "MOVIE_TITLE", "fr": "MOVIE_TITLE_FR", "*": "ORIGINAL_TITLE" }
```

### Gotcha #4 — Entity Variable Matching in Embeddings Cache
A candidate document is only accepted when **all** extracted entity variables appear in it ([main.py:671](main.py#L671)):
```python
if all(var in doc_entity_vars for var in entity_variables):
```

### Gotcha #5 — Messages Position Counter
Always increment after appending. When delegating to `entity.resolve_entities()` or `_retry_with_resolved_complex_question()`, the updated counter is threaded through the return dict.

### Gotcha #6 — Database Connection Lifecycle
Open once per request, pass the connection around, close in a `finally`. Do NOT call `get_db_connection()` inside loops.

### Gotcha #7 — Custom Embedding Function Interface
`OpenAIEmbeddingFunction` ([main.py:80](main.py#L80)) must implement both `__call__()` (batch) and `embed_query()` (single query) — ChromaDB needs both.

### Gotcha #8 — Complex Question Retry Recursion Guard
The pipeline can retry via the stronger model, but only when `complex_question_already_resolved = False`. The recursive call sets it to `True` to prevent runaway retries.

### Gotcha #9 — Closed-Vocabulary Resolution
`Movie_genre`, `Serie_genre`, `Technical_format`, `Status_name`, `Serie_type`, and `Department_name` are resolved via [closed_vocab.py](closed_vocab.py): canonicals from the database at startup, aliases from [data/closed_vocabularies.json](data/closed_vocabularies.json) (hot-reloaded). Typo tolerance is uniform via RapidFuzz with `score_cutoff=85` and `margin=5`. Genre placeholders and `Technical_format` substitute integers (no quotes); `Status_name`, `Serie_type`, and `Department_name` substitute single-quoted canonical strings. `Movie_genre` and `Serie_genre` draw from the same `T_WC_TMDB_GENRE` table but each loader query filters by the `APPLIES_TO_MOVIE` / `APPLIES_TO_SERIE` flag, so a question filtering movies cannot resolve to a TV-only genre (e.g. `Reality`, `Sci-Fi & Fantasy`) and vice versa.

**Resolver order matters**: in `_resolve_closed_vocab`, canonical exact match runs **before** alias match. If a user-typed value happens to be a literal canonical, the canonical wins and the alias never fires. To remap noisy DB variants to a single dominant form, exclude them from canonicals via the loader query.

`Department_name` is **crew-only** — its canonical loader explicitly excludes `'Actors'` and `'Acting'` from all three UNIONed source columns (`CREW_DEPARTMENT` × movie + serie, plus `KNOWN_FOR_DEPARTMENT` from `T_WC_T2S_PERSON`). The text-to-SQL prompt picks the column based on question intent (person-search → `KNOWN_FOR_DEPARTMENT`, crew-of-content → `CREW_DEPARTMENT`); whenever `CREW_DEPARTMENT` is filtered via `{{Department_nameN}}`, the prompt also enforces `CREDIT_TYPE = 'crew'` on the same join. Cast / actor queries never produce a `Department_name` placeholder; the LLM emits `CREDIT_TYPE = 'cast'` (film context) or `KNOWN_FOR_DEPARTMENT = 'Acting'` (person-search) inline.

Aspect ratios are **part of `Technical_format`** (rows in `T_WC_T2S_TECHNICAL` with `TECHNICAL_TYPE='aspect_ratio'` and dot-decimal `DESCRIPTION` values like `'1.85'`, `'2.35'`). Surface variants (`Academy`, `widescreen`, `flat`, `4:3`, `16:9`, `2.35:1`, `2,35` with French comma) live as aliases under `Technical_format` in [data/closed_vocabularies.json](data/closed_vocabularies.json) and resolve to the matching aspect-ratio `ID_TECHNICAL`. Filtering and detail both go through the same `{{Technical_formatN}}` pattern as every other technical (junction `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL` for filter; direct `T_WC_T2S_TECHNICAL.ID_TECHNICAL` for detail), so a movie that ships in several aspect ratios is correctly matched on any of them.

Only the two genre placeholders (`Movie_genre`, `Serie_genre`) have a `_LANG` companion table today (`T_WC_TMDB_GENRE_LANG`, joined against the side-applicability flag at load time); for the others, multilingual aliases live in JSON only.

### Gotcha #10 — Regex Placeholders Reject Malformed Values
The 9 regex-validated placeholders validate against a fixed pattern in `_REGEX_PLACEHOLDER_RULES`. Failed matches are **rejected** — the placeholder is left in place and the trailing unresolved-placeholder check marks the question ambiguous. Order in the rule list matters because dispatch uses `startswith()`: `IMDb_person_ID` precedes `IMDb_ID`, `Wikidata_property_ID` precedes `Wikidata_ID`. Numeric rules substitute as bare integers (and strip surrounding quotes via two regex passes); string rules substitute as quoted SQL string literals — choose `is_numeric` based on the target column's SQL type.

### Gotcha #11 — MCP Mount Path
`app.mount("", mcp_app)` (empty string), not `"/mcp"`. Nginx strips/preserves `/mcp` upstream, and FastMCP's own routes live under `/mcp/…`. Mounting under `/mcp` produces `/mcp/mcp` paths.

---

## Database tables you'll touch most

Full prompt-visible schema rules live in [data/text_to_sql.md](data/text_to_sql.md), full DDL lives in [doc/sql/](doc/sql/), and MCP clients also see the `context://database-scope` resource. Quick map:

- `T_WC_T2S_CACHE` — cache storage. Keys: `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`, `JUSTIFICATION`, `ANSWER`, `RESULT_ENTITY`, `API_VERSION` (`XXX.YYY.ZZZ`), `UI_LANGUAGE`, `IS_ANONYMIZED`, `DELETED`, timing columns. `RESULT_ENTITY` is written/read by [sql_cache.py](sql_cache.py) with graceful degradation: if the column is absent (pre-migration), reads/writes fall back to the legacy column set and treat it as empty rather than failing.
- Primary entities: `T_WC_T2S_MOVIE`, `T_WC_T2S_SERIE`, `T_WC_T2S_PERSON`.
- Reference (closed-vocab): `T_WC_TMDB_GENRE` + `T_WC_TMDB_GENRE_LANG` (genres); `T_WC_T2S_TECHNICAL` (technical formats).
- Person AKAs: `T_WC_TMDB_PERSON_ALSO_KNOWN_AS` (used by RapidFuzz for non-Latin person names; resolves canonical via `resolve_to_canonical`).
- Locations: `T_WC_T2S_ITEM` (Wikidata) + `T_WC_WIKIDATA_ITEM_PROPERTY` (joined via `ID_PROPERTY IN ('P840', 'P915')` — narrative / filming).
- Join tables follow `T_WC_T2S_{PARENT}_{CHILD}` (e.g., `T_WC_T2S_PERSON_MOVIE`, `T_WC_T2S_MOVIE_GENRE`, `T_WC_T2S_SERIE_NETWORK`, `T_WC_T2S_MOVIE_AWARD`).

---

## Database Schema Sources

Full DDL lives under [doc/sql/](doc/sql/); do not duplicate table definitions here. Treat these files as reference-only unless the user explicitly asks for schema-doc edits.

- [doc/sql/T2S\_Evaluation-tables.sql](doc/sql/T2S-tables.sql) — tables used by the evaluation process.
- [doc/sql/T2S-tables.sql](doc/sql/T2S-tables.sql) — canonical Text2SQL read-model tables used by prompts, API detail endpoints, cache, and evaluation tables.
- [doc/sql/TMDb-tables.sql](doc/sql/TMDb-tables.sql) — upstream/source TMDb tables and reference tables.
- [doc/sql/Wikidata-tables.sql](doc/sql/Wikidata-tables.sql) — Wikidata staging and canonical tables.
- [doc/sql/Wikipedia-tables.sql](doc/sql/Wikipedia-tables.sql) — Wikipedia section tables.
- [doc/sql/T_WC_TMDB_GENRE.sql](doc/sql/T_WC_TMDB_GENRE.sql) — focused genre reference DDL.
- [doc/sql/T_WC_T2S_TECHNICAL.sql](doc/sql/T_WC_T2S_TECHNICAL.sql) — focused technical-format reference DDL.
- [doc/sql/T2S_PERSON-rapidfuzz.sql](doc/sql/T2S_PERSON-rapidfuzz.sql) and [doc/sql/T_WC_TMDB_PERSON_ALSO_KNOWN_AS-rapidfuzz.sql](doc/sql/T_WC_TMDB_PERSON_ALSO_KNOWN_AS-rapidfuzz.sql) — generated columns, indexes, and FULLTEXT setup required by RapidFuzz.

When changing SQL-facing behavior:

1. Check [data/text_to_sql.md](data/text_to_sql.md) for the prompt-visible schema and query rules.
2. Check [doc/sql/](doc/sql/) for real DDL.
3. Check code users in [main.py](main.py), [entity.py](entity.py), [closed_vocab.py](closed_vocab.py), [sql_cache.py](sql_cache.py), and [rapidfuzz_query.py](rapidfuzz_query.py).
4. If schema or prompt-visible behavior changes, update [data/text_to_sql.md](data/text_to_sql.md) and relevant docs. Edit [doc/sql/](doc/sql/) only when explicitly requested.
5. Bump `strapiversion` only when explicitly requested.

---

## SQL Object Naming Conventions

- SQL table and column names are uppercase snake case, except legacy imported TMDb genre columns such as `id` and `name`.
- Persistent tables use `T_WC_*`.
- Text2SQL read-model tables use `T_WC_T2S_*`.
- TMDb source/reference tables use `T_WC_TMDB_*`.
- Wikidata tables use `T_WC_WIKIDATA_*`; staging tables use `STG_T_WC_WIKIDATA_*`.
- Wikipedia tables use `T_WC_WIKIPEDIA_*`.
- Join tables usually follow `T_WC_T2S_{PARENT}_{CHILD}`, for example `T_WC_T2S_MOVIE_GENRE`, `T_WC_T2S_PERSON_MOVIE`.
- Primary keys are usually `ID_{ENTITY}` for entity tables, `ID_ROW` for generic/join rows, or a table-specific surrogate such as `ID_T2S_PERSON_MOVIE`.
- Foreign keys reuse the referenced primary-key name, for example `ID_MOVIE`, `ID_PERSON`, `ID_GENRE`.
- Date columns use `DAT_*`; datetime/timestamp columns use `TIM_*`.
- Boolean-like flags use `IS_*` or legacy integer flags such as `DELETED`.
- Ordering uses `DISPLAY_ORDER`.
- Aggregate counters use `*_COUNT`.
- Media paths use `*_PATH`.
- Language-specific labels/titles often use suffixes such as `_FR`; generic language rows use `LANG`.
- RapidFuzz/generated search columns use `*_NORM` and `*_KEY`; popularity tie-breakers commonly use `POPULARITY`.
- Index names are mixed legacy style. Preserve existing style: simple `KEY COLUMN_NAME`, `IDX_*` for indexes, `UK_*` for unique keys, `FK_*` for foreign keys, and `ft_*` for FULLTEXT indexes.

---

## SQL execution safety

The text-to-SQL prompt should generate read-only SELECT queries. Do not add write queries to prompt examples or generated-query paths. Cache writes are centralized in [sql_cache.py](sql_cache.py), cleanup deletes are centralized in [cleanup.py](cleanup.py), and schema/reference SQL under [doc/sql/](doc/sql/) is documentation unless the user explicitly asks otherwise.

Prefer parameterized SQL for application-owned queries. Placeholder de-anonymization is a special pipeline step; when inlining placeholder values, use `entity._sql_escape_literal()` and SQL doubled single quotes.

---

## Encoding

Keep Markdown, prompt files, JSON config, and logs UTF-8. These files contain non-ASCII names and multilingual examples. Avoid editor or terminal operations that rewrite them with mojibake.

---

## Build & deployment (Docker)

The API/MCP server is built and run as a Docker container via the repo's `Dockerfile` (base image `python:3.12-slim-bookworm`, `PYTHONUNBUFFERED=1`). The build compiles SQLite 3.40.1 from source (set on `LD_LIBRARY_PATH`) for ChromaDB compatibility, installs `requirements.txt`, copies `*.py` and `./data/`, and runs `CMD ["python", "./main.py"]`. The `Dockerfile` does not declare an `EXPOSE` or `VOLUME`; the runtime config (the `.env` variables in "Runtime dependencies", including the Blue/Green `API_PORT_*` ports) is supplied at `docker run` time. Note `data/` is hot-reloaded from inside the image, so prompt/config edits need a rebuilt (or volume-mounted) `data/` to take effect in a running container.

---

**Last Updated**: 2026-06-03
**Current Version**: 1.1.16 (see `strapiversion` in [main.py:105](main.py#L105))

## Backlog (Nestor second-brain)

The prioritized, agent-ready implementation backlog for this repo lives in the **Nestor**
knowledge repo (a separate repo, not cloned alongside this one):

- This repo: `C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\fastapi-text2sql.md`
- Cross-repo dashboard: `C:\Users\vaugo\Nestor\projets\t2s-backlog\index.md`

Consult it before implementing: tasks are `FASTAPI-TEXT2SQL-NNN` with status (done / in-progress /
todo), priority, and quick-wins. NOTE: these are local paths on Philippe's PC and do not
resolve on the VPS or on cloud agents (claude.ai/code).
