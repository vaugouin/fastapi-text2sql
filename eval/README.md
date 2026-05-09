# Text2SQL Evaluator

**Version:** 2.5
**Last Updated:** 2026-05-06
**Status:** Production Ready
**Main file:** [text2sql-eval.py](text2sql-eval.py)

End-to-end evaluation harness for the FastAPI Text2SQL service: calls the running `/search/text2sql` endpoint with a curated question bank, stores each JSON response, and scores the responses against three assertion types (entity extraction, SQL regex, result-set DataFrame). All results, scores, and timing metrics are persisted to a MariaDB table for historical analysis and regression tracking.

After scoring, the evaluator also exports the three evaluation tables (`T_WC_T2S_EVALUATION_CATEGORY`, `T_WC_T2S_EVALUATION`, `T_WC_T2S_EVALUATION_EXECUTION`) as one-JSON-per-row files into `/shared/<subfolder>/` so a downstream LLM can analyse the question bank, taxonomy, and execution results without DB access.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Quick Start & CLI](#2-quick-start--cli)
3. [Processes](#3-processes)
4. [Assertion Types](#4-assertion-types)
5. [Entity Extraction DSL](#5-entity-extraction-dsl)
6. [Database Schema](#6-database-schema)
7. [Error Reporting](#7-error-reporting)
8. [Source Files](#8-source-files)
9. [Performance Metrics](#9-performance-metrics)
10. [JSON Exports for LLM Analysis](#10-json-exports-for-llm-analysis)
11. [Interactive Web UI (PHP)](#11-interactive-web-ui-php)
12. [Troubleshooting](#12-troubleshooting)
13. [Version History](#13-version-history)

---

## 1. Architecture

The evaluator is a **single-pass multi-phase pipeline** driven by a numeric process index. Each phase reads from or writes to one of three evaluation tables:

| Table | Role |
|---|---|
| `T_WC_T2S_EVALUATION` | Question bank (EN + FR) + three assertion columns (`ASSERTIONS_ENTITY_EXTRACTION`, `ASSERTIONS_SQL_QUERY`, `ASSERTIONS_QUERY_RESULT`) |
| `T_WC_T2S_EVALUATION_CATEGORY` | Taxonomy (categories of questions) |
| `T_WC_T2S_EVALUATION_EXECUTION` | One row per `(eval_id, api_version, entity_extraction_model, text2sql_model, complex_model, language)` combination — stores the full JSON response, per-assertion scores, aggregated `ASSERTIONS_TOTAL_SCORE`, and timing breakdown |

Phases run in order: **translations → cleanup → run → process → export**. Rerunning the same command is idempotent — the `run` phase skips combinations already present in `T_WC_T2S_EVALUATION_EXECUTION`, and the `export` phases skip files that already exist on disk.

Phase 11 hits the FastAPI server over HTTP. Phase 20 does the scoring offline against the stored `JSON_RESULT`. Phases 30/31/32 dump the three tables to `/shared/<subfolder>/` as one JSON file per row for downstream LLM analysis. This separation means scoring and export can be re-run after an assertion correction without re-spending LLM tokens.

---

## 2. Quick Start & CLI

```bash
# Docker (recommended)
docker run -it --rm --network="host" --name text2sql-eval -v /home/debian/docker/shared_data/text2sql-eval:/shared text2sql-eval-python-app

# Custom parameters
docker run -it --rm --network="host" --name text2sql-eval \
  -v /home/debian/docker/shared_data/text2sql-eval:/shared \
  text2sql-eval-python-app \
  --api-version 1.1.15 \
  --entity-extraction-model gpt-4o \
  --text2sql-model gpt-4o \
  --complex-model gpt-4o \
  --language fr

# Gemma 4 Google run without writing new API cache entries
docker run -it --rm --network="host" --name text2sql-eval \
  -v /home/debian/docker/shared_data/text2sql-eval:/shared \
  text2sql-eval-python-app \
  --api-version 1.1.15 \
  --entity-extraction-model gemma-4-google \
  --text2sql-model gemma-4-google \
  --complex-model gpt-4o \
  --language "*" \
  --no-store-to-cache \
  --no-complex-model-used

# Launch via helper script (builds image, runs detached)
./text2sql-eval.sh
```

All CLI arguments are optional; defaults are chosen so `docker run` without arguments reproduces the previous hardcoded configuration.

The `/shared` mount is now **read-write**. Phases 30/31/32 write JSON exports there into three subfolders — `evaluation_category/`, `evaluation/`, `evaluation_execution/` — see [§10 JSON Exports for LLM Analysis](#10-json-exports-for-llm-analysis). The base directory can be overridden with the env var `TEXT2SQL_EVAL_EXPORT_DIR` (default `/shared`).

| Argument | Default | Description |
|---|---|---|
| `--entity-extraction-model` | `gpt-4o` | LLM model for entity extraction (matches API `llm_model_entity_extraction`) |
| `--text2sql-model` | `gpt-4o` | LLM model for text-to-SQL generation |
| `--complex-model` | `gpt-4o` | LLM model for complex-question processing / stronger-model retry |
| `--api-version` | `1.1.14` | API version expected in the response; execution aborts on mismatch |
| `--language` | `*` | Language filter: `en`, `fr`, or `*` for both |
| `--store-to-cache` | `true` | Store evaluation API results in the FastAPI cache |
| `--no-store-to-cache` | `false` | Disable cache writes for the evaluation run |
| `--complex-model-used` | `false` | Send `complex_model_used=true` in the API input |
| `--no-complex-model-used` | `false` | Send `complex_model_used=false` in the API input |

### Required environment variables

The evaluator is configured via `.env` / container env vars:

```bash
# MariaDB (via citizenphil helpers)
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# Target FastAPI server
TEXT2SQL_API_URL=http://localhost            # scheme + host only; port is auto-selected
API_PORT_BLUE=8000
API_PORT_GREEN=8001
TEXT2SQL_API_KEY=<X-API-Key value>

# Evaluator pacing / retry for LLM quota errors
TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS=2
TEXT2SQL_EVAL_API_429_MAX_RETRIES=6
TEXT2SQL_EVAL_API_429_FALLBACK_DELAY_SECONDS=30
TEXT2SQL_EVAL_API_429_BUFFER_SECONDS=3

# Translations (phases 4/5/6)
OPENAI_API_KEY=sk-...
```

The evaluator computes the API port from the patch parity of `--api-version` (even → Blue, odd → Green), matching the Blue/Green deployment convention of the API itself.

`--store-to-cache` / `--no-store-to-cache` control the API payload field `store_to_cache`. The default is to keep the previous behavior and write successful responses to the API cache. Use `--no-store-to-cache` when you want a clean evaluator run that does not populate the cache, for example while testing direct Google Gemma 4 quota behavior.

`--complex-model-used` / `--no-complex-model-used` control the API payload field `complex_model_used`. The default is `false`. This is useful when you want the evaluator to explicitly simulate requests that already come from a stronger-model path or to keep that signal disabled during normal baseline runs.

The evaluator also supports built-in pacing and retry for retryable provider quota / rate-limit failures. It waits `TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS` before each API call, then retries the same `(question, language)` pair when the API or provider indicates a retryable `429` / `RESOURCE_EXHAUSTED` condition. If the API returns a structured `retry_after_seconds` hint, the evaluator uses that delay plus a small safety buffer; otherwise it falls back to `TEXT2SQL_EVAL_API_429_FALLBACK_DELAY_SECONDS`. Once `TEXT2SQL_EVAL_API_429_MAX_RETRIES` is exhausted, the evaluator stops the run instead of silently skipping the failed case.

For retryable quota / rate-limit failures, the FastAPI endpoint is intentionally **not** the owner of wait-and-retry behavior. The API now returns the structured retryable error metadata directly and skips the internal stronger-model fallback for that specific error class, so the evaluator remains the single place that decides when to pause and retry.

---

## 3. Processes

Phases are defined by `arrprocessscope` at [text2sql-eval.py:107](text2sql-eval.py#L107). Every phase reports progress via [citizenphil](citizenphil.py) server variables (`strtext2sqlevalcurrentprocess`, `strtext2sqlevalprocessesexecuted`, etc.) so long-running runs can be monitored externally.

### Phase 4 — Translate categories EN→FR
- Reads `T_WC_T2S_EVALUATION_CATEGORY` rows where `DESCRIPTION` is set and `DESCRIPTION_FR` is empty
- Calls OpenAI gpt-4o (`translate_question_to_french`) to populate `DESCRIPTION_FR`

### Phase 5 — Translate questions EN→FR
- Reads `T_WC_T2S_EVALUATION` rows with `QUESTION` set and `QUESTION_FR` empty
- Populates `QUESTION_FR` via gpt-4o

### Phase 6 — Translate questions FR→EN
- Reverse direction: fills `QUESTION` when only `QUESTION_FR` exists

### Phase 10 — Cleanup soft-deleted executions
- `DELETE FROM T_WC_T2S_EVALUATION_EXECUTION WHERE DELETED = 1`

### Phase 11 — Run evaluations against the FastAPI server
- Selects questions where `IS_EVAL = 1` and at least one assertion column is non-empty
- **Skips combinations already executed** for this `(api_version, entity_extraction_model, text2sql_model, complex_model, language)` tuple (no wasted API calls)
- **One API call per `(question, language)` pair**: each call sends `ui_language` matching the question language (`"en"` for `QUESTION`, `"fr"` for `QUESTION_FR`). Even if `QUESTION == QUESTION_FR`, the API is called twice because the `answer` field in the response depends on `ui_language`
- Uses the optional server variable `strtext2sqlevalrunevalid` to resume from a specific ID
- Posts to `POST {TEXT2SQL_API_URL}/search/text2sql` with `complex_question_processing=True`, `retrieve_from_cache=False`, `store_to_cache=<CLI flag>`, `complex_model_used=<CLI flag>`, `rows_per_page=100`, `ui_language=<lang>`
- Waits `TEXT2SQL_EVAL_API_CALL_DELAY_SECONDS` before each API call to reduce the risk of upstream provider throttling
- Retries retryable LLM quota / rate-limit failures (`HTTP 429`, API `error_code=429`, provider strings such as `RESOURCE_EXHAUSTED`) for the same evaluation case instead of immediately failing it
- Uses provider retry hints when available (`retry_after_seconds`, `Retry-After`, or provider error text such as `Please retry in 27s`), otherwise falls back to `TEXT2SQL_EVAL_API_429_FALLBACK_DELAY_SECONDS`
- Logs retry diagnostics for retryable responses, including HTTP status, structured retry metadata, and the provider error text
- Retryable quota / rate-limit failures do **not** trigger the API's internal stronger-model fallback; they are returned as structured retryable responses so the evaluator can own the wait-and-retry loop
- Aborts the full evaluation run with a clear error once `TEXT2SQL_EVAL_API_429_MAX_RETRIES` is exhausted for a case
- **Configuration guard**: if `api_version` / `llm_model_*` in the response do not match the CLI args, the script exits immediately to avoid burning tokens with a misconfigured server
- Persists the full JSON response (including `answer`, `answer_anonymized`, `ui_language`) as `JSON_RESULT` in `T_WC_T2S_EVALUATION_EXECUTION`
- No per-run cap on number of evaluations. The previous `LIMIT 10` safety throttle at [text2sql-eval.py:287](text2sql-eval.py#L287) is commented out — every eligible row from the question bank is processed in a single pass. Re-enable it if you want a quick smoke test instead of a full run.

### Phase 20 — Score stored executions
For every `JSON_RESULT` in `T_WC_T2S_EVALUATION_EXECUTION` matching the CLI filters, the evaluator:
1. Parses the JSON via `t2s_eval.safe_json_loads()`
2. Builds a pandas DataFrame from `response_json["result"]` (each row is `{"index": int, "data": dict}`)
3. Runs the three assertion evaluations (see §4) and computes per-assertion scores
4. Aggregates `ASSERTIONS_TOTAL_SCORE = 1` iff every non-null per-assertion score is `1`
5. Writes scores + `ASSERTIONS_RESULT_DETAILED` (human-readable multi-line trace) back to the execution row
6. Accumulates pipeline timings to print a run summary

Phase 20 is pure offline scoring — re-runnable after assertion corrections without hitting the API.

### Phase 30 — Export evaluation categories to JSON
- Reads `T_WC_T2S_EVALUATION_CATEGORY` (full taxonomy, CLI-agnostic — every non-deleted row)
- Writes one file per category to `/shared/evaluation_category/<evalcatid>_<englishDescriptionSlug>.json`
- **Skips files that already exist** (idempotent on re-run)
- See [§10 JSON Exports for LLM Analysis](#10-json-exports-for-llm-analysis) for the file schema

### Phase 31 — Export evaluations to JSON
- Reads `T_WC_T2S_EVALUATION` (full question bank, CLI-agnostic — every non-deleted row)
- Writes one file per evaluation to `/shared/evaluation/<evalid>_<evalcatid>_<englishDescriptionSlug>.json`
- Each file embeds the EN + FR question pair, the three assertion strings, the originating category ID, and the `LONG_DESC` "why this evaluation was created" comment
- **Skips files that already exist**

### Phase 32 — Export evaluation executions to JSON
- Reads `T_WC_T2S_EVALUATION_EXECUTION` **filtered by the same CLI tuple as Phase 20** (`--api-version`, `--entity-extraction-model`, `--text2sql-model`, `--complex-model`, `--language`)
- Writes one file per execution row to `/shared/evaluation_execution/<run-subfolder>/<YYYYMMDD>_<evalid>_<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>.json`
  - **Run subfolder** = `<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>` (e.g. `001.001.015_en_gpt-4o_gpt-4o_gpt-4o/`). Created on first write; one subfolder per run signature so successive evaluations across versions / models / languages stay separated and the parent `evaluation_execution/` directory does not accumulate thousands of mixed files.
  - Example: `001.001.015_en_gpt-4o_gpt-4o_gpt-4o/20260425_42_001.001.015_en_gpt-4o_gpt-4o_gpt-4o.json`
  - `YYYYMMDD` is taken from `TIM_EXECUTION` (falls back to `DAT_CREAT`, then today)
  - `evalid` is `ID_T2S_EVALUATION` (added on top of the original spec to disambiguate same-day runs)
- Each file embeds the parsed `JSON_RESULT` (full API response, including `messages`, `entity_extraction`, `sql_query`, `result`, `answer`), the per-assertion scores, the detailed scoring trace, and the timing breakdown
- **Skips files that already exist**

---

## 4. Assertion Types

Three assertion columns on `T_WC_T2S_EVALUATION`. Each is optional; omitting one stores `NULL` for that score and excludes it from `ASSERTIONS_TOTAL_SCORE`. HTML-escaped operators (`&gt;`, `&lt;`) are accepted — values are passed through `html.unescape()` before parsing.

### 4.1 `ASSERTIONS_ENTITY_EXTRACTION` — Two-Layer EE DSL
Validates the `entity_extraction` dict returned by the API. Score column: `ASSERTIONS_ENTITY_EXTRACTION_SCORE` (0/1, or `NULL` when the response has no `entity_extraction`).

**Layer 1 (hard gate, automatic):**
- `entity_extraction["question"]` must be a non-empty string
- Placeholders inside the anonymized question (e.g. `{{Movie_title1}}`) must match the set of entity keys exactly (order-insensitive), excluding `"question"`
- Every entity value must be a non-empty string

**Layer 2 (gold-value expression DSL):** evaluated by `ee_eval_two_layer()` in [entity_extraction_eval_functions.py](entity_extraction_eval_functions.py). Fail-closed: any parsing/eval error returns `0`.

Supported:
- Boolean operators: `AND`, `OR`, `NOT`, parentheses
- Functions: `eq(a, b)`, `nonempty(x)`, `seteq(listA, listB)`, `placeholders($.question)`, `entity_keys($)`, `keys($)`, `matches(x, /regex/flags)` (flags: `i`, `m`, `s`)
- Root key access: `$.<Key>`

Examples:
```
eq($.question, "What are the highest-grossing movies of all time?") AND seteq(entity_keys($), [])

(eq($.question, "{{Movie_title1}} ({{Release_year1}})") AND eq($.Movie_title1, "Tommy") AND eq($.Release_year1, "1975"))

(matches($.question, /^best .+ movies$/i) AND eq($.Person_name1, "Martin Scorsese"))
```

> Wrap multi-line expressions in parentheses — bare newlines can break the DSL parser.

### 4.2 `ASSERTIONS_SQL_QUERY` — SQL regex
A plain Python regex matched against `response_json["sql_query"]` via `re.search()`. Score column: `ASSERTIONS_SQL_QUERY_SCORE` (0/1, or `NULL` when absent).

Examples:
```regex
SELECT\s+.*FROM\s+T_WC_T2S_MOVIE
JOIN\s+T_WC_T2S_PERSON_MOVIE
ORDER\s+BY\s+IMDB_RATING_WEIGHTED\s+DESC
```

Common failure modes reported in the detailed trace:
- `sql_query` empty (ambiguous question / Text2SQL error)
- Regex error (`re.error`)

### 4.3 `ASSERTIONS_QUERY_RESULT` — DataFrame assertion DSL
Validates the result set via `t2s_eval.evaluate_dataframe_assertions()` in [text2sql_eval_functions.py](text2sql_eval_functions.py). Score column: `ASSERTIONS_RESULT_SCORE` (0/1).

Supported forms (combinable with `AND` / `OR` and parentheses):

| Form | Semantics |
|---|---|
| `COUNT(*) <op> <n>` | Row count comparison (`==`, `!=`, `<`, `>`, `<=`, `>=`) |
| `COUNT(<col>) <op> <n>` | Unique non-null value count for a column |
| `CELL(<row>, <col>) <op> <value>` | Single-cell check, 0-indexed positions; values may be int, float, or quoted string |
| `<col> IN (<v1>, <v2>, …)` | All listed values must be present (extra values in the DataFrame are OK) |
| `<col> NOT IN (<v1>, …)` | None of the listed values may appear |
| `<col> <op> <value>` | Every row must satisfy the comparison |

Examples:
```
COUNT(*) == 5
COUNT(ID_MOVIE) >= 3
CELL(0, 0) == 'GoodFellas'
ID_MOVIE IN (910, 22584, 11016)
ID_MOVIE NOT IN (289, 3090)
IMDB_RATING >= 7.0
(COUNT(*) == 5 OR COUNT(*) == 6) AND ID_MOVIE IN (910, 22584) AND RATING >= 7.0
```

Behaviour on an empty DataFrame: passes iff the assertion is exactly `COUNT(*) == 0`; otherwise fails.

#### Unified-schema column bridge

The Text2SQL prompt emits a unified result shape for movie / serie (and occasionally person) queries: `T_WC_T2S_MOVIE.ID_MOVIE AS ID_CONTENT, 'movie' AS CONTENT_TYPE, …`. Legacy assertions written against the per-table column names (`ID_MOVIE IN (...)`, `ID_SERIE IN (...)`, `ID_PERSON IN (...)`) keep working because `evaluate_dataframe_assertions()` synthesizes virtual columns at the top of the function whenever both `ID_CONTENT` and `CONTENT_TYPE` are present in the DataFrame:

| Virtual column | Source rows |
|---|---|
| `ID_MOVIE` | `ID_CONTENT` where `CONTENT_TYPE` (case-insensitive) is `movie`, NaN elsewhere |
| `ID_SERIE` | `ID_CONTENT` where `CONTENT_TYPE` is `serie`, NaN elsewhere |
| `ID_PERSON` | `ID_CONTENT` where `CONTENT_TYPE` is `person`, NaN elsewhere |

Behavioural notes:
- Existing columns are never overwritten — if the DataFrame already carries an `ID_MOVIE` column, the bridge is a no-op for that column.
- Non-matching rows become NaN, which `IN` / `NOT IN` evaluators treat as not-in-list, so a mixed movie+serie result correctly satisfies `ID_MOVIE IN (...)` for only the movie rows.
- When `CONTENT_TYPE` is absent (or `ID_CONTENT` is absent), the bridge does not fire and column resolution falls back to the strict exact-match path — `ID_MOVIE IN (...)` against a DataFrame without `ID_MOVIE` fails with the usual `Column 'ID_MOVIE' does not exist in DataFrame` message.

Regression coverage: [test-unified-schema-bridge.py](test-unified-schema-bridge.py) (movies-only, mixed movies+series, ID_PERSON, mixed-case `Movie`, no-op when `ID_MOVIE` already exists, no-op when `CONTENT_TYPE` is absent, `NOT IN` semantics).

### 4.4 Aggregated score
`ASSERTIONS_TOTAL_SCORE = 1` iff **all non-null** component scores are `1`. If only one assertion is provided, `TOTAL_SCORE` reflects just that one. If none are provided, it stays `NULL`.

---

## 5. Entity Extraction DSL — Reference

Implemented in [entity_extraction_eval_functions.py](entity_extraction_eval_functions.py) (`ee_eval_two_layer`, helpers `_placeholders`, `_entity_keys`, `_keys_root`, `_nonempty`, `_eval_layer2`).

### Layer 1 gate — what it enforces
1. `question` key is a non-empty string
2. `sorted(placeholders(question)) == sorted(entity_keys(ee))`
3. Every entity value is a non-empty string

If any Layer 1 check fails, `ee_eval_two_layer` returns `False` immediately; Layer 2 is not evaluated.

### Layer 2 expression grammar
- Literals: `"..."` (double-quoted string), `[...]` (list literal for `seteq`)
- Root access: `$` refers to the entire `entity_extraction` dict; `$.<Key>` dereferences a top-level key
- Functions return booleans or values used by outer boolean operators
- `matches(x, /regex/flags)` — the regex delimiters are literal slashes; trailing flags supported: `i`, `m`, `s`

**Fail-closed** — any exception during parsing or evaluation produces a `0`, never a `1`.

---

## 6. Database Schema

### `T_WC_T2S_EVALUATION` (question bank)
Key columns:
- `ID_T2S_EVALUATION` (PK)
- `QUESTION`, `QUESTION_FR` — dual-language source text
- `ID_T2S_EVALUATION_CATEGORY` — taxonomy FK
- `IS_EVAL`, `IS_SAMPLE`, `DELETED`, `DISPLAY_ORDER`
- `ASSERTIONS_QUERY_RESULT`, `ASSERTIONS_ENTITY_EXTRACTION`, `ASSERTIONS_SQL_QUERY` — the three assertion strings
- Metadata: `LONG_DESC`, `MOT_CLE`, `MOT_CLE_AUTO`, `DAT_CREAT`, `TIM_UPDATED`

### `T_WC_T2S_EVALUATION_CATEGORY` (taxonomy)
`ID_T2S_EVALUATION_CATEGORY`, `DESCRIPTION`, `DESCRIPTION_FR`, `ID_PARENT`, `LANG`, soft-delete / audit columns.

### `T_WC_T2S_EVALUATION_EXECUTION` (results)
One row per execution. Key columns:
- `ID_ROW` (PK)
- `ID_T2S_EVALUATION` (FK to question)
- `LANG` — `en` or `fr`
- `API_VERSION` — stored in `XXX.YYY.ZZZ` form (via `t2s_eval.format_api_version()`)
- `ENTITY_EXTRACTION_MODEL`, `TEXT2SQL_MODEL`, `COMPLEX_MODEL` — the tuple that disambiguates executions
- `JSON_RESULT` — full API response (mediumtext)
- Timings: `ENTITY_EXTRACTION_PROCESSING_TIME`, `TEXT2SQL_PROCESSING_TIME`, `EMBEDDINGS_PROCESSING_TIME`, `QUERY_EXECUTION_TIME`, `TOTAL_PROCESSING_TIME`
- Scores: `ASSERTIONS_ENTITY_EXTRACTION_SCORE`, `ASSERTIONS_SQL_QUERY_SCORE`, `ASSERTIONS_RESULT_SCORE`, `ASSERTIONS_TOTAL_SCORE`
- Detail trace: `ASSERTIONS_RESULT_DETAILED` (human-readable)
- Costs (reserved): `ENTITY_EXTRACTION_COST`, `TEXT2SQL_COST`, `TOTAL_COST`
- Audit: `DELETED`, `DAT_CREAT`, `TIM_UPDATED`, `TIM_EXECUTION`

Schema DDL lives at [T2S_EVALUATION-tables.sql](T2S_EVALUATION-tables.sql) and [T2S_EVALUATION-tables-with-data.sql](T2S_EVALUATION-tables-with-data.sql).

### Common queries

```sql
-- All failures for the current run
SELECT ID_ROW, ID_T2S_EVALUATION, LANG, ASSERTIONS_RESULT_DETAILED
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0
  AND API_VERSION = '001.001.015'
  AND ASSERTIONS_TOTAL_SCORE = 0;

-- Score rollup by model
SELECT TEXT2SQL_MODEL,
       SUM(ASSERTIONS_TOTAL_SCORE) / COUNT(*) AS pass_rate,
       COUNT(*) AS n
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0 AND API_VERSION = '001.001.015'
GROUP BY TEXT2SQL_MODEL;

-- Entity extraction regressions only
SELECT ID_ROW, ID_T2S_EVALUATION
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE ASSERTIONS_ENTITY_EXTRACTION_SCORE = 0;

-- Specific error patterns
SELECT ID_ROW FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE ASSERTIONS_RESULT_DETAILED LIKE '%Missing%required value%';
```

---

## 7. Error Reporting

### 7.1 Console output (Phase 20)

```
========================================
Evaluation Result: FAIL ✗
========================================

Assertions on result set: (COUNT(*) == 5 OR COUNT(*) == 6) AND
ID_MOVIE IN (488, 10178, 5996, 34689, 63618, 42880) AND
ID_MOVIE NOT IN (289, 3090, 11016, 910, 963, 27725)
DataFrame shape: 4 rows, 5 columns

========================================
Detailed Results:
========================================

Assertion #1: ✓ PASS
  Statement: COUNT(*) == 5
  Message: Row count check passed

Assertion #2: ✓ PASS
  Statement: ID_MOVIE IN (488, 10178, 5996, 34689, 63618, 42880)
  Message: All 4 values in 'ID_MOVIE' are in the required list

Assertion #3: ✗ FAIL
  Statement: ID_MOVIE NOT IN (289, 3090, 11016, 910, 963, 27725)
  Message: Found 1 value(s) in 'ID_MOVIE' that should NOT be in the list: 289
  Expected: ID_MOVIE NOT IN (289, 3090, 11016, 910, 963, 27725)
  Actual: Found violations: 289 (occurred 1 time(s))

========================================

ASSERTIONS_SQL_QUERY: PASS
Regex: ORDER\s+BY\s+IMDB_RATING_WEIGHTED
SQL query: SELECT ... ORDER BY IMDB_RATING_WEIGHTED DESC LIMIT 100

ASSERTIONS_ENTITY_EXTRACTION: PASS
```

### 7.2 Typical failure messages

| Cause | Message |
|---|---|
| Count mismatch | `Row count mismatch: Expected == 5, but got 3` |
| Missing IN values | `Missing 1 required value(s) in 'ID_MOVIE': 11016` |
| Forbidden NOT IN values | `Found 1 value(s) in 'ID_MOVIE' that should NOT be in the list: 289` |
| Comparison violation | `Found 2 value(s) in 'IMDB_RATING' that violate IMDB_RATING >= 7.0` |
| Unknown column | `Column 'NONEXISTENT_COL' does not exist in DataFrame` |
| SQL regex without sql_query | `Reason: sql_query is missing or empty in JSON_RESULT` |
| EE without entity_extraction | `ASSERTIONS_ENTITY_EXTRACTION: SKIPPED — entity_extraction dict is missing or empty in JSON_RESULT` |

---

## 8. Source Files

| File | Purpose |
|---|---|
| [text2sql-eval.py](text2sql-eval.py) | Main runner — phase dispatch, API calls, DB I/O, scoring loop |
| [text2sql_eval_functions.py](text2sql_eval_functions.py) | `evaluate_dataframe_assertions()`, `_evaluate_*_assertion()` helpers, `format_detailed_results_for_db()`, `safe_json_loads()`, `format_api_version()` |
| [entity_extraction_eval_functions.py](entity_extraction_eval_functions.py) | `ee_eval_two_layer()` + DSL helpers (`_placeholders`, `_entity_keys`, `_eval_layer2`, …) |
| [citizenphil.py](citizenphil.py) | Shared DB / server-variable / SQL-update helpers (`f_getconnection`, `f_getservervariable`, `f_setservervariable`, `f_sqlupdatearray`, `convert_seconds_to_duration`, `paris_tz`) |
| [test-cell-condition.py](test-cell-condition.py) | Standalone sanity check for `CELL()` assertions |
| [test-unified-schema-bridge.py](test-unified-schema-bridge.py) | Standalone regression test for the unified-schema column bridge (`ID_CONTENT` + `CONTENT_TYPE` → virtual `ID_MOVIE` / `ID_SERIE` / `ID_PERSON`); see [§4.3 Unified-schema column bridge](#unified-schema-column-bridge) |
| [Dockerfile](Dockerfile) | `python:3.11-slim` base; installs `requirements.txt`; entrypoint `python ./text2sql-eval.py` |
| [text2sql-eval.sh](text2sql-eval.sh) | Build image + run container (detached, host network) |
| [requirements.txt](requirements.txt) | `requests`, `pymysql`, `pandas>=1.5`, `numpy>=1.21`, `pytest>=7`, `pytz`, `python-dotenv>=1`, `openai>=1` |
| [T2S_EVALUATION-tables.sql](T2S_EVALUATION-tables.sql) | DDL for the three evaluation tables |
| [T2S_EVALUATION-tables-with-data.sql](T2S_EVALUATION-tables-with-data.sql) | DDL + seed question bank |
| [how-many-samples-evals-by-category.ipynb](how-many-samples-evals-by-category.ipynb) | Coverage-by-category reporting notebook — reads the Phase 30/31 JSON exports under [data/evaluation_category/](data/evaluation_category/) and [data/evaluation/](data/evaluation/), aggregates `is_sample` / `is_eval` per category, and saves a dated horizontal bar chart `how-many-samples-evals-by-category-<YYYYMMDD>.png`. Figure height auto-scales with the number of categories. |
| [how-many-samples-evals-by-category.sql](how-many-samples-evals-by-category.sql) | Equivalent direct-DB query (legacy CSV source, kept for reference) |
| [lib/](lib/) | PHP scripts that read the evaluation tables and render interactive graphs / drill-downs in a browser — see [§11 Interactive Web UI (PHP)](#11-interactive-web-ui-php) |
| [data/](data/) | Ancillary fixtures / export dumps |

---

## 9. Performance Metrics

At the end of Phase 20 the evaluator prints the run summary:

```
FastAPI Text2SQL API version: 1.1.15
Entity extraction model: gpt-4o
Text2SQL model: gpt-4o
Complex model: gpt-4o
Language: *
Global score: 87/120 = 72.50%

Sum entity_extraction_processing_time: 42.131s (00:00:42) (n=120)
Avg entity_extraction_processing_time: 0.351s (n=120)
Sum text2sql_processing_time: 185.904s (00:03:05) (n=120)
Avg text2sql_processing_time: 1.549s (n=120)
Sum embeddings_processing_time: 12.020s (00:00:12) (n=120)
Avg embeddings_processing_time: 0.100s (n=120)
Sum query_execution_time: 6.711s (00:00:06) (n=120)
Avg query_execution_time: 0.056s (n=120)
Sum total_processing_time: 248.422s (00:04:08) (n=120)
Avg total_processing_time: 2.070s (n=120)

Total runtime: 312 seconds (00:05:12)
```

Timings are read from the API response and stored per execution row — you can SQL-aggregate them any way you like.

### Assertion evaluation complexity
| Operation | Complexity | Notes |
|---|---|---|
| `COUNT(*)` | O(1) | `len(df)` |
| `COUNT(column)` | O(n) | `df[col].dropna().nunique()` |
| `CELL(r, c)` | O(1) | `df.iloc[r, c]` |
| `IN` / `NOT IN` | O(n) | Column scan |
| Comparison | O(n) | Column scan |
| Multiple assertions | O(n × m) | n rows, m assertions |
| EE Layer 1+2 | O(p + k + e) | p = placeholders, k = keys, e = expression size |
| SQL regex | O(|sql_query|) | Standard `re.search()` |

---

## 10. JSON Exports for LLM Analysis

Phases 30, 31, and 32 dump the three evaluation tables to `/shared/<subfolder>/` as one JSON file per row. The intended consumer is an LLM that performs **global analysis of the evaluator's output** (regression triage, failure-pattern clustering, prompt-quality reasoning, etc.) without needing direct DB access.

### Layout

```
/shared/
├── evaluation_category/
│   └── <evalcatid>_<englishDescriptionSlug>.json
├── evaluation/
│   └── <evalid>_<evalcatid>_<englishDescriptionSlug>.json
└── evaluation_execution/
    └── <api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>/   # one subfolder per run signature
        └── <YYYYMMDD>_<evalid>_<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>.json
```

For example, an evaluator run with `--api-version 1.1.14 --language en --entity-extraction-model gpt-4o --text2sql-model gpt-4o --complex-model gpt-4o` writes its execution JSON files into `/shared/evaluation_execution/001.001.014_en_gpt-4o_gpt-4o_gpt-4o/`, while the same run with `--language fr` writes into `/shared/evaluation_execution/001.001.014_fr_gpt-4o_gpt-4o_gpt-4o/`. This isolates each combination of API version, language, and model triple so the parent folder remains navigable as more runs accumulate.

The base path is `/shared` by default; override with `TEXT2SQL_EVAL_EXPORT_DIR`.

### Filename slug rule

`englishDescriptionSlug` is derived from the English `DESCRIPTION` (categories) or `QUESTION` (evaluations). The slug rule:

1. Unicode NFKD normalize and strip combining marks (`é` → `e`, `ñ` → `n`)
2. ASCII-encode (drops anything still non-ASCII)
3. Lowercase
4. Replace any run of non-`[a-z0-9]` characters with a single `-`
5. Trim leading/trailing `-`
6. Truncate to 60 characters

Empty/missing inputs produce the literal slug `untitled`. For execution filenames, model names go through the same slug rule with a 40-char cap.

### File schemas

#### `evaluation_category/<evalcatid>_<slug>.json`
```json
{
  "evaluation_category_id": 12,
  "description": "Person disambiguation by year",
  "description_fr": "Désambiguïsation des personnes par année",
  "lang": "en",
  "id_parent": 3,
  "comment": "Created to cover the case where two persons share the same name and we need the year suffix to pick the right one.",
  "keywords": null,
  "keywords_auto": null,
  "display_order": 12,
  "dat_creat": "2026-02-01",
  "tim_updated": "2026-04-21T10:23:45"
}
```
The `comment` field is sourced from `LONG_DESC` and is the "why this category was created" explanation.

#### `evaluation/<evalid>_<evalcatid>_<slug>.json`
```json
{
  "evaluation_id": 487,
  "evaluation_category_id": 12,
  "question_en": "Who directed Tommy (1975)?",
  "question_fr": "Qui a réalisé Tommy (1975) ?",
  "translation_note": "Each evaluation carries an English (`question_en`) and a French (`question_fr`) form. One side is the original input typed by the user; the other is automatically translated by gpt-4o through Phase 5 (EN→FR) or Phase 6 (FR→EN) of the evaluator. Translations are generally high-quality but may differ in wording from a natively-typed equivalent — keep this in mind when comparing API outputs across languages.",
  "assertions": {
    "entity_extraction": "(eq($.question, \"{{Movie_title1}} ({{Release_year1}})\") AND eq($.Movie_title1, \"Tommy\") AND eq($.Release_year1, \"1975\"))",
    "sql_query": "JOIN\\s+T_WC_T2S_PERSON_MOVIE",
    "query_result": "COUNT(*) == 1 AND CELL(0, 0) == 'Ken Russell'"
  },
  "comment": "Misspelling regression: original 'Tommi (1975)' was returning the wrong row before v1.1.10.",
  "keywords": null,
  "keywords_auto": null,
  "is_eval": 1,
  "is_sample": 0,
  "display_order": 487,
  "dat_creat": "2026-02-01",
  "tim_updated": "2026-04-21T10:23:45"
}
```
Use `comment` to capture the *reason* the evaluation was added — misspelling, API evolution, new data, known bug, education sample, entity-extraction edge case, etc.

#### `evaluation_execution/<date>_<evalid>_<version>_<lang>_<...>.json`
```json
{
  "evaluation_id": 487,
  "execution_row_id": 9821,
  "language": "en",
  "api_input": {
    "api_version": "001.001.015",
    "entity_extraction_model": "gpt-4o",
    "text2sql_model": "gpt-4o",
    "complex_model": "gpt-4o",
    "ui_language": "en"
  },
  "api_output": {
    "question": "Who directed Tommy (1975)?",
    "question_anonymized": "Who directed {{Movie_title1}} ({{Release_year1}})?",
    "entity_extraction": { "question": "Who directed {{Movie_title1}} ({{Release_year1}})?", "Movie_title1": "Tommy", "Release_year1": "1975" },
    "sql_query": "SELECT ...",
    "answer": "Tommy (1975) was directed by Ken Russell.",
    "result": [ { "index": 0, "data": { "PERSON_NAME": "Ken Russell" } } ],
    "messages": [ { "position": 0, "text": "..." }, { "position": 1, "text": "..." } ],
    "...": "all other Text2SQLResponse fields are present"
  },
  "scoring": {
    "assertions_entity_extraction_score": 1,
    "assertions_sql_query_score": 1,
    "assertions_result_score": 1,
    "assertions_total_score": 1,
    "assertions_result_detailed": "OVERALL: PASS\nAssertion #1: ✓ PASS\n  Statement: COUNT(*) == 1\n  ..."
  },
  "timings": {
    "entity_extraction_processing_time": 0.342,
    "text2sql_processing_time": 1.512,
    "embeddings_processing_time": 0.097,
    "query_execution_time": 0.041,
    "total_processing_time": 2.001
  },
  "tim_execution": "2026-04-25T10:23:45",
  "tim_updated": "2026-04-25T10:23:50"
}
```

The full `api_output` is the parsed `JSON_RESULT` from the DB — it echoes every API input plus the `messages` collection, so an LLM analysing the file can spot **when the complex-question retry path was taken** (typically a sign of trouble in the regular workflow). The `scoring` block tells the LLM whether the run passed or failed and gives the human-readable trace produced by Phase 20.

### Idempotence

All three export phases **skip files that already exist on disk**. To force a re-export of a single execution row, delete the corresponding JSON file under its run subfolder in `/shared/evaluation_execution/<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>/` and re-run.

### Per-phase summary line

At the end of each export phase, the runner prints a one-line summary:

```
Export summary (process 32): wrote=37, skipped=58, errors=0
```

### Downstream consumers

[how-many-samples-evals-by-category.ipynb](how-many-samples-evals-by-category.ipynb) is the canonical local consumer of the Phase 30/31 exports. It walks [data/evaluation_category/](data/evaluation_category/) and [data/evaluation/](data/evaluation/), keeps leaf categories (`id_parent == 1`), aggregates `is_sample` / `is_eval` per `evaluation_category_id`, computes per-category share-of-total weights, and saves a dated horizontal bar chart (`how-many-samples-evals-by-category-<YYYYMMDD>.png`) with the figure height auto-scaling to the category count. Re-run the notebook after any new Phase 30/31 export to refresh coverage statistics without touching the DB.

---

## 11. Interactive Web UI (PHP)

The [lib/](lib/) folder ships a small PHP application that reads the same three evaluation tables as the Python evaluator (`T_WC_T2S_EVALUATION_CATEGORY`, `T_WC_T2S_EVALUATION`, `T_WC_T2S_EVALUATION_EXECUTION`) and renders **interactive comparison graphs and drill-down views** in a browser. It complements the Python harness — same DB, different consumer — and is the easiest way to compare runs across API versions, languages, and model triples without writing SQL by hand.

### Source files

| File | Role |
|---|---|
| [lib/global-light.inc.php](lib/global-light.inc.php) | Shared bootstrap. Provides a Composer-free `.env` loader (`env_load`, `env`), exposes DB credentials (`$dbhost`, `$dbname`, `$dbuser`, `$dbpwd`), the allowed-model lists (`$arrallowedmodels`, `$arrallowedcomplexmodels`) used by the layer dropdowns, and shared helpers. Must be `include`d first by every other script in this folder. |
| [lib/t2sevalexecgraph.inc.php](lib/t2sevalexecgraph.inc.php) | **Multi-layer comparison graph** (entry point). Categories on the X axis; the Y axis is selectable from `avg_ee_score`, `avg_sql_score`, `avg_result_score`, `avg_total_score`, `avg_total_time`, `avg_total_cost`, `avg_ee_cost`, `avg_t2s_cost`, `avg_ee_time`, `avg_t2s_time`, `avg_embed_time`, `avg_query_time`. Each *layer* is a `(lang, api_version, entity_extraction_model, text2sql_model, complex_model, color, name)` tuple stored in `$_SESSION['t2s_layers']` and added/removed/recolored via POST actions (`add_layer`, `remove_layer`, `update_layer_color`, `reset_layers`). Optional filters: `only_eval=1` (`IS_EVAL=1` rows only), `min_n` (minimum executions per category). Canvas height auto-scales with the number of categories. |
| [lib/t2sevalexecdetails.inc.php](lib/t2sevalexecdetails.inc.php) | **Drill-down list**. Reached by clicking a bar in the graph. Reads the layer definition from session + a `cat_id` from query string, then lists every execution in that category for that layer with PASS/FAIL badges, sortable columns (`tim_execution`, `score`, `total_time`, `cost`, `t2sevalexecid`) and pagination (`per_page` 10–200). Each row links to the JSON viewer. |
| [lib/t2sevalexecjson.inc.php](lib/t2sevalexecjson.inc.php) | **JSON viewer** for the raw `JSON_RESULT` of one execution (`?t2sevalexecid=<ID_ROW>`). Default response is a styled HTML view of the pretty-printed payload; pass `?format=json` to get the parsed JSON directly. Falls back to the raw column value when it is not valid JSON. |

### Endpoints / query parameters

```
t2sevalexecgraph.php?x=cat&y=avg_result_score&only_eval=1&min_n=3
t2sevalexecdetails.php?layer=0&cat_id=12&y=avg_total_score&sort=score&dir=DESC&per_page=50
t2sevalexecjson.php?t2sevalexecid=9821[&format=json]
```

The graph is the entry point: define one or more layers via the form, click a bar to open the drill-down for that `(layer, category)` pair, click an execution row to view its full JSON response.

### Configuration

The PHP app loads `eval/.env` via `global-light.inc.php` and expects:
- `DB_HOST` (with optional `:port` suffix), `DB_NAME`, `DB_USER`, `DB_PASSWORD` — same MariaDB instance as the Python evaluator
- `$arrallowedmodels` / `$arrallowedcomplexmodels` — defined inside `global-light.inc.php`; populate the layer dropdowns

Runs on PHP 8.1+ behind any web server (Apache, Nginx + php-fpm, or `php -S` for local dev). PHP sessions must be enabled (the layer list lives in `$_SESSION['t2s_layers']`). All DB queries use prepared statements via `mysqli`.

---

## 12. Troubleshooting

### Evaluator exits immediately with "API version mismatch"
Your `--api-version` (and/or `--*-model`) does not match what the server actually returned in `response_json["api_version"]` / `llm_model_*`. The guard prevents spending tokens on a wrong configuration. Either rebuild the API container with the expected version or pass `--api-version` matching the running server.

### Assertion syntax pitfalls
```python
"ID_MOVIE IN 910, 22584"    # wrong — missing parentheses
"ID_MOVIE IN (910, 22584)"  # correct

"COUNT(*) = 5"              # wrong — single =
"COUNT(*) == 5"             # correct

"NONEXISTENT_COL >= 5"      # error message will list available columns
```

### EE expression eval returns 0 but looks correct
- The expression must be a single logical line — wrap multi-line text in `(...)` or concatenate
- The assertion engine is fail-closed: any `re.error`, `SyntaxError`, or missing key yields `0`
- Placeholder names in `question` must match entity keys exactly (case-sensitive; `{{Movie_title1}}` ↔ `Movie_title1`)

### Phase 11 skips everything
- Every `(api_version, model triple, language)` combination is already present in `T_WC_T2S_EVALUATION_EXECUTION` — this is the intended re-entrant behaviour
- To force a re-run, soft-delete the matching executions (`UPDATE ... SET DELETED = 1`) and run Phase 10 first, or bump the API version

### `Column 'ID_MOVIE' does not exist in DataFrame` despite the right movies appearing
The Text2SQL prompt emitted the unified `ID_CONTENT` + `CONTENT_TYPE` result shape but the assertion used a per-table column name (`ID_MOVIE` / `ID_SERIE` / `ID_PERSON`). The evaluator resolves this automatically via the unified-schema bridge documented in [§4.3 Unified-schema column bridge](#unified-schema-column-bridge) — if you still see this message, check that the API response actually contains both `ID_CONTENT` and `CONTENT_TYPE` columns (a malformed SQL that aliased `ID_CONTENT` without emitting `CONTENT_TYPE`, or vice versa, will not trigger the bridge).

### Phase 20 produces no output
- No executions match the CLI filter tuple — check `API_VERSION` is stored in `XXX.YYY.ZZZ` form
- `JSON_RESULT` may be empty or unparseable — `safe_json_loads()` will raise

### Questions without assertions
Phase 11 only selects questions where at least one assertion column is non-empty. Rows with all three assertion columns null are ignored — that's how the question bank distinguishes "sample" entries from "evaluation" entries (also controlled by `IS_EVAL`).

---

## 13. Version History

| Version | Date | Changes |
|---|---|---|
| 2.5 | 2026-05-06 | Added the **unified-schema column bridge** to `evaluate_dataframe_assertions()` in [text2sql_eval_functions.py](text2sql_eval_functions.py): when a result DataFrame carries both `ID_CONTENT` and `CONTENT_TYPE` (the unified movie/serie/person shape prescribed in [data/text_to_sql.md](../data/text_to_sql.md)), virtual `ID_MOVIE` / `ID_SERIE` / `ID_PERSON` columns are synthesized so legacy `ID_MOVIE IN (...)` / `ID_SERIE IN (...)` / `ID_PERSON IN (...)` assertions resolve without any question-bank migration. Existing columns are never overwritten; non-matching rows become NaN. Fixed the systemic regression where ~621 evaluation rows scored 0 with `Column 'ID_MOVIE' does not exist in DataFrame`. Added [test-unified-schema-bridge.py](test-unified-schema-bridge.py) (12 cases: movies-only, mixed movies+series, ID_PERSON, mixed-case `Movie`, no-op when column already exists, no-op when `CONTENT_TYPE` is absent, `NOT IN` semantics). Documented the bridge in [§4.3 Unified-schema column bridge](#unified-schema-column-bridge) and the matching troubleshooting entry in §12. |
| 2.4 | 2026-04-27 | Documented the [lib/](lib/) PHP web UI — `global-light.inc.php` (shared bootstrap), `t2sevalexecgraph.inc.php` (multi-layer comparison graph with selectable Y axis and per-layer color), `t2sevalexecdetails.inc.php` (per-`(layer, category)` drill-down with pagination and sort), and `t2sevalexecjson.inc.php` (`JSON_RESULT` viewer with `?format=json` switch). Added [§11 Interactive Web UI (PHP)](#11-interactive-web-ui-php) and a `lib/` row in the source files table; renumbered Troubleshooting (§12) and Version History (§13). Also rewrote [how-many-samples-evals-by-category.ipynb](how-many-samples-evals-by-category.ipynb) to read the Phase 30/31 JSON exports (replacing the legacy CSV source) and updated its source-files entry plus a downstream-consumer note in §10. |
| 2.3 | 2026-04-25 | Phase 32 now writes execution JSON files into a per-run subfolder `<api_version>_<lang>_<eemodel>_<t2smodel>_<complexmodel>/` under `/shared/evaluation_execution/`, so successive runs across versions, languages, and model triples stay isolated instead of piling up in a single folder. |
| 2.2 | 2026-04-25 | Added Phases 30/31/32 — JSON exports of `T_WC_T2S_EVALUATION_CATEGORY`, `T_WC_T2S_EVALUATION`, and `T_WC_T2S_EVALUATION_EXECUTION` to `/shared/<subfolder>/` (one file per row, skip-if-exists, ASCII-folded slug filenames, eval ID embedded in execution filenames to avoid same-day collisions). The exports power downstream LLM analysis of the question bank, taxonomy, and execution results without requiring DB access. |
| 2.1 | 2026-04-21 | Added `ui_language` parameter to API calls (one call per question×language pair); response now includes `answer`, `answer_anonymized`, `ui_language` in `JSON_RESULT`; removed EN/FR question-text deduplication since the `answer` field is language-specific |
| 2.0 | 2026-04-21 | Documented multi-phase pipeline, CLI, `ASSERTIONS_SQL_QUERY` regex scoring, `ASSERTIONS_TOTAL_SCORE` aggregation, EN/FR dedupe, language filter, complex-question processing flag, timing rollup |
| 1.2 | 2026-02-20 | Added `CELL(row, col)` and `COUNT(column)` unique-value assertions |
| 1.1 | 2026-02-10 | Added two-layer entity extraction DSL (`ee_eval_two_layer`) |
| 1.0 | 2025-02-07 | Initial DataFrame assertion evaluator |

---

**Last Updated:** 2026-05-06
**Maintainer:** See repository owner
**Primary entry point:** [text2sql-eval.py](text2sql-eval.py)
