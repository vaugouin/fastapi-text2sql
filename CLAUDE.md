# CLAUDE.md - AI Assistant Guide for FastAPI Text2SQL

## Project Overview

This is a FastAPI-based REST API that converts natural language questions into SQL queries using LLM provider SDKs (OpenAI, Anthropic, Google). The system specializes in querying a large-scale entertainment database (~620k movies, ~88k TV series, ~890k persons). It also exposes an MCP (Model Context Protocol) server so Claude clients (web, Desktop, mobile, Code CLI) can use the API as a remote tool.

**Primary Technology Stack:**
- **Framework**: FastAPI (Python 3.8+)
- **LLM**: OpenAI GPT-4o (default), Anthropic Claude, Google Gemini — via native provider SDKs
- **Vector DB**: ChromaDB (for embeddings and similarity search)
- **Lexical matching**: RapidFuzz (for person-name fuzzy search with FULLTEXT / prefix index fallback)
- **SQL DB**: MariaDB/MySQL
- **MCP**: FastMCP 2.x (remote tool server for Claude clients, mounted on the same FastAPI app)
- **Deployment**: Docker with Blue/Green deployment strategy

**Current Version**: 1.1.15 (see `strapiversion` in [main.py:54](main.py#L54))

## Architecture & Design Patterns

### Core Architecture Components

1. **Multi-Tier Caching System** (Performance Optimization)
   - **Tier 1**: Exact question cache (SQL database `T_WC_T2S_CACHE`, `IS_ANONYMIZED = 0`)
   - **Tier 2**: Anonymized question cache (SQL database `T_WC_T2S_CACHE`, `IS_ANONYMIZED = 1`)
   - **Tier 3**: Vector embeddings cache (ChromaDB `anonymizedqueries` collection) — **disabled by default** via `USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE = False` ([main.py:153](main.py#L153))
   - All SQL cache reads/writes go through [sql_cache.py](sql_cache.py) (`search_sql_cache_by_question_hash`, `search_sql_cache_by_question_text`, `write_sql_cache_entry`)
   - Cache lookups filter by formatted API version (`XXX.YYY.ZZZ`), `UI_LANGUAGE`, and `DELETED IS NULL OR DELETED = 0`
   - Cache entries store the `ANSWER` field and `UI_LANGUAGE`; lookups include `UI_LANGUAGE` in the WHERE clause (with `OR UI_LANGUAGE IS NULL` for backward compatibility)
   - On hit, `SQL_PROCESSED` is preferred; `SQL_QUERY` is used instead when it preserves a smaller LLM-defined `LIMIT` (see `used_raw_query_to_preserve_limit` in [sql_cache.py:52](sql_cache.py#L52))

2. **Entity Extraction Pipeline** ([entity.py:52](entity.py#L52))
   - Entities are extracted from natural language via `entity.f_entity_extraction()` using the configured LLM (default `gpt-4o`)
   - Questions are anonymized with typed placeholders (e.g., `{{Person_name1}}`, `{{Movie_title1}}`, `{{Release_year1}}`, `{{Genre_name1}}`)
   - Extracted entity types produce placeholders matching prefixes in [data/entity_resolution.json](data/entity_resolution.json): `Person_name`, `Movie_title`, `Serie_title`, `Company_name`, `Network_name`, `Topic_name`, `List_name`, `Award_name`, `Nomination_name`, `Collection_name`, `Movement_name`, `Location_name`, `Group_name`, `Death_name`
   - Special placeholder prefixes handled directly in code (not in JSON config):
     - **Closed-vocabulary** ([closed_vocab.py](closed_vocab.py), loaded at startup via `closed_vocab.init(connection)` in [main.py:261](main.py#L261); aliases hot-reload from [data/closed_vocabularies.json](data/closed_vocabularies.json)):
       - `Genre_name*` — closed-vocabulary lookup mapping name → integer `ID_GENRE`. Canonicals from `T_WC_TMDB_GENRE`; multilingual aliases from `T_WC_TMDB_GENRE_LANG` + JSON aliases. RapidFuzz typo tolerance.
       - `Technical_format*` — closed-vocabulary lookup mapping name → integer `ID_TECHNICAL`. Canonicals from `T_WC_T2S_TECHNICAL` (56 active rows: sound systems, color/film/sound technologies, film formats); aliases from JSON only (no `_LANG` companion table yet).
       - `Status_name*` — closed-vocabulary string substitution (e.g., `Released`, `Canceled`). Canonicals from `DISTINCT STATUS` over `T_WC_T2S_MOVIE` ∪ `T_WC_T2S_SERIE`.
       - `Serie_type*` — closed-vocabulary string substitution (e.g., `Documentary`, `Miniseries`). Canonicals from `DISTINCT SERIE_TYPE` over `T_WC_T2S_SERIE`.
     - **Regex-validated** ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`) — each rule defines a placeholder prefix, validation regex, and numeric-vs-string flag. Numeric substitutes a bare number (INT columns); string substitutes a quoted SQL literal (VARCHAR columns). Malformed values are rejected and the placeholder is left unresolved (marks question ambiguous):
       - Numeric (`\d{4}`): `Release_year*`, `Birth_year*`, `Death_year*`
       - Numeric (`\d+`): `TMDb_ID*`, `Criterion_spine_ID*`
       - String (`tt\d+` / `nm\d+`): `IMDb_ID*`, `IMDb_person_ID*`
       - String (`Q\d+` / `P\d+`): `Wikidata_ID*`, `Wikidata_property_ID*`

3. **Entity Resolution** ([entity.py:197](entity.py#L197) `resolve_entities()`)
   - Driven by [data/entity_resolution.json](data/entity_resolution.json) (hot-reloaded via `data_watcher`)
   - Each placeholder prefix defines a `search_list` of strategies tried in order
   - Two `search_mode` strategies:
     - `"embeddings"` — ChromaDB vector similarity lookup (collection + language-aware field mapping: `en` → `MOVIE_TITLE`, `fr` → `MOVIE_TITLE_FR`, `*` → `ORIGINAL_TITLE`)
     - `"rapidfuzz"` — lexical match via [rapidfuzz_query.py](rapidfuzz_query.py) with normalized/key columns and optional FULLTEXT index
   - Strategies may be gated by language family (`apply_when_language_family_in`, `apply_when_language_family_not_in`) — detected by [language_family.py](language_family.py) (Latin vs Hangul / Japanese / Chinese / Cyrillic / Arabic / Hebrew / Devanagari / etc.)
   - Persons use RapidFuzz with two branches:
     - **Latin scripts** → search `T_WC_T2S_PERSON` directly
     - **Non-Latin scripts** → search `T_WC_TMDB_PERSON_ALSO_KNOWN_AS` (AKAs) then resolve to canonical `PERSON_NAME` via the `resolve_to_canonical` block
   - On fallback, the raw value is SQL-escaped and substituted directly (`raw fallback`)
   - Any placeholder still unresolved after the loop marks the question as `ambiguous_question_for_text2sql = 1`

4. **Vector Search Integration**
   - ChromaDB collections initialized in [main.py:124-143](main.py#L124-L143):
     `persons`, `movies`, `series`, `companies`, `networks`, `topics`, `locations`, `groups`, `characters`, `lists`, `collections`, `deaths`, `awards`, `nominations`, plus `anonymizedqueries` for the (disabled) question embeddings cache
   - Similarity threshold: `0.15` (configurable at [main.py:169](main.py#L169))
   - Embedding model: OpenAI `text-embedding-3-large` via custom `OpenAIEmbeddingFunction` implementing both `__call__()` and `embed_query()`

5. **Multi-LLM Dispatch** ([text2sql.py:90](text2sql.py#L90) `_call_chat_llm`)
   - Single entry point routes on model prefix:
     - `gpt-*`, `o1*`, `o3*` → OpenAI (native `openai` SDK; o1/o3 use Responses API with fallback to chat.completions)
     - `claude-*` → Anthropic (native `anthropic` SDK)
     - `gemini-*` → Google (`google-generativeai`, with NOT_FOUND fallback chain)
   - Per-request override via `llm_model_entity_extraction`, `llm_model_text2sql`, `llm_model_complex` (default `"default"` → `gpt-4o`)

6. **Complex-Question Processing & Retry** ([main.py:794](main.py#L794))
   - When `complex_question_processing=true`, three one-time retry paths run the pipeline again with a stronger model (`llm_model_complex`):
     - **Text2SQL failure** — LLM returned no `sql_query` / an error
     - **SQL execution error** — MariaDB raised an exception during `cursor.execute()`
     - **Zero-row result on page 1** — valid SQL, empty result set
   - The stronger model is asked (via [data/complex_question.md](data/complex_question.md)) to rewrite the question into a simpler form (`f_resolve_complex_question_retry_payload`); messages from both runs are merged
   - **Single-cell zero-count answer** ([main.py:1160](main.py#L1160)) — if SQL returns exactly one row / one column with value `0`, the stronger model is asked for a direct scalar answer via `t2s.f_answer_single_value()`. The answer is embedded in a synthetic `SELECT {value} AS '{question}' FROM DUAL`, executed, and cached.

7. **Hot-Reload for Data Files** ([data_watcher.py](data_watcher.py))
   - Modules call `data_watcher.register(filename, callback)`; a daemon thread polls `./data/` every 5 seconds and re-fires the callback on mtime changes
   - Registered files:
     - `text_to_sql.md` (main Text2SQL prompt, [text2sql.py:63](text2sql.py#L63))
     - `complex_question.md` (complex-question resolver prompt, [text2sql.py:64](text2sql.py#L64))
     - `entity_extraction.md` (entity extraction prompt, [entity.py:48](entity.py#L48))
     - `entity_resolution.json` (entity resolution strategy config, [entity.py:49](entity.py#L49))
   - Hot reloads are logged via `logs.log_hot_reload()` — no restart needed to pick up prompt changes

8. **Blue/Green Deployment**
   - Version-based port selection: even patch versions → `API_PORT_BLUE` (default 8000), odd → `API_PORT_GREEN` (default 8001)
   - Controlled by `strapiversion` at [main.py:54](main.py#L54)
   - Restart scripts: `restart-blue.sh` and `restart-green.sh`

9. **Automatic Cache Cleanup — disabled by default**
   - Controlled by `intcleanupenabled` flag at [main.py:70-71](main.py#L70-L71) (currently `False`)
   - When enabled, `cleanup.cleanup_sql_cache()` runs at startup; `cleanup.cleanup_anonymized_queries_collection()` runs only when the embeddings cache is also enabled

10. **MCP Server** — see dedicated section below

### Request Processing Pipeline (`/search/text2sql`)

1. **Normalize input question** (strip whitespace, collapse double spaces, unescape `&#039;` and curly apostrophes)
2. **Exact cache lookup** — by `question_hashed` then by `question` text (SQL, via `sql_cache.py`); filtered by `ui_language`
3. **Entity extraction & anonymization** (configured LLM) → placeholders + anonymized question
4. **Anonymized cache lookup** (SQL)
5. **Embeddings cache lookup** (ChromaDB, disabled by default) — filters results so *all* required entity variables appear in the candidate document and distance < threshold
6. **Text-to-SQL generation** (configured LLM) — only if no cache hit
7. **Entity resolution** — embeddings and/or RapidFuzz per [entity_resolution.json](data/entity_resolution.json) strategy; replaces placeholders with resolved values (SQL-escaped) in SQL, justification, and answer
8. **Pagination** — strip any LLM `LIMIT`/`OFFSET`, append `LIMIT {rows_per_page} OFFSET {(page-1)*rows_per_page}`, respect a smaller LLM-defined limit when present
9. **SQL execution** (MariaDB) — `html.unescape()` applied to string values
10. **One-time retry paths** for complex questions (Text2SQL error / SQL execution error / zero rows / single-cell 0) — see Complex-Question section
11. **Cache population** — writes both exact and anonymized entries (including `answer` and `ui_language`); embeddings cache write gated by `USE_ANONYMIZEDQUERIES_EMBEDDINGS_CACHE`; embeddings metadata includes `answer`
12. **Response** — full pipeline trace in `messages`, entity extraction JSON, anonymized SQL, latency breakdown

## Key Files and Their Roles

### Core Application Files

**[main.py](main.py)** (~2460 lines)
- FastAPI application setup, ChromaDB init, DB connection pooling (`get_db_connection()`)
- Version utilities: `format_api_version()` ([main.py:33](main.py#L33)), `compare_versions()` ([main.py:38](main.py#L38))
- `Text2SQLRequest` / `Text2SQLResponse` Pydantic models ([main.py:214-269](main.py#L214-L269))
- `POST /search/text2sql` — main pipeline endpoint
- 14 entity detail endpoints (`/movies/{id}`, `/series/{id}`, `/persons/{id}`, `/companies/{id}`, `/networks/{id}`, `/collections/{id}`, `/topics/{id}`, `/lists/{id}`, `/movements/{id}`, `/groups/{id}`, `/deaths/{id}`, `/awards/{id}`, `/nominations/{id}`, `/locations/{wikidata_id}`)
- FastMCP instance, 15 MCP tools (`sql_search` + 14 entity tools), 1 resource (`context://database-scope`), bearer-token middleware, and `app.mount("", mcp_app)` at root
- Blue/Green port selection in `__main__`

**[text2sql.py](text2sql.py)**
- `_call_chat_llm()` — unified multi-provider LLM dispatcher (OpenAI / Anthropic / Google)
- `f_text2sql(user_question, strtext2sqlmodel, ui_language="en")` — core text-to-SQL conversion; replaces `{ui_language}` in the prompt template so the LLM generates the `answer` field in the requested language
- `f_resolve_complex_question()` and `f_resolve_complex_question_retry_payload()` — complex-question simplification via stronger model
- `f_build_retry_question_from_reasoning()` — deterministically composes a retry question from structured reasoning output (items with type/value/year)
- `f_answer_single_value()` — direct-answer path for zero-count single-cell results
- Uses `data_watcher` to hot-reload `text_to_sql.md` and `complex_question.md`

**[entity.py](entity.py)**
- `f_entity_extraction()` — LLM-based entity extraction + anonymization
- `resolve_entities()` — main resolver combining embeddings + RapidFuzz strategies + closed-vocabulary lookups (`Genre_name*`, `Technical_format*`, `Status_name*`, `Serie_type*` via [closed_vocab.py](closed_vocab.py)) + regex-validated placeholders (`Release_year*`, `Birth_year*`, `Death_year*`, `IMDb_ID*`, `IMDb_person_ID*`, `Wikidata_ID*`, `Wikidata_property_ID*`, `TMDb_ID*`, `Criterion_spine_ID*` via `_REGEX_PLACEHOLDER_RULES`); also accepts and de-anonymizes the `answer` field alongside `justification`
- `_match_regex_placeholder_rule()` — dispatch helper returning the regex rule (prefix, pattern, is_numeric) that matches a placeholder key
- Loads and validates `entity_resolution.json` via `data_watcher`

**[rapidfuzz_query.py](rapidfuzz_query.py)**
- `search_first_match()` — primary entry, tries exact normalized match → prefix lookup on `*_KEY` → FULLTEXT fallback on `*_NORM` → LIKE last resort; ranks with `fuzz.WRatio`
- Thresholds: `AUTO_SCORE = 90`, `MIN_MARGIN = 5`, `TOP_K = 10`
- Requires generated columns `PERSON_NAME_NORM` / `PERSON_NAME_KEY` (see `T2S_PERSON-rapidfuzz.sql`) and optional FULLTEXT index

**[sql_cache.py](sql_cache.py)**
- `search_sql_cache_by_question_hash(connection, question_hash, api_version, ui_language="en")` / `search_sql_cache_by_question_text(connection, question_text, api_version, ui_language="en")` / `write_sql_cache_entry(…, answer="", ui_language="en")`
- Cache lookups filter by `UI_LANGUAGE` (`OR UI_LANGUAGE IS NULL` for backward compatibility); writes store `ANSWER` and `UI_LANGUAGE`
- `_normalize_cache_row()` — returns uniform payload including `answer`; detects when raw `SQL_QUERY` should override `SQL_PROCESSED` to preserve a smaller LLM-defined `LIMIT`

**[cleanup.py](cleanup.py)**
- `format_api_version()`
- `cleanup_sql_cache(connection, strapiversion)` — `DELETE FROM T_WC_T2S_CACHE WHERE API_VERSION = ?`
- `cleanup_anonymized_queries_collection(collection, strapiversion)` — batched ChromaDB purge (1000 at a time) + targeted delete of a specific problematic doc ID

**[auth.py](auth.py)**
- `get_api_key()` FastAPI Security dependency
- Supports multiple keys via `API_KEYS` env var (comma-separated); legacy `API_KEY` fallback
- Uses `secrets.compare_digest()` for constant-time comparison

**[data_watcher.py](data_watcher.py)**
- `register(filename, callback)` — synchronous initial load + daemon-thread mtime polling (5 s interval)
- Logs every hot reload via `logs.log_hot_reload()`

**[language_family.py](language_family.py)**
- `guess_language_family()` — detects script family from Unicode code points (Latin / Hangul / Japanese / Chinese / Cyrillic / Arabic / Hebrew / Devanagari / Greek / Armenian / Georgian / Bengali / Tamil / Telugu / Kannada / Malayalam / Sinhala / Thai / Khmer / Ethiopic)

**[logs.py](logs.py)**
- `log_usage(endpoint, content, strapiversion)` — writes JSON logs to `logs/` folder
- Filename format: `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`
- `log_hot_reload(filename)` — dedicated entry used by `data_watcher`

### Configuration & Data Files

**[data/](data/)** directory (hot-reloaded)
- `text_to_sql.md` — main Text2SQL prompt with full MariaDB schema
- `complex_question.md` — complex-question resolver prompt (structured JSON reasoning)
- `entity_extraction.md` — entity extraction prompt
- `entity_resolution.json` — per-placeholder resolution strategy list (embeddings + rapidfuzz + language gating + canonical resolution)

**[MCP.md](MCP.md)** — full MCP integration guide (tool code, resource reference, client setup, bearer token, end-to-end query flow)

**[RAPIDFUZZ.md](RAPIDFUZZ.md)** — RapidFuzz setup and SQL schema requirements

**[.env.example](.env.example)** — environment variable template

**[requirements.txt](requirements.txt)**
- Core: fastapi, uvicorn, openai, chromadb, pymysql, pandas, numpy, rapidfuzz, python-dotenv, psutil
- LLM: anthropic, google-generativeai
- MCP: fastmcp, httpx

**Dockerfile** — Python 3.12-slim-bookworm with a custom SQLite 3.40.1 build (required for modern ChromaDB)

### Deployment Scripts
**restart-blue.sh / restart-green.sh** — Docker container lifecycle management for Blue/Green deployments.

## API Endpoints

**GET /** — Health check; returns `{"message": "hello world! The universal answer is 42"}`. Requires `X-API-Key`.

**POST /search/text2sql** — Main text-to-SQL endpoint.
- Request (`Text2SQLRequest`): `question` or `question_hashed`, `page` (default 1), `rows_per_page` (default 50), `retrieve_from_cache`, `store_to_cache`, `llm_model_entity_extraction`, `llm_model_text2sql`, `llm_model_complex` (each `"default"` → `gpt-4o`), `complex_question_processing` (bool, default `False`), `complex_question_already_resolved` (internal flag, set automatically on retry), `ui_language` (str, default `"en"` — language for the user-oriented `answer` field; also part of the cache key)
- Response (`Text2SQLResponse`): full pipeline trace — see Response Fields below

**Entity Detail Endpoints (14)** — each returns the row plus embedded relations and logs via `logs.log_usage()`:
- `GET /movies/{id}` — movie + cast, crew, genres, companies, production_countries, spoken_languages, topics, collections, movements, awards, nominations
- `GET /series/{id}` — series + cast, crew, genres, companies, networks, production_countries, spoken_languages, topics, collections, movements, awards, nominations
- `GET /persons/{id}` — person + movie_cast, movie_crew, series_cast, series_crew, groups, deaths, awards, nominations
- `GET /companies/{id}`, `GET /networks/{id}` — entity + associated movies/series ordered by `IMDB_RATING_WEIGHTED DESC`
- `GET /collections/{id}`, `GET /topics/{id}`, `GET /lists/{id}`, `GET /movements/{id}` — entity + member movies/series ordered by `DISPLAY_ORDER ASC`
- `GET /groups/{id}`, `GET /deaths/{id}` — entity + associated persons
- `GET /awards/{id}`, `GET /nominations/{id}` — entity + associated movies, series, and persons
- `GET /locations/{wikidata_id}` — Wikidata item (`T_WC_T2S_ITEM`) + movies and series linked via `T_WC_WIKIDATA_ITEM_PROPERTY` with `ID_PROPERTY IN ('P840', 'P915')` (narrative / filming location)

**MCP Endpoint** — see MCP section below.

### Response Fields (`Text2SQLResponse`)

Every response includes:
- **Core**: `question`, `question_hashed`, `sql_query`, `sql_query_anonymized`, `justification`, `justification_anonymized`, `answer`, `answer_anonymized`, `error`, `result` (list of `{"index": int, "data": dict}`)
- **Entity Extraction**: `entity_extraction` (dict of placeholder → value), `question_anonymized`
- **Performance Metrics**: `entity_extraction_processing_time`, `text2sql_processing_time`, `embeddings_processing_time`, `embeddings_cache_search_time`, `query_execution_time`, `total_processing_time`
- **Pagination**: `page`, `limit`, `offset`, `rows_per_page`, `llm_defined_limit`, `llm_defined_offset`
- **Cache Indicators**: `cached_exact_question`, `cached_anonymized_question`, `cached_anonymized_question_embedding`
- **Flags**: `ambiguous_question_for_text2sql`
- **Model Selection**: `llm_model_entity_extraction`, `llm_model_text2sql`, `llm_model_complex`, `ui_language`
- **Meta**: `api_version`, `messages` (ordered `TextMessage{position, text}` pipeline trace)

## MCP (Model Context Protocol) Server

The FastMCP server is mounted on the same FastAPI app — no extra container or port.

### Setup

- **Instance**: `mcp = FastMCP("text2sql")`; `mcp_app = mcp.http_app(stateless_http=True)`
- **Lifespan**: `FastAPI(..., lifespan=mcp_app.lifespan)` so FastMCP hooks run
- **Mount**: `app.mount("", mcp_app)` — Nginx proxies `/mcp` → FastAPI, FastMCP sees `/mcp/…`. Mounting at `""` avoids a `/mcp/mcp` double prefix.
- **Bearer auth**: `_verify_mcp_bearer` middleware checks `Authorization: Bearer {MCP_API_KEY}` only for paths starting with `/mcp`; skipped when `MCP_API_KEY` is empty
- **Internal base URL**: `MCP_INTERNAL_BASE_URL` auto-detected from `strapiversion` parity (`API_PORT_BLUE` if even, `API_PORT_GREEN` if odd). Tools make HTTP calls back to `127.0.0.1` with `MCP_INTERNAL_API_KEY` in `X-API-Key`.

### Tools (15)
`sql_search(question)` + one entity tool per endpoint: `get_movie`, `get_series`, `get_person`, `get_company`, `get_network`, `get_collection`, `get_topic`, `get_list`, `get_movement`, `get_group`, `get_death`, `get_award`, `get_nomination`, `get_location`.

Each tool's docstring is Layer 1 documentation (scope, exclusions, URL patterns, data coverage, pointer to the resource) — always loaded by Claude at conversation start.

### Resource
`context://database-scope` — Layer 2 semantic schema reference (entities, columns, value ranges, genre IDs, relationship tables). Loaded on demand when a complex question needs precise field knowledge.

### Client Registration

**Claude.ai Web Connectors** (syncs to Desktop + mobile): Settings → Connectors → Add Custom Connector → URL `https://yourdomain.com/mcp`. Claude.ai's connector UI supports OAuth only, not static bearer — leave `MCP_API_KEY` empty for web/mobile and rely on HTTPS.

**Claude Code CLI**:
```bash
claude mcp add text2sql --url https://yourdomain.com/mcp --header "Authorization: Bearer your-secret-key"
```

## Database Schema

Core tables used across the pipeline (full list: see [data/text_to_sql.md](data/text_to_sql.md) and the `context://database-scope` MCP resource):
- `T_WC_T2S_CACHE` — cache storage. Key fields: `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`, `JUSTIFICATION`, `ANSWER`, `API_VERSION` (`XXX.YYY.ZZZ`), `UI_LANGUAGE`, `IS_ANONYMIZED`, timing columns, `DELETED`, `DAT_CREAT`, `TIM_UPDATED`
- Primary entities: `T_WC_T2S_MOVIE`, `T_WC_T2S_SERIE`, `T_WC_T2S_PERSON`
- Related entities: `T_WC_T2S_COMPANY`, `T_WC_T2S_NETWORK`, `T_WC_T2S_TOPIC`, `T_WC_T2S_LIST`, `T_WC_T2S_COLLECTION`, `T_WC_T2S_MOVEMENT`, `T_WC_T2S_GROUP`, `T_WC_T2S_DEATH`, `T_WC_T2S_AWARD`, `T_WC_T2S_NOMINATION`
- Locations: `T_WC_T2S_ITEM` (Wikidata items) + `T_WC_WIKIDATA_ITEM_PROPERTY` (joined via `ID_PROPERTY IN ('P840', 'P915')`)
- Person AKAs: `T_WC_TMDB_PERSON_ALSO_KNOWN_AS` (used by RapidFuzz for non-Latin person names)
- Join tables follow `T_WC_T2S_{PARENT}_{CHILD}` convention (e.g., `T_WC_T2S_PERSON_MOVIE`, `T_WC_T2S_MOVIE_GENRE`, `T_WC_T2S_MOVIE_TOPIC`, `T_WC_T2S_SERIE_NETWORK`, `T_WC_T2S_MOVIE_AWARD`)

### Version Format

- Input: `"1.1.15"`
- Stored: `"001.001.015"` (via `format_api_version()` in both [main.py:33](main.py#L33) and [cleanup.py:5](cleanup.py#L5))

## Code Conventions

### Python Style

- **Naming Convention**: Hungarian notation for variables (legacy style)
  - `str` prefix for strings (`strtablename`, `strapiversion`)
  - `lng` prefix for integers (`lngpage`, `lngrowsperpage`)
  - `dbl` prefix for floats (`dblavailableram`)
  - `arr` prefix for arrays/lists
  - `int` prefix for boolean-like flags (`intcleanupenabled`, `intentity`)
- **Function Naming**: Public pipeline entry points prefixed with `f_` (`f_text2sql`, `f_entity_extraction`, `f_resolve_complex_question`, `f_answer_single_value`, `f_hello_world`). Internal helpers use a `_` prefix (`_call_chat_llm`, `_normalize_llm_model`).
- **Docstrings**: Google-style docstrings on public functions
- **Error Handling**: Broad try/except with console logging; errors surfaced in `error` response field and in the `messages` trace. Database errors during query execution are not returned directly to clients.
- **JSON Handling**: `logs.decimal_serializer()` for `Decimal` and `datetime`

### SQL Handling

**Escaping** — use SQL-style doubled single quotes, NOT backslash:
```python
value = "O'Brien"
sql_escaped = value.replace("'", "''")  # correct
```
`entity._sql_escape_literal()` centralizes this rule.

**Pagination** — LLM-emitted `LIMIT`/`OFFSET` clauses are detected and stripped by three regexes (`LIMIT n OFFSET m`, `LIMIT m, n`, `LIMIT n`); a smaller LLM-defined limit is respected when smaller than `rows_per_page` ([main.py:1010-1046](main.py#L1010-L1046)).

**Ambiguous Questions** — when the LLM cannot produce a valid query or when entity resolution leaves unresolved placeholders, `ambiguous_question_for_text2sql = True` is set, execution is skipped, and the LLM's explanation is surfaced in `error` (the legacy `##AMBIGUOUS##` marker is gone).

### Entity Resolution Config ([data/entity_resolution.json](data/entity_resolution.json))

Each entry has a `placeholder_prefix` and a `search_list`. Each search entry can define:
- `search_mode`: `"embeddings"` or `"rapidfuzz"`
- `apply_when_language_family_in` / `apply_when_language_family_not_in`: gate by script family
- `strtablename`, `strtableid`, `default_field`: SQL table / PK / display column
- `collection`: ChromaDB collection name (embeddings mode)
- `languages`: `{ "en": FIELD, "fr": FIELD, "*": FIELD }` for language-routed column selection on document IDs formatted as `{entity}_{id}_{lang}`
- `rapidfuzz_col_norm`, `rapidfuzz_col_key`, `rapidfuzz_col_popularity`: generated/norm columns for lexical matching
- `resolve_to_canonical`: when an AKA table returns a row, look up the canonical value in another table (e.g., `T_WC_TMDB_PERSON_ALSO_KNOWN_AS.ID_PERSON` → `T_WC_T2S_PERSON.PERSON_NAME`)

### Messages Array

Every processing step appends `TextMessage(position=int, text=str)` to `messages` with a monotonically increasing `position_counter`. On complex-question retry, messages from the outer and inner runs are renumbered and merged ([main.py:879-891](main.py#L879-L891)).

### Logging

- Log folder: `logs/` (auto-created)
- `logs.log_usage(endpoint, content, strapiversion)` — called by every endpoint (`hello`, `text2sql_post`, `start`, 14 entity endpoints)
- `logs.log_hot_reload(filename)` — called by `data_watcher` on every prompt reload
- Filename: `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`
- Writes only when file doesn't exist (no overwrites)

## Environment Variables

**Required:**
```bash
API_KEYS=key_for_app,key_for_mcp,key_for_scripts   # legacy API_KEY also accepted
OPENAI_API_KEY=sk-...

DB_HOST=localhost
DB_PORT=3306
DB_USER=dbuser
DB_PASSWORD=dbpass
DB_NAME=moviesdb

CHROMADB_HOST=localhost
CHROMADB_PORT=8000

API_PORT_BLUE=8000
API_PORT_GREEN=8001
```

**Optional:**
```bash
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...

MCP_API_KEY=your_mcp_bearer_token          # empty → /mcp is open (HTTPS-only protection)
MCP_INTERNAL_API_KEY=key_for_mcp           # defaults to first entry of API_KEYS
MCP_INTERNAL_BASE_URL=http://127.0.0.1:8010  # auto-detected from version parity
```

## Version Management

When updating prompt templates:
1. Bump `strapiversion` in [main.py:54](main.py#L54) (this also flips the Blue/Green port if the patch parity changes)
2. Edit the hot-reloaded file in `data/` directly (no versioned filename suffix — hot-reload picks changes up within 5 s without a restart)
3. Filenames registered at module import are static:
   - `text_to_sql.md`, `complex_question.md` ([text2sql.py:36,40](text2sql.py#L36))
   - `entity_extraction.md`, `entity_resolution.json` ([entity.py:12-13](entity.py#L12-L13))
4. If `intcleanupenabled=True` is set, startup cleanup removes old cached queries for the current version

## Local Development

```bash
cp .env.example .env           # fill in credentials
pip install -r requirements.txt
python main.py                 # port from strapiversion parity
```

Docs: `http://localhost:{port}/docs` (Swagger) / `/redoc` (ReDoc).

### Docker

```bash
docker build -t fastapi-text2sql .
docker run -p 8000:8000 --env-file .env fastapi-text2sql
```

Use `restart-blue.sh` (even versions, port 8000) or `restart-green.sh` (odd versions, port 8001).

## Evaluation Framework

See [eval/README.md](eval/README.md) for the Text2SQL evaluation harness that runs the API against curated question sets and scores SQL correctness, result-set quality, entity-resolution accuracy, and latency.

## Common Gotchas

### Gotcha #1 — SQL Quote Escaping

```python
"O'Brien".replace("'", "\\'")  # WRONG (breaks MariaDB)
"O'Brien".replace("'", "''")   # CORRECT (→ 'O''Brien')
```
Use `entity._sql_escape_literal()`.

### Gotcha #2 — Cache API Version Filtering

All cache reads and writes must pass `strapiversionformatted` (`XXX.YYY.ZZZ`), never the raw `strapiversion`. The `sql_cache` helpers already take the formatted version as a parameter.

### Gotcha #3 — ChromaDB Document IDs

Format: `{entity}_{id}_{lang}` (e.g., `movie_12345_fr`). Language drives the SQL field via the `languages` map in `entity_resolution.json`:
```
"languages": { "en": "MOVIE_TITLE", "fr": "MOVIE_TITLE_FR", "*": "ORIGINAL_TITLE" }
```

### Gotcha #4 — Entity Variable Matching in Embeddings Cache

A candidate document is only accepted when **all** extracted entity variables appear in it ([main.py:671](main.py#L671)):
```python
if all(var in doc_entity_vars for var in entity_variables):
```

### Gotcha #5 — Messages Position Counter

Always increment after appending:
```python
messages.append(TextMessage(position=position_counter, text="..."))
position_counter += 1
```
When delegating to `entity.resolve_entities()` or `_retry_with_resolved_complex_question()`, the updated counter is threaded through the return dict / merged message list.

### Gotcha #6 — Database Connection Lifecycle

Open once per request, pass the connection around, close in a `finally`. Do not call `get_db_connection()` inside loops.

### Gotcha #7 — Custom Embedding Function Interface

`OpenAIEmbeddingFunction` ([main.py:80](main.py#L80)) must implement both `__call__()` (batch) and `embed_query()` (single query) — ChromaDB needs both.

### Gotcha #8 — Complex Question Retry Recursion Guard

The pipeline can retry via the stronger model, but only when `complex_question_already_resolved` is `False`. When the outer call invokes itself recursively with a simplified question, it sets `complex_question_already_resolved = True` to prevent runaway retries.

### Gotcha #9 — Closed-Vocabulary Resolution

`Genre_name`, `Technical_format`, `Status_name`, and `Serie_type` are resolved via [closed_vocab.py](closed_vocab.py), which loads canonicals from the database at startup and merges aliases from [data/closed_vocabularies.json](data/closed_vocabularies.json) (hot-reloaded). `Genre_name` produces an integer `ID_GENRE` (no movie-vs-series split — both join tables share the same ID space); `Technical_format` produces an integer `ID_TECHNICAL` (joined to `T_WC_T2S_MOVIE_TECHNICAL`); `Status_name` and `Serie_type` produce canonical strings. Typo tolerance is uniform across all four via RapidFuzz with `score_cutoff=85` and `margin=5`. `Genre_name` also pulls multilingual aliases from `T_WC_TMDB_GENRE_LANG`; `Technical_format` has no `_LANG` companion table yet — multilingual aliases live in JSON only.

### Gotcha #10 — Regex Placeholders Reject Malformed Values

The 9 regex-validated placeholders (`Release_year`, `Birth_year`, `Death_year`, `IMDb_ID`, `IMDb_person_ID`, `Wikidata_ID`, `Wikidata_property_ID`, `TMDb_ID`, `Criterion_spine_ID`) validate against a fixed pattern in `entity._REGEX_PLACEHOLDER_RULES`. A value that fails the pattern is **rejected** — the placeholder is left in place, and the trailing unresolved-placeholder check marks the question ambiguous. Order in the rule list matters: `IMDb_person_ID` precedes `IMDb_ID`, and `Wikidata_property_ID` precedes `Wikidata_ID`, because dispatch uses `startswith()`. Numeric rules substitute as bare integers (and strip surrounding quotes via two regex passes); string rules substitute as quoted SQL string literals — adding new ID-style placeholders requires picking the right `is_numeric` based on the target column's SQL type.

### Gotcha #11 — MCP Mount Path

`app.mount("", mcp_app)` (empty string), not `"/mcp"`. Nginx strips/preserves `/mcp` upstream, and FastMCP's own routes live under `/mcp/…`. Mounting under `/mcp` produces `/mcp/mcp` paths.

## Security Considerations

1. **API Key Auth** — all FastAPI endpoints require `X-API-Key`; multi-key via `API_KEYS`
2. **MCP Bearer Token** — `/mcp` protected by `MCP_API_KEY` (skipped if empty for Claude.ai web/mobile compatibility)
3. **Constant-Time Comparison** — `secrets.compare_digest()` everywhere
4. **Secrets in `.env`** (never committed)
5. **Parameterized SQL** — all direct queries use `cursor.execute(query, params)`; inlined entity substitutions pass through `_sql_escape_literal`

## Performance Tips

1. Keep `retrieve_from_cache=True` / `store_to_cache=True`
2. Use `question_hashed` + `page` for pagination (avoids re-running entity extraction and Text2SQL)
3. Adjust `similarity_threshold` ([main.py:169](main.py#L169)) to trade cache hit rate vs accuracy
4. Ensure indexes on `T_WC_T2S_CACHE(QUESTION)`, `(QUESTION_HASHED)`, `(API_VERSION)`, `(TIM_UPDATED)`
5. For RapidFuzz, ensure `PERSON_NAME_NORM`, `PERSON_NAME_KEY` generated columns + FULLTEXT index exist (see `T2S_PERSON-rapidfuzz.sql`)
6. Reserve `complex_question_processing=true` for user-facing paths where the extra LLM cost is justified — each retry is an additional stronger-model call

## Troubleshooting

**Cache not working** — verify `API_VERSION` uses the formatted (`XXX.YYY.ZZZ`) form, question text matches (whitespace is normalized but exact after that), and `DELETED` is NULL/0.

**Entity not found** — confirm the entity exists in the right ChromaDB collection, the language family routing matches (for persons), and the similarity threshold isn't too strict. For RapidFuzz, verify the generated columns and (optionally) FULLTEXT index.

**SQL execution fails** — check that entity substitution used `''` escaping, pagination regex didn't mangle the query, and table/column names match the prompt schema. With `complex_question_processing=true`, execution failure triggers a one-time retry via the stronger model.

**Ambiguous question** — the `error` field contains the LLM's explanation. If entity resolution leaves placeholders in the SQL, the pipeline marks the question ambiguous even when Text2SQL produced output.

**MCP connector not working** — Claude.ai's connector UI only supports OAuth; leave `MCP_API_KEY` empty there. For Claude Code CLI, use `--header "Authorization: Bearer …"`.

## Additional Resources

- FastAPI — https://fastapi.tiangolo.com/
- OpenAI API — https://platform.openai.com/docs/
- Anthropic API — https://docs.anthropic.com/
- Google Gemini API — https://ai.google.dev/docs
- ChromaDB — https://docs.trychroma.com/
- FastMCP — https://github.com/jlowin/fastmcp
- RapidFuzz — https://rapidfuzz.github.io/RapidFuzz/
- Project guides: [MCP.md](MCP.md), [RAPIDFUZZ.md](RAPIDFUZZ.md), [eval/README.md](eval/README.md)

---

**Last Updated**: 2026-04-21
**Current Version**: 1.1.15
**Maintainer**: See repository owner
