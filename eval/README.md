# Text2SQL Evaluator

**Version:** 2.1
**Last Updated:** 2026-04-21
**Status:** Production Ready
**Main file:** [text2sql-eval.py](text2sql-eval.py)

End-to-end evaluation harness for the FastAPI Text2SQL service: calls the running `/search/text2sql` endpoint with a curated question bank, stores each JSON response, and scores the responses against three assertion types (entity extraction, SQL regex, result-set DataFrame). All results, scores, and timing metrics are persisted to a MariaDB table for historical analysis and regression tracking.

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
10. [Troubleshooting](#10-troubleshooting)
11. [Version History](#11-version-history)

---

## 1. Architecture

The evaluator is a **single-pass multi-phase pipeline** driven by a numeric process index. Each phase reads from or writes to one of three evaluation tables:

| Table | Role |
|---|---|
| `T_WC_T2S_EVALUATION` | Question bank (EN + FR) + three assertion columns (`ASSERTIONS_ENTITY_EXTRACTION`, `ASSERTIONS_SQL_QUERY`, `ASSERTIONS_QUERY_RESULT`) |
| `T_WC_T2S_EVALUATION_CATEGORY` | Taxonomy (categories of questions) |
| `T_WC_T2S_EVALUATION_EXECUTION` | One row per `(eval_id, api_version, entity_extraction_model, text2sql_model, complex_model, language)` combination — stores the full JSON response, per-assertion scores, aggregated `ASSERTIONS_TOTAL_SCORE`, and timing breakdown |

Phases run in order: **translations → cleanup → run → process**. Rerunning the same command is idempotent — the `run` phase skips combinations already present in `T_WC_T2S_EVALUATION_EXECUTION`.

Phase 11 hits the FastAPI server over HTTP. Phase 20 does the scoring offline against the stored `JSON_RESULT`. This separation means scoring can be re-run after an assertion correction without re-spending LLM tokens.

---

## 2. Quick Start & CLI

```bash
# Docker (recommended)
docker run -it --rm --network="host" --name text2sql-eval text2sql-eval-python-app

# Custom parameters
docker run -it --rm --network="host" --name text2sql-eval text2sql-eval-python-app \
  --api-version 1.1.15 \
  --entity-extraction-model gpt-4o \
  --text2sql-model gpt-4o \
  --complex-model gpt-4o \
  --language fr

# Launch via helper script (builds image, runs detached)
./text2sql-eval.sh
```

All CLI arguments are optional; defaults are chosen so `docker run` without arguments reproduces the previous hardcoded configuration.

| Argument | Default | Description |
|---|---|---|
| `--entity-extraction-model` | `gpt-4o` | LLM model for entity extraction (matches API `llm_model_entity_extraction`) |
| `--text2sql-model` | `gpt-4o` | LLM model for text-to-SQL generation |
| `--complex-model` | `gpt-4o` | LLM model for complex-question processing / stronger-model retry |
| `--api-version` | `1.1.14` | API version expected in the response; execution aborts on mismatch |
| `--language` | `*` | Language filter: `en`, `fr`, or `*` for both |

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

# Translations (phases 4/5/6)
OPENAI_API_KEY=sk-...
```

The evaluator computes the API port from the patch parity of `--api-version` (even → Blue, odd → Green), matching the Blue/Green deployment convention of the API itself.

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
- Posts to `POST {TEXT2SQL_API_URL}/search/text2sql` with `complex_question_processing=True`, `retrieve_from_cache=False`, `store_to_cache=True`, `rows_per_page=100`, `ui_language=<lang>`
- **Configuration guard**: if `api_version` / `llm_model_*` in the response do not match the CLI args, the script exits immediately to avoid burning tokens with a misconfigured server
- Persists the full JSON response (including `answer`, `answer_anonymized`, `ui_language`) as `JSON_RESULT` in `T_WC_T2S_EVALUATION_EXECUTION`
- Default page limit: `LIMIT 10` per run (see line 217). Remove for a full pass.

### Phase 20 — Score stored executions
For every `JSON_RESULT` in `T_WC_T2S_EVALUATION_EXECUTION` matching the CLI filters, the evaluator:
1. Parses the JSON via `t2s_eval.safe_json_loads()`
2. Builds a pandas DataFrame from `response_json["result"]` (each row is `{"index": int, "data": dict}`)
3. Runs the three assertion evaluations (see §4) and computes per-assertion scores
4. Aggregates `ASSERTIONS_TOTAL_SCORE = 1` iff every non-null per-assertion score is `1`
5. Writes scores + `ASSERTIONS_RESULT_DETAILED` (human-readable multi-line trace) back to the execution row
6. Accumulates pipeline timings to print a run summary

Phase 20 is pure offline scoring — re-runnable after assertion corrections without hitting the API.

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
| [Dockerfile](Dockerfile) | `python:3.11-slim` base; installs `requirements.txt`; entrypoint `python ./text2sql-eval.py` |
| [text2sql-eval.sh](text2sql-eval.sh) | Build image + run container (detached, host network) |
| [requirements.txt](requirements.txt) | `requests`, `pymysql`, `pandas>=1.5`, `numpy>=1.21`, `pytest>=7`, `pytz`, `python-dotenv>=1`, `openai>=1` |
| [T2S_EVALUATION-tables.sql](T2S_EVALUATION-tables.sql) | DDL for the three evaluation tables |
| [T2S_EVALUATION-tables-with-data.sql](T2S_EVALUATION-tables-with-data.sql) | DDL + seed question bank |
| [how-many-samples-evals-by-category.ipynb](how-many-samples-evals-by-category.ipynb) / `.sql` | Coverage-by-category reporting notebook |
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

## 10. Troubleshooting

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

### Phase 20 produces no output
- No executions match the CLI filter tuple — check `API_VERSION` is stored in `XXX.YYY.ZZZ` form
- `JSON_RESULT` may be empty or unparseable — `safe_json_loads()` will raise

### Questions without assertions
Phase 11 only selects questions where at least one assertion column is non-empty. Rows with all three assertion columns null are ignored — that's how the question bank distinguishes "sample" entries from "evaluation" entries (also controlled by `IS_EVAL`).

---

## 11. Version History

| Version | Date | Changes |
|---|---|---|
| 2.1 | 2026-04-21 | Added `ui_language` parameter to API calls (one call per question×language pair); response now includes `answer`, `answer_anonymized`, `ui_language` in `JSON_RESULT`; removed EN/FR question-text deduplication since the `answer` field is language-specific |
| 2.0 | 2026-04-21 | Documented multi-phase pipeline, CLI, `ASSERTIONS_SQL_QUERY` regex scoring, `ASSERTIONS_TOTAL_SCORE` aggregation, EN/FR dedupe, language filter, complex-question processing flag, timing rollup |
| 1.2 | 2026-02-20 | Added `CELL(row, col)` and `COUNT(column)` unique-value assertions |
| 1.1 | 2026-02-10 | Added two-layer entity extraction DSL (`ee_eval_two_layer`) |
| 1.0 | 2025-02-07 | Initial DataFrame assertion evaluator |

---

**Last Updated:** 2026-04-21
**Maintainer:** See repository owner
**Primary entry point:** [text2sql-eval.py](text2sql-eval.py)
