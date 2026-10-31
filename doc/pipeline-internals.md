# Pipeline internals

File-by-file map of the code, and the reasoning behind the pipeline's scheduling, guards, retries, rescues, entity-endpoint contracts, rounding and clock.

Moved out of the root `AGENTS.md` on 2026-10-31 so that file keeps only the rules. A section name in italics refers to this document, to its siblings in `doc/` (`pipeline-internals.md`, `llm-tasks-and-costs.md`, `vision-pre-stage.md`), or to the rules left in [../AGENTS.md](../AGENTS.md) (the numbered *Gotchas* among them).

## Where things live (file → role)

Edit at the right layer; the architecture is intentionally split.

**[main.py](../main.py)** (~2460 lines) — FastAPI app, ChromaDB / DB startup, request orchestration only.
- Version utilities: `format_api_version()` ([main.py:33](../main.py#L33)), `compare_versions()` ([main.py:38](../main.py#L38))
- `strapiversion` lives at [main.py:137](../main.py#L137) (also drives Blue/Green port parity and `MCP_INTERNAL_BASE_URL`)
- `Text2SQLRequest` / `Text2SQLResponse` Pydantic models around [main.py:214-269](../main.py#L214-L269); the response rounds its numbers on serialization through [response_rounding.py](../response_rounding.py) (FASTAPI-TEXT2SQL-308), as do the entity endpoints via `RoundedJSONResponse`
- `POST /search/text2sql` : main pipeline endpoint. Its first stage is the vision pre-stage
  when the request carries an `image_ref` (FASTAPI-TEXT2SQL-114): identify, compose the
  question, then fall through to the ordinary pipeline
- `POST /uploads/vision` / `GET /uploads/vision/{image_ref}` : the binary deposit and its
  replay read (FASTAPI-TEXT2SQL-275), the only routes in this repo that carry bytes
- 19 entity detail endpoints (movies, series, seasons, episodes, persons, companies, networks, collections, topics, lists, movements, technicals, genres, groups, deaths, awards, nominations, locations, sourceworks). `/sourceworks/{id}` (FASTAPI-TEXT2SQL-323) is keyed on `ID_SOURCE_WORK`, the id every `based_on` item of `/movies/{id}` and `/series/{id}` carries; its `source_entity` stub names the T2S movie or series the source is (Scarface 1932), null otherwise, and its Wikipedia arrays stay empty until WIKIPEDIA-CRAWLER-023. The reverse of `based_on` now rides on `/movies/{id}` and `/series/{id}` too: `adapted_movies` and `adapted_series` (shipped in 1.1.19, in place) are the films and series adapted from THIS title when it is itself a source work (a source-work row carries its `ID_MOVIE` / `ID_SERIE`, e.g. Yojimbo for A Fistful of Dollars), paginated collections mirroring `/sourceworks/{id}`'s `movies` / `series` (`collection=adapted_movies|adapted_series`, image kind `movie` / `serie`, the title excluded from its own side), empty for an ordinary title. They let a client drop the two "adapted from this work" rails straight onto the film / series sheet instead of the source-work sheet. `seasons` and `episodes` are keyed on composite paths (`/seasons/{id_serie}/{season_number}`, `/episodes/{id_serie}/{season_number}/{episode_number}`) and read from the T2S read-model (`T_WC_T2S_SEASON`, `T_WC_T2S_EPISODE` and their credit, image and video tables) since FASTAPI-TEXT2SQL-179. `genres` reads the closed-vocabulary reference table `T_WC_T2S_GENRE` (PK `ID_GENRE`, no `ID_WIKIDATA`, so no Wikipedia arrays) since FASTAPI-TEXT2SQL-313; the API no longer reads `T_WC_TMDB_GENRE`, `T_WC_TMDB_GENRE_LANG` or `T_WC_TMDB_PERSON_ALSO_KNOWN_AS`.
- FastMCP instance + 21 MCP tools (`sql_search`, 19 entity tools including `get_source_work`, `list_samples`), 1 resource (`context://database-scope`), bearer-token middleware, `app.mount("", mcp_app)` at root. Every detail endpoint has its `get_*` wrapper; `get_season` and `get_episode` (FASTAPI-TEXT2SQL-314) take the composite keys of their HTTP paths (`id_serie`, `season_number`, `episode_number`), not `ID_SEASON` / `ID_EPISODE`. `_mcp_get` turns an HTTP error into `{"error": <endpoint detail>, "status_code": <code>}`

**[text2sql.py](../text2sql.py)** — core LLM logic.
- `_call_chat_llm()` — unified multi-provider dispatcher (OpenAI / Anthropic / Google). Routes on prefix: `gpt-*`/`o1*`/`o3*` → OpenAI; `claude-*` → Anthropic; `gemini-*` → Google.
- `f_text2sql(user_question, model, ui_language)` — text-to-SQL conversion; replaces `{ui_language}` in the prompt template so the LLM generates the `answer` field in the requested language.
- `f_resolve_complex_question()` / `f_resolve_complex_question_retry_payload()` — complex-question simplification via stronger model.
- `f_build_retry_question_from_reasoning()` — deterministic retry-question composer (typed entities + years).
- `f_identify_from_image()` / `_call_vision_llm()` : the sixth task, the only one whose input
  is an image (FASTAPI-TEXT2SQL-114). OpenAI route only, and the error says so.
- `compose_vision_question()` / `select_vision_candidates()` / `question_targets_the_image()` :
  the deterministic half of the vision path: what the model identified becomes a question here,
  never in the model. See *The vision pre-stage*.
- Hot-reloads `text_to_sql.md`, `complex_question.md` and `vision_identification.md` via
  `data_watcher`.

**[entity.py](../entity.py)** — entity extraction + resolution.
- `f_entity_extraction()` — LLM-based extraction + anonymization.
- `_run_extraction_prompt()` — the prompt-call + JSON-cleanup body behind it.
- `plan_entity_resolutions()` — the expensive, SQL-independent half of resolution (regex, closed vocab, ChromaDB, RapidFuzz, row lookups). Returns `{"entities": [...], "planning_time": float}`.
- `apply_entity_resolutions()` — the cheap half: substitution into SQL / justification / answer, plus the recorded diagnostics.
- `resolve_entities()` — the two back to back; unchanged signature, still the right call when there is nothing to overlap with.
- `_match_regex_placeholder_rule()` — dispatch helper for regex placeholders.
- `_REGEX_PLACEHOLDER_RULES` — list of `(prefix, regex, is_numeric)` tuples; **order matters** (uses `startswith()`).
- Hot-reloads `entity_extraction.md` and `entity_resolution.json` via `data_watcher`. Both must exist on disk at import time: `data_watcher.register()` reads them eagerly and raises if one is missing, which kills the container at boot.

**[closed_vocab.py](../closed_vocab.py)** — closed-vocabulary lookups (DB canonicals + JSON aliases + RapidFuzz typo tolerance).
- `init(connection)` — loads canonicals at startup. Called once from `main.py` startup.
- `resolve(entity, raw_value)` — string-canonical lookup (`Status_name`, `Serie_type`, `Department_name`).
- `resolve_genre(raw)` / `resolve_technical(raw)` — integer-ID lookups (`ID_GENRE`, `ID_TECHNICAL`).
- Aliases hot-reload from [data/closed_vocabularies.json](../data/closed_vocabularies.json).

**[rapidfuzz_query.py](../rapidfuzz_query.py)** — lexical matching.
- `search_first_match()` — exact-norm → key prefix → FULLTEXT → LIKE last resort, ranked with `fuzz.WRatio`.
- Thresholds: `AUTO_SCORE = 90`, `MIN_MARGIN = 5`, `TOP_K = 10`.
- Requires `*_NORM` / `*_KEY` generated columns and (optional) FULLTEXT index — see [RAPIDFUZZ.md](RAPIDFUZZ.md).

**[sql_cache.py](../sql_cache.py)** — cache helpers.
- `search_sql_cache_by_question_hash()`, `search_sql_cache_by_question_text()`, `write_sql_cache_entry()` — all take the **formatted** API version (`XXX.YYY.ZZZ`).
- `_normalize_cache_row()` — picks `SQL_QUERY` over `SQL_PROCESSED` when needed to preserve a smaller LLM-defined `LIMIT` (see `used_raw_query_to_preserve_limit`).

**[vision_cache.py](../vision_cache.py)** : the recognition cache of the vision path
(FASTAPI-TEXT2SQL-114), keyed on the MD5 of the image bytes and the formatted API version, in
its own table `T_WC_T2S_VISION_CACHE`.
- `search_vision_cache()` / `write_vision_cache_entry()` : degrade to a silent miss when the
  table is absent, so the path works before the migration runs.
- `identification_payload()` : **the contract**, what is stored is what depends on the image
  and not on the question. Adding a question-dependent key here makes the cache serve
  yesterday's answer to today's question.

**[sql_shapes.py](../sql_shapes.py)** : structural predicates over a generated SQL query. Pure string analysis, no DB and no LLM: it answers *what shape does this query have*, never *is it right*.
- `detect_person_role_collapse(sql_query, result_entity)` : true when a person-listing query pins the `ID_PERSON` it projects to a person named in the question, a shape that can only ever return that named person (FASTAPI-TEXT2SQL-211).
- It exists as its own module so the runtime guard in `main.py` and the measurement in `analyze-complex-retry-logs.py` share the **exact same predicate**. A guard measured with a rule other than the one it runs is a number about nothing; do not fork the logic back into either caller.

**[analyze-usage-logs.py](../analyze-usage-logs.py)** : the replayable measurements of the HARNESS-BRICKS backlog topic, read from the usage logs and the evaluation exports, written as two dated HTML pages. See *Replaying the usage measurements*.

**[cleanup.py](../cleanup.py)** — version-scoped purge utilities (off by default; see `intcleanupenabled` at [main.py:70-71](../main.py#L70-L71)).

**[auth.py](../auth.py)** — `get_api_key()` Security dependency. Multi-key via `API_KEYS` (comma-separated); `secrets.compare_digest()` for constant-time comparison.

**[data_watcher.py](../data_watcher.py)** — `register(filename, callback)`; daemon thread polls `./data/` every 5 s on mtime; logs hot reloads via `logs.log_hot_reload()`.

**[language_family.py](../language_family.py)** — `guess_language_family()` from Unicode code points (Latin / Hangul / Japanese / Chinese / Cyrillic / Arabic / Hebrew / Devanagari / etc.).

**[logs.py](../logs.py)** : `log_usage(endpoint, content, strapiversion)` and `log_hot_reload(filename)`. Filenames are `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`; never overwrite existing files. Also the request clock (`start_request_clock`, started by the `_RequestClock` middleware of `main.py`) that stamps `server_time` and `cpu_time` in every log written during a request (FASTAPI-TEXT2SQL-337).

**[llm_costs.py](../llm_costs.py)** : the price table (dollars per million tokens, with sources and date) and the arithmetic that turns `llm_usage` and `embedding_usage` into `llm_cost` (FASTAPI-TEXT2SQL-337), plus the VPS rate (`VPS_EUR_PER_MONTH`, `EUR_PER_CPU_SECOND`) behind `server_cost_eur` (FASTAPI-TEXT2SQL-338). The only place a price lives; see *What a call costs*.
- `now_paris()` and `PARIS_TZ` are the one clock of the repo (FASTAPI-TEXT2SQL-328): every stamp a human reads goes through them, and every "now" compared with an upload horizon too. See *One clock: Paris time, with its offset* below.
- `LOGS_FOLDER` is the **relative** `"logs"`, and that is load-bearing. Making it absolute or
  configurable would re-split the corpus per colour; see *`logs/` and `uploads/` are shared*.

**[uploads.py](../uploads.py)** — the vision-mode image deposits (FASTAPI-TEXT2SQL-275), the only binary path in this repo.
- `store_vision_image(imagebytes, strapiversion)` — magic-number check, house filename, write, and the `image_ref` returned to the client.
- `f_getuploadfilename()` — twin of `logs.f_getlogfilename`, same `YYYYMMDD-HHMMSS_<kind>_<version>_<md5>` shape, **hash over the raw bytes**; do not reuse the log one, it hashes `contenttext.encode('utf-8')`.
- `parse_image_ref()` / `vision_image_path()` — the guard between a client string and the filesystem. Anything the generator could not have produced is refused before a path exists.
- `load_vision_image()` — the replay read, raising `UploadUnavailable` **with the deposit date and the purge** when the file is gone.
- `UPLOADS_FOLDER` is relative for exactly the same reason, and with a sharper failure mode:
  absolute or per-colour makes a post-flip replay fail **silently**.

**[data/](../data/)** : hot-reloaded prompts and config. [data/AGENTS.md](../data/AGENTS.md) carries
what only matters when editing one of these files, in particular the three rules twinned
between `complex_question.md` and `vision_identification.md`, which share a motive and must
keep different instructions:
- `text_to_sql.md` — main Text2SQL prompt (loaded by [text2sql.py](../text2sql.py))
- `complex_question.md` — complex-question resolver prompt (loaded by [text2sql.py](../text2sql.py))
- `entity_extraction.md` — entity extraction prompt (loaded by [entity.py](../entity.py))
- `entity_resolution.json` — per-placeholder resolution strategy list (loaded by [entity.py](../entity.py))
- `closed_vocabularies.json` — alias dictionaries (loaded by [closed_vocab.py](../closed_vocab.py))
- `vision_identification.md` : the image-reading prompt (loaded by [text2sql.py](../text2sql.py))

**[maintenance/](../maintenance/)** — one-shot operational SQL, run by hand against the production DB, no code path loads it. Distinct from `doc/sql/` (reference DDL, read-only) and from `text2sql-eval/assertions-*.sql` (which writes to the evaluation bank): this folder writes to operational tables, `T_WC_T2S_CACHE` first among them. Conventions and the cache facts a cleanup relies on are in [maintenance/AGENTS.md](../maintenance/AGENTS.md); read it before adding or running anything there.

## Pipeline scheduling: what runs in parallel

`/search/text2sql` used to be an `async def` that never awaited anything, so every LLM call blocked the event loop and requests serialized. Three calls now go through `asyncio.to_thread`: `f_text2sql`, `f_classify_result_entity` and the answer-entity guard's regeneration. Consequences worth knowing:

- **Four calls, not three, since the vision task.** `f_identify_from_image` goes through
  `asyncio.to_thread` for the same reason as the other three: it is the slowest call of the
  six, and blocking the event loop on it would serialize every concurrent request behind one
  photo.
- **Requests now genuinely interleave.** Per-request state (the DB connection, the messages list) is local; module state touched at request time is either read-only after startup (prompts, closed-vocab canonicals) or lock-protected (`_BKTREE_CACHE`). The prompt-cache buffer is a `ContextVar` holding a list, and `asyncio.to_thread` copies the context by reference, so appends from worker threads still reach the response.
**The fork-join (FASTAPI-TEXT2SQL-201).** Entity resolution iterates over the extraction payload, not over the placeholders found in the SQL, and `f_text2sql` only ever sees `input_text_anonymized`. The two branches are therefore independent, and `plan_entity_resolutions()` is started in a worker thread just before the text-to-SQL call, then joined right after the answer-entity guard. **The join is unconditional and must stay where it is**: the complex-question retry path below it closes the connection the worker thread is using. A plan that raised degrades to `resolve_entities()` on the sequential path.

**The second fork (FASTAPI-TEXT2SQL-286).** `f_classify_result_entity` reads only the original question and the label set, so it is started as a task at the top of the text2sql block (after the anonymized-question cache lookup and the complex-question routing) and joined just before the answer-entity guard; it was first forked at request entry, but the join and the guard only run inside that block, so its label was dropped on every anonymized-cache hit and complex escalation (11 wasted calls out of 96, FASTAPI-TEXT2SQL-306); until 1.1.19 it ran serially after SQL generation (0.96 s median, 12.8 s p99). It holds **no** DB connection, so unlike the resolution fork an early return between fork and join is harmless: the thread finishes, the label is dropped. Consequences: `result_entity_processing_time` is the call's own duration and **overlaps** extraction and text2sql, so `total - sum of stages` goes negative; a wasted classification is paid on requests that end without SQL (errors, complex escalations), about a thousandth of a cent each; a failed call abstains. Not forked on the exact-cache hit (nothing to overlap) nor on the identity re-entry of -300. `RESULT_ENTITY_PARALLEL=0` restores the sequential call.

**One accepted behavioural divergence.** When a placeholder is extracted but appears nowhere in the SQL, the justification or the answer, the old resolver ran *every* strategy and logged each one before discarding the result; the planner stops at the first strategy that resolves. The three texts come out identical, only the message trace is shorter. Everything else is byte-identical, message traces included.

## One slow SQL query must not freeze the API (FASTAPI-TEXT2SQL-302)

The generated SQL runs through `_run_generated_sql` (main.py), **never** with a bare
`cursor.execute` inside the async endpoint. Two reasons, both learned the hard way on
2026-09-27, when a gpt-6-sol query for "How many movies are there?" (`COUNT(*) OVER ()` over
~688,000 rows) froze production until it was killed by hand:

- **Off the event loop.** It is called through `asyncio.to_thread`, like every LLM call. A
  blocking `execute` in the endpoint stops every other request of every client for as long as
  the query runs.
- **Capped in time.** It is sent as `SET STATEMENT max_statement_time=N FOR <query>`; MariaDB
  kills it at N seconds (error 1969), so nothing survives in `PROCESSLIST`. `N` is
  `SQL_MAX_STATEMENT_TIME` (env, default 60, 0 disables). 60 s was chosen on measurement: the
  slowest of the 1,739 executions of the 1.1.19 baseline took 23.2 s.

A query interrupted at the cap fails with `sql_execution_failure_code = "sql_timeout"`, the
response carries `error_code: "sql_timeout"` and an explicit error, and it is **not** sent to
the SQL regeneration nor to the stronger-model retry: a rewrite of a query that proved too heavy
can be just as heavy, and would pay the cap a second time. Any new place that executes
model-written SQL goes through the same helper.

**A whole-result window count is refused before it reaches MariaDB** (FASTAPI-TEXT2SQL-303).
`SQL_GUARD_WINDOW_COUNT` rejects `COUNT(...) OVER ()` like the leading-wildcard LIKE of -223,
with `sql_guard_rejected`, so the targeted regeneration retries once with the reason and the shape
to write. It is how gpt-6-sol answered "How many movies are there?": the prompt told it that a
question which counts still returns entity rows. `data/text_to_sql.md` now has "A single total:
one row, one column", and the aggregation rule says "per entity". A single total is one cell:
`SELECT COUNT(DISTINCT <id>) AS <X>_COUNT FROM ... [WHERE ...]`.

**The answer-entity guard exempts a single total** (FASTAPI-TEXT2SQL-303, 2026-09-29). The guard
(-117/-136) regenerates any query that does not project the id column of the expected entity. A
single total projects no id by design, so the guard used to demand entity rows: gpt-6-sol obeyed
and failed its counts (793, 2169-2172, 2313), gpt-4o failed to regenerate and kept its count,
passing by accident after a discarded LLM call. `_is_single_total_select` now lets through a query
whose outer SELECT list is exactly one `COUNT(...)` with no `GROUP BY`. Not MIN or MAX, on
purpose: "What is the longest movie?" written as `SELECT MAX(RUNTIME)` is still a wrong answer the
guard must turn into the movie row.

**Extended by FASTAPI-TEXT2SQL-311 (2026-10-04)**, on two measured cases (evaluations 2524 and
2525): the generator wrote the right shape and the guard rewrote it wrong. "The average runtime of
Christopher Nolan movies", one `AVG` cell, became one average per technical format; "the average
IMDb rating of Kubrick movies per decade", grouped by decade, became one row per film.

- The single total now also takes `AVG` and `SUM` (no single row can carry them), `ROUND()`
  around the aggregate included. Still not `MIN` / `MAX`.
- `_is_statistics_table_select` lets through a **statistics table**: a `GROUP BY` whose keys are
  all attributes (decade, year, language), keys resolved through aliases and ordinals, every
  projected column a key or an aggregate, no window function, no `UNION`. A key that is an
  identity (`ID_*`, `*_NAME`, `*_TITLE`, `DESCRIPTION`) disqualifies it: "directors with the most
  films" grouped on `PERSON_NAME` alone is exactly what the guard must still turn into person rows.
- **Offline check:** `uv run checks/verif-311.py` (23 cases, both directions). **Replayed** on the
  11,477 SQL statements of the 5,502 executions of the 1.1.19 campaigns: no `AVG`/`SUM` total and
  no statistics table among them, and the 266 `GROUP BY` queries all project an entity id and are
  all rejected by the new rule. So -311 changes no decision on the existing bank; its only
  coverage is 2524 and 2525.

## Numbers are rounded on the way out, and only there (FASTAPI-TEXT2SQL-308)

[response_rounding.py](../response_rounding.py) rounds every number of a response at
serialization time. Two hooks, one function (`round_tree`):

- `Text2SQLResponse` carries a `@field_serializer("*", mode="wrap")`: every field, `result`
  rows included, is rounded in `model_dump()` and in the JSON. **The attributes keep their raw
  values**, so the code that reads a response after building it (the complex retry, the
  first-pass record) still sees exact numbers, and the log, built from `model_dump()`, holds
  what the client received.
- The 18 entity endpoints declare `response_class=RoundedJSONResponse`. A new entity endpoint
  must declare it too; `checks/verif-308.py` counts them and fails otherwise.

Precision by key, case-insensitive: two decimals by default (a non-zero value under 0.1 keeps
three significant digits instead of collapsing to 0.0), `*_time` / `*_seconds` three,
`distance` / `*_distance` four, `fuzz_ratio*` one, `BUDGET` / `REVENUE` an integer when whole,
`FRAME_RATE` three, the Wikidata quantities (`AMOUNT`, `AMOUNT_NORMALIZED`, `LOWER_BOUND`,
`UPPER_BOUND`) and coordinates converted but never rounded.

**Why not in SQL or in the prompt.** MariaDB sorts on the exact value before anything is
rounded, so no `ORDER BY` changes; a `ROUND()` asked of the model would be forgotten some of
the time, would change the shape of cached SQL, and an `ORDER BY` on a rounded alias creates
ties. The entity-resolution thresholds compare the raw distances, upstream of serialization.

**The `Decimal` trap this also closes.** MariaDB returns `AVG()` and `SUM()` over an integer
column as `DECIMAL`, PyMySQL hands over a `decimal.Decimal`, and Pydantic v2 serializes a
`Decimal` found inside `result: List[dict]` as a JSON **string** (`"148.4000"`), while the
entity endpoints, through `jsonable_encoder`, emitted a number. Both now emit a number (an
`int` when the value is whole). Do not reintroduce a `Decimal` path that bypasses the two hooks.

**Offline check:** `uv run --with "fastapi>=0.104.1" --with httpx checks/verif-308.py`
(38 cases, no API, no database). It reads `Text2SQLResponse` out of `main.py` like
`verif-114.py` does; that script's model namespace now also carries `field_serializer` and
`round_tree`, and any other script that execs the model block needs the same two names.

## Entity endpoints: the contracts to preserve

`README.md` documents what these endpoints **return**: the `ui_language` collapse, the
`data_freshness` block, the `wikipedia_page` credit and the `collection` pagination. Below is only
what **breaks when you edit them**.

**Localization.** `localize_response()` collapses each `<COL>`/`<COL>_FR` pair, so it can only
collapse what the SELECT fetched: a new nested related-entity SELECT **must select the `_FR`
variant** alongside the canonical column. Image paths have no `_FR`, so they go through
`apply_localized_main_image()` (top-level entity) and `apply_localized_related_images()` (nested
rows, one batched query per kind declared in `_RELATED_IMAGE_SOURCES`: `movie` / `serie` →
`POSTER_PATH`, `person` → `PROFILE_PATH`, `season` → `POSTER_PATH`), so a new nested array of
movie / serie / person / season rows **must be added to that endpoint's
`apply_localized_related_images` call**. Both run after `logs.log_usage` and before
`localize_response`, which is why logs keep the canonical path and both language columns.
Episodes are excluded: `STILL_PATH` frames are not language-specific.

**Data freshness.** `_build_data_freshness(cursor, row, record_source, ui_language)`. The argument
to get right is `record_source`, because it is what licenses labelling `TIM_UPDATED` as a TMDb
date. `RECORD_SOURCE_TMDB` only where `tmdb-movie-preprocess` copies `TIM_UPDATED` **verbatim**
from the `T_WC_TMDB_*` row (movies, series, seasons, episodes, persons, companies, networks);
`RECORD_SOURCE_WIKIDATA` everywhere else, where `tmdb_updated_at` **must stay null**, since
labelling a Wikidata refresh as a TMDb date is a lie a voice client repeats out loud;
`RECORD_SOURCE_REFERENCE` for `/genres`, all nulls.

**One language resolution, two consumers.** `_resolve_wikipedia_page_row()` is the single home of
the rule (the requested language wins only when it actually has sections, English otherwise).
`_fetch_wikipedia_freshness()` *dates* the content and `_fetch_wikipedia_page()` *credits* it from
the same row, so `wikipedia_page.lang == data_freshness.wikipedia_lang` must hold on every
response. That invariant is the cheapest regression check in the repo, internal and needing no
fixture. If you change the fallback in `_fetch_wikipedia_content` or `_fetch_wikipedia_images`,
change it there too, or a response dates one language and credits another. Do not add a third
resolution, and never resolve on the page row's *existence*: a row can exist for a language
carrying zero sections, and crediting that article over English prose is a false attribution,
worse than no credit. `verify_wikipedia_page.py` checks all of it against a deployed API and
reports what it could not reach as SKIPPED rather than passing it. Every source column stays in an
allowed table, so the restricted-DB table-scope contract (DATA-DISTRIBUTION-008) holds without new
promotions.

**Wikipedia Markdown and mentions (2026-10-16).** `_fetch_wikipedia_content(..., wikipedia_format)` serves `CONTENT_MD` per section when asked (`format`, `references` per element); the `text` branch must stay byte for byte what it was, since every existing client reads it. The six `mentions_*` / `mentioned_in_*` lists come from `_wikipedia_mention_collections()`, merged into each endpoint's registry at the `_run_collections` call and attached by `_attach_wikipedia_mentions()`, so a new Wikipedia-carrying endpoint needs those three calls plus the `wikipedia_format` parameter on the route and on its MCP tool. tmdb-front's `f_wikipediamentions()` applies the same rules (date links out, 20,000-page cap backward, adult and deleted rows out); change both together. `checks/test-wikipedia-md-mentions.py` checks the helpers and the wiring of all 16 endpoints offline. The two tables are in the T2S backup perimeter (`tools/backupvaugouindb-t2s.sh`).

**Pagination.** Each endpoint declares a local `pcollections` registry mapping
`collection_name -> (sql, params, image_kind)`, driven by `_run_collections()`. It is the single
source of truth for both the untargeted and the targeted mode, so a new nested related-entity list
**goes in the registry**, never in a one-off `cursor.execute`. Every registry SQL must select
`COUNT(*) OVER() AS _TOTAL_COUNT` (MariaDB >= 10.2; stripped by `_paginate_collection`), carry a
deterministic `ORDER BY` with a unique tiebreaker, and omit its own `LIMIT` and semicolon, which
the helper appends. `cast` / `crew` and the four person variants are split per `CREDIT_TYPE` with
`CAST_CHARACTER_EXCLUSIONS` pushed into SQL.

**MCP alignment.** The `get_*` tools relay the endpoint JSON verbatim (`_mcp_get` returns
`r.text`), so a new collection's **data** appears in MCP with no code at all. Its **docstring does
not**: that is hand-maintained and it is the MCP contract. List the new collection there twice, in
the relations enumeration and among the valid `collection` values, or it stays invisible to MCP
clients although the data is present.

## Typographic rescue of the gate (`rescue_normalizations`, FASTAPI-TEXT2SQL-309)

**What it fixes.** Eval 475, "Movie Bell' Antonio": the vector search put *Il bell'Antonio* (TMDb
76157) at rank 1 of the shortlist, distance 0.361, and the gate refused it at `fuzz.ratio` **85.7**
for a movie threshold of **85.85**. One of the four characters counted against it is the space typed
after the elision apostrophe; the French spelling of the same eval, `Bell'Antonio`, scores 88.9 and
passes. The question then escalated to the complex model, which on gpt-4o returned it unchanged.

**How.** A **second pass** over the same shortlist, reached only when the first pass (gate plus the
-224 walk) has refused **every** candidate. Same thresholds, same `score_stopwords`; only the strings
compared are normalised, on both sides, by the normalisers the strategy names in
`rescue_normalizations` (registry: `RESCUE_NORMALIZERS` in [rapidfuzz_query.py](../rapidfuzz_query.py)).
Three properties follow, and they are why it was built as a second pass and not as a change to the
gate:

- A value that resolves today never reaches the new code, so **no current answer can change**. Only
  today's raw fallbacks can, and those are already failures (0 rows, then the complex model).
- The first pass computes exactly what it computed before: `_score_candidate` only normalises when
  the second pass passes it normalisers.
- What is written into the SQL is the stored document, never the normalised form.

**Normalisers** (`RESCUE_NORMALIZERS` in [rapidfuzz_query.py](../rapidfuzz_query.py), applied in a
fixed order whatever the order of the list): `apostrophes` (every form of `’ ‘ ʼ ´`, backtick and
prime becomes `'`, no space around it), `accents` (diacritics folded: `amelie` against `amélie`
scores 83.3, refused at 85.85), `dashes` (every dash becomes a space), `punctuation` (`. , : ; ! ?`,
quotes, brackets removed; NOT the apostrophe, NOT `&`, NOT digits). An unknown name is refused when
the configuration loads, so a typo keeps the previous configuration instead of reaching a request.

**The second pass takes the best normalised score**, not the first candidate that passes; a tie
keeps the walk order. Measured by eval-309 on 2026-10-04: "Prete a tout" (accents dropped) took
*Prêt à tout* first in rank order at 95.7, while *Prête à tout*, further down, scored 100.
Normalising brings near-homonyms closer together, so the pass must compare them.

**Configured per type, from the eval-309 run of 2026-10-04** (3,557 values; `none` to `full`:
46 changes, read one by one), never by intuition:

| Type | `rescue_normalizations` | Why |
|---|---|---|
| `Movie_title`, `Serie_title`, `Network_name`, `Group_name`, `Location_name`, `Topic_name` | all four | rescues right; the only "errors" were homonyms (two *S.O.S. Fantômes*, two *E!*) and *Prête à tout*, fixed by the best-score rule |
| `Company_name` | apostrophes, accents, dashes | punctuation took "Warner Bros" to *Warner Bros. China* (75.9 to 78.6, threshold 77.5) |
| `Collection_name` | none | no right rescue in any stage, two wrong ones: dashes took "Collection Dracula" to *Dracula 2000 - Saga* (66.7 to 73.7, threshold 73.5); without dashes, accents took "Miss Detective - Saga" to *Détective K - Saga* (69.0 to 75.9), the right collection not being among the ten candidates. The ` - Saga` documents and the low threshold make any normaliser risky here |
| `Award_name`, `Death_name`, `List_name`, `Movement_name`, `Nomination_name` | none | no rescue measured, so no evidence either way |

**Deliberately not normalised:** leading articles (they raise every score carrying one, so they
loosen the gate, and *Die*, *Las*, *El*, *Le* are words in other titles), `&` ("and" or "et"),
numbers (`2` against `II`). Do not lower a threshold to get the same effect: that widens -299, where
the gate already accepts wrong candidates. The collision to watch with `punctuation`: *mother!*
(2017) and *Mother* (2009).

**Reading it.** The trace says `typographic rescue (apostrophes) accepted rank N '...'` with both
scores; `match_scores` carries `rescue_normalizations` (empty when the first pass decided),
`fuzz_ratio_first_pass` and `candidate_id` (the ChromaDB id of the candidate weighed).

**The stage evaluation, in Docker only** (`uv` is not available on the VPS). [checks/eval-309.sh](../checks/eval-309.sh)
runs [checks/eval-309.py](../checks/eval-309.py) in a throwaway container built from the API image, with
this checkout mounted read-only and the share at `/shared`. The stage is set in memory inside that
container, so the running API and `data/entity_resolution.json` are untouched, and the three stages
are measured on the same pulled checkout before any restart:

```bash
cd ~/docker/fastapi-text2sql-green && git pull          # the running API is not affected
cd checks
./eval-309.sh none            # the gate as it was: no second pass
./eval-309.sh apostrophes     # the first fix
./eval-309.sh full            # apostrophes, accents, dashes, punctuation
./eval-309.sh configured      # each type with its list from entity_resolution.json: what the restart deploys
./eval-309.sh compare         # what changed between stages: NEW WRONG, UNKNOWN and HOMONYM acceptances
NORMALIZERS=accents ./eval-309.sh custom   # one normaliser alone, to isolate it
```

Corpus: values the gate refused in the exports (right or wrong read from the row's
`ID_... IN (...)` assertion), catalogue values, the same retyped (space after the apostrophe,
curly apostrophe, accents dropped, dash as a space, punctuation dropped), values of other types and
invented names, some with apostrophes and accents so the normalisers get every chance to admit
them. The bar for switching a normaliser on for a type: **0 new wrong acceptances** against
`none`. Results in `shared_data/text2sql-eval/eval-309/`. `checks/check-rescue-309.py` (the real
branch with eval 475's shortlist, no database) and `checks/replay-rescue-309.py` (every refusal of the
exports, rescored offline from the traces) are the offline checks; run them in the same container
when on the VPS.

The offline replay of 2026-10-04, stage `apostrophes`, over the 17 runs then on disk: 230 refusals
of a title resolver, **one** distinct rescue (*Bell' Antonio*), no wrong acceptance. It reads only
the five candidates the trace prints, so it is a lower bound.

## Entity-resolution config schema (`data/entity_resolution.json`)

Each entry has a `placeholder_prefix` and a `search_list`. Each search entry can define:
- `search_mode`: `"embeddings"` or `"rapidfuzz"`
- `apply_when_language_family_in` / `apply_when_language_family_not_in`: gate by script family
- `strtablename`, `strtableid`, `default_field`: SQL table / PK / display column
- `collection`: ChromaDB collection name (embeddings mode)
- `languages`: `{ "en": FIELD, "fr": FIELD, "*": FIELD }` for language-routed column selection on document IDs formatted as `{entity}_{id}_{lang}`
- `rapidfuzz_col_norm`, `rapidfuzz_col_key`, `rapidfuzz_col_popularity`: generated/norm columns for lexical matching
- `resolve_to_canonical`: when an AKA table returns a row, look up the canonical value in another table (e.g., `T_WC_T2S_PERSON_ALSO_KNOWN_AS.ID_PERSON` → `T_WC_T2S_PERSON.PERSON_NAME`)

**Confidence gating (opt-in, per strategy).** By default both search modes always substitute their best candidate — a degraded shortlist or a near-miss then produces a *confidently wrong* entity rather than an error. Three optional keys make a strategy fail safe (fall through to the next strategy, then to raw fallback / ambiguous) instead:
- `min_fuzz_ratio` (embeddings): reject the chosen candidate when `fuzz.ratio(query, candidate) < min_fuzz_ratio`. Uses `fuzz.ratio` (edit distance), **not** `WRatio` — titles sharing a suffix (e.g. "… Collection") inflate WRatio's token_set component and let unrelated entries through. An exact normalized document match always passes. When rejected, a diagnostic message logs the chosen candidate and the top-5 shortlist with distances.
- `max_distance` (embeddings): reject when the ChromaDB distance of the chosen candidate exceeds this. Weak discriminator for short proper nouns (near-duplicates sit at similar distances), so prefer `min_fuzz_ratio`; combine both only when distances are meaningful for that collection.
- `rescue_normalizations` (embeddings): a list of normaliser names (`apostrophes`, `accents`, `dashes`, `punctuation`) for a second scoring pass when the gate has refused every candidate; see *Typographic rescue of the gate* above (FASTAPI-TEXT2SQL-309).
- `require_confident` (rapidfuzz): only accept an exact / high-confidence auto-correct (`auto` True); a low-confidence lexical guess falls through. Off by default so `Person_name` keeps always-resolve behaviour.

`Collection_name` uses both: a `require_confident` **rapidfuzz** strategy first (exact-normalized DB match — robust and independent of ChromaDB/RAM state), then the gated **embeddings** strategy (`min_fuzz_ratio: 72`) as a semantic/French fallback. The rapidfuzz strategy needs the generated columns in [doc/sql/T2S_COLLECTION-rapidfuzz.sql](sql/T2S_COLLECTION-rapidfuzz.sql); until that migration runs it no-ops and only the embeddings strategy is active.

ChromaDB document ID format is always `{entity}_{id}_{lang}` (e.g., `movie_12345_fr`). Language drives the SQL field via the `languages` map.

## The first pass of a retried request is recorded (FASTAPI-TEXT2SQL-241)

When one of the three complex-retry paths fires (text2sql error, execution failure, 0 rows on
page 1), `_retry_with_resolved_complex_question` reruns the whole pipeline on the stronger
model's rewrite and returns the INNER response, with the outer messages merged in front. Before
-241 the SQL that failed and the reason it failed survived nowhere: that early return skipped the
`logs.log_usage` call at the end of `search_text2sql`, so the only file on disk was the inner
pass's, whose `request.question` is the rewritten question.

`README.md` documents the five `first_pass_*` / `complex_retry_*` response fields and the closed
vocabulary of `first_pass_failure_code`. Five things it does not say:

- **The fields are set on the inner response right after it is produced**, so the returned object
  and the **outer** log file carry them; the inner log file, written before that, does not.
- **`entity_extraction` and `first_pass_entity_extraction` answer different questions.** The
  first describes the pass that produced the returned rows, so on a retry it holds the INNER
  extraction of the rewritten question (`Serie Twin Peaks`), and it is `null` when that inner
  pass hit the exact-question cache and never extracted anything. The second holds what the
  user's own wording produced, which is where `query_mode` reads `descriptive_identification`
  and explains why the retry fired at all. Read the second one when asking **why** a question
  was routed; read the first when asking **how** the answer was built.
- **Three messages**, written by the retry helper BEFORE the stronger model is called:
  `First-pass SQL query (before the stronger-model retry): ...`, `First-pass failure reason
  [<code>]: ...`, and once the rewrite is known, `Stronger model rewrote the question as: '...'
  (original question: '...').` The wording of the pre-existing retry messages is untouched:
  `analyze-complex-retry-logs.py` keys on `SQL query returned 0 rows; attempting to simplify`.
- **A retried question produces TWO log files**, since the outer request is logged too from the
  helper's return: the inner one (`request.complex_question_already_resolved` true, rewritten
  question, no first-pass fields) and the outer one (the user's own wording, merged messages,
  first-pass fields). Anything that counts questions from `logs/` must skip the inner file
  (FASTAPI-TEXT2SQL-246).
- **The execution branch records its own code** in `sql_execution_failure_code` / `_reason`, set
  by the three `except` clauses of the execution block; extend that pair when you add an `except`.

What the "Pour le plaisir" trace taught, and why it is worth reading a first pass: extraction
returned no entity for the bare French phrase, so no ChromaDB resolution ran and no
language-specific expansion (`MOVIE_TITLE_FR` / `ORIGINAL_TITLE`, added by the resolver for
`lang=fr`) was applied. The generated `MOVIE_TITLE = 'Pour le plaisir'` compared the French
title to the English column and found nothing. `_localize_search_rows` then displays the French
title in `MOVIE_TITLE` for a `fr` UI, which hides the mismatch from anyone reading results.

## The no-entity rescue runs before the stronger model (FASTAPI-TEXT2SQL-244)

When extraction returns no entity, the text-to-SQL prompt still writes the user's words as a
literal equality on a canonical column (`MOVIE_TITLE = 'Pour le plaisir'`), and nothing looks at
that literal: `plan_entity_resolutions` iterates over extracted keys, of which there are none,
so no ChromaDB lookup runs and the language-aware OR expansion of `_substitute_entity_row` never
fires. On a French title that means comparing it to the English column, 0 rows, and a trip to
the stronger model, which then adds a year from memory (-243). Since -244, right after the
execution block and before any retry, when page 1 returned 0 rows with `no_entity_extracted`
true and no exact-cache hit:

1. `entity.find_literal_equalities(sql)` lists the literal equalities on resolvable columns.
   The column set is derived from `data/entity_resolution.json`: the `default_field` of each
   resolver's first strategy (`MOVIE_TITLE`, `SERIE_TITLE`, `PERSON_NAME`, ...); a column
   claimed by two prefixes is dropped as ambiguous.
2. `entity.placeholderize_literals` puts each literal back into placeholder form
   (`MOVIE_TITLE = '{{Movie_title1}}'`) and main.py builds the matching synthetic extraction.
3. The ORDINARY resolver runs on it (`plan_entity_resolutions` in a thread, then
   `apply_entity_resolutions`): ChromaDB shortlist, fuzz gate, canonical value, language OR
   expansion, and its messages land in the response like any resolution.
4. If the resolver found nothing better than the raw words (raw fallback, unresolved
   placeholder, or an unchanged SQL), the first-pass SQL stands and the usual retry rules
   apply. Otherwise the rescued SQL is re-executed and **adopted whatever the row count**: it
   replaces `sql_query`, `sql_query_processed_base` and the anonymized copies, so the cache
   holds the language-aware form and a retry reports it as the first pass. With nothing
   extracted, the anonymized question IS the raw question, which is why the anonymized copy
   must follow: otherwise its row would keep serving the equality that just failed.

Zero LLM call. `README.md` lists the `no_entity_rescue_outcome` values. The rescue's candidates
join `entity_match_scores`, and its re-execution time is added to `query_execution_time`. The
rescue is gated on the EMPTY result on purpose: a first pass that returns rows is left alone,
whatever column it compared. Not covered: a raw fallback (the resolver's own thresholds decide),
and a literal that is not an equality (`LIKE`, `IN`).

## The retry never caches a narrowed rewrite under the original question (FASTAPI-TEXT2SQL-242)

After a successful stronger-model retry, the helper writes the retry's SQL to `T_WC_T2S_CACHE`
under the ORIGINAL wording, so the next identical question costs 60 ms instead of seven LLM
calls. That row is legitimate when the rewrite repaired a resolution (`Marion Morrison` ->
`John Wayne`) and poison when it added information: on 2026-09-08 "Pour le plaisir" was
rewritten "Movie Pour le plaisir (2004)" from the model's memory, and the year-filtered SQL
served every following "Pour le plaisir" for two days, hiding the 2026 film. Since -242 the
write is skipped when the rewrite carries a four-digit year absent from the original question,
or (second belt) when the inner extraction produced a `Release_year` / `First_air_year` /
`Birth_year` / `Death_year` placeholder while the original question holds no year. The decision is written to
the messages and to `complex_retry_cache_policy`, whose values `README.md` lists. The rewritten
question stays cached under its own wording by the inner pass, so nothing is lost. Not done:
marking retry-derived rows, which would need a column in `T_WC_T2S_CACHE`.

## An identity retry carries the resolver's type as data (FASTAPI-TEXT2SQL-300)

When the complex step answers with exactly one typed item and an identity card of that type
(`Serie Sherlock`, `Movie Alien (1979)`, `Person John Wayne`), `f_build_identity_retry_seed`
builds the extraction the retry would have needed and `main.py` passes it on
`retry_request.complex_retry_seed`. The inner pass then skips the LLM extraction, skips the
SQL caches (exact, anonymized, embeddings), and expects the item's type as `result_entity`,
with no classifier call. The answer-entity guard regenerates once when the result entity
differs, **even if the id token is in the SELECT**, because the series' images also project
`ID_SERIE`. Why: on 2026-09-24 and -25, eighteen riddles came back as zero rows (`Sherlock`
re-extracted as a character) or as `serie_image` (a bare `Serie {{Serie_title1}}` read as a
picture request, then served from cache). Relation questions (`In which city…`) and lists get
no seed and keep the full pipeline. The field is ignored unless `complex_question_already_resolved`
is true, so a client cannot use it to bypass extraction. A movie keeps its year in parentheses.

## Entity identity boundary

Text2SQL owns relational structure, never the identification of an unnamed real-world entity from remembered clues. `data/entity_extraction.md` classifies each request with `query_mode`; `descriptive_identification` routes to the stronger model before Text2SQL. Text2SQL may also emit `requires_complex_resolution: true`. The two reach `first_pass_failure_code` as distinct values since FASTAPI-TEXT2SQL-271, so a campaign can tell a deliberate routing from an admission of defeat. Independently of both prompts, `entity.find_unbacked_entity_literals()` rejects resolvable entity equalities whose value occurs in neither the original question nor extracted entities. Keep this guard before SQL execution and cache writes. A literal explicitly present in the original question remains grounded even when extraction missed it, which preserves the `Pour le plaisir` rescue path.

**The guard judges SQL generated in the current request, never an exact-question cache hit (FASTAPI-TEXT2SQL-259).** Two facts make it unsatisfiable on that path, and both are properties of the cache rather than accidents: `sql_cache` returns `SQL_PROCESSED`, the already entity-resolved SQL whose literal is the canonical database value, and entity extraction is skipped on a cache hit, so `entity_extraction` is `None`. Left ungated, the guard rejected SQL the pipeline itself had resolved and stored, for every cached question whose title needed any normalization at all: a colon, an accent, a leading article, a French title resolved onto the English column. Grounding also folds case, diacritics and punctuation before comparing, so `2001: A Space Odyssey` matches a user who typed `2001 A space odyssey`; it folds surface form only, never words, so a title recalled from a plot description still shares nothing with the question. The anonymized and embeddings cache paths keep the guard: extraction runs there, and their SQL still carries placeholders, which `find_literal_equalities` skips.

`query_mode` is a soft field (FASTAPI-TEXT2SQL-255): [json_guardrails.py](../json_guardrails.py) validates its value against the closed vocabulary but does not require its presence. A missing mode costs the descriptive routing only, while rejecting the payload discarded a usable extraction and handed Text2SQL the raw, non-anonymized question. The lesson for any prompt-and-guardrail pair: a rule stated once in the spec loses to the shape demonstrated by the examples. When adding a required key to a prompt contract, update every example in that prompt in the same commit, or the model will keep answering in the shape it was shown.

## One clock: Paris time, with its offset (FASTAPI-TEXT2SQL-328)

The stack-wide rule (DEPLOYMENT-015): every date a human reads is **Europe/Paris with its
offset** (`2026-10-19T14:59:03+02:00`), always through the zone, never a fixed `+02:00`.
Naive `DATETIME` values in the database stay naive Paris; the VPS host stays on `Etc/UTC` and
the container sets no `TZ`, which is why the zone is named in `logs.py` (`PARIS_TZ`,
`now_paris()`) and `tzdata` is in `requirements.txt` (the slim image has no zone database).

**Switch date: 2026-10-19 (code), effective at the next deployment.** Before it, log and
upload file names are **UTC with no offset**, and the log JSON carries no timestamp. After it,
names are **Paris time** (same `YYYYMMDD-HHMMSS` shape) and every dict logged by `log_usage`
starts with `"ts"`, the same moment with its offset. Read the `ts` when it is there; the name is
for humans, repeats 02:00 to 03:00 on the last Sunday of October, and on the switch day sorts
new Paris names before older UTC ones for up to two hours.

- `uploads.deposited_at()` and `purge_after()` return **aware** Paris datetimes; compare them
  with `logs.now_paris()`, never with `datetime.now()`, which is naive and raises `TypeError`.
  An upload deposited before the switch reads one or two hours early: harmless on 30 days, and
  `purge-uploads.sh` deletes by modification time anyway.
- The startup banner and the Chroma cache metadata `dat_creat` are Paris ISO with offset.
- Not this repo's clock: `NOW()` in `sql_cache.py` and `vision_cache.py` follows the MariaDB
  server (TMDB-FRONT-100).

## `logs/` and `uploads/` are shared by every colour, with opposite retentions

Both folders are bind-mounted from `shared_data/fastapi-text2sql/` by the two restart scripts:
every deployment writes into one log corpus (FASTAPI-TEXT2SQL-276), and an image deposited on one
colour is readable from the other (FASTAPI-TEXT2SQL-275). That is why `LOGS_FOLDER` and
`UPLOADS_FOLDER` stay relative, see "Where things live" above. The mount lines, the
host-directory ownership trap, the archive merge and the inverse retention table (`logs/` kept
without limit and backed up, `uploads/` purged at 30 days and neither backed up nor mirrored)
are in `README.md`, sections *The second mount*, *The third mount* and *Vision uploads*. Do not
restate them here.

**What this changes for an agent reading the logs.** A path no longer says which colour served
a request; the **version component of the filename** does, and it always did. Anything counting
questions over `logs/` now sees every colour at once, which is what makes a figure like "35
retries out of 505 local logs" a statement about the system rather than about one port.

**Verifying the shared mount.** `checks/verif-275.sh` exercises the upload path against a running
deployment. Its one check that cannot run on a laptop is the cross-colour read that proves the
mount is really shared, `OTHER_BASE_URL=...`.

## `T_WC_T2S_CACHE`

- `T_WC_T2S_CACHE` — keys `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`,
  `JUSTIFICATION`, `ANSWER`, `RESULT_ENTITY`, `API_VERSION` (`XXX.YYY.ZZZ`), `UI_LANGUAGE`,
  `IS_ANONYMIZED`, `DELETED`, plus timing columns. `RESULT_ENTITY` is written and read by
  [sql_cache.py](../sql_cache.py) with **graceful degradation**: when the column is absent
  (pre-migration), reads and writes fall back to the legacy column set and treat it as empty
  rather than failing.
