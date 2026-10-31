# AGENTS.md - Agent Guide for FastAPI Text2SQL

This file holds the rules an agent needs to work on this codebase safely. Project overview, install, deployment, request/response examples and troubleshooting are in @README.md, which is canonical. Assistant-specific files (@CLAUDE.md, a future `GEMINI.md`) only point here.

Deeper references, read the one that matches the task:
- @data/AGENTS.md : the hot-reloaded prompts and configuration, what each file must keep, and the three rules twinned between `complex_question.md` and `vision_identification.md` that must stay different
- @doc/AGENTS.md : index of the reference documentation, and the rule that a new entity ships with a measured threshold
- `doc/pipeline-internals.md` : file-by-file map of the code, scheduling, SQL guards, retries and rescues, entity-endpoint contracts, typographic rescue, rounding, clock and shared folders
- `doc/llm-tasks-and-costs.md` : the six LLM tasks, measured costs and latencies, model benches, prompt cache, reasoning-family block, resolution-mode verdicts, adding a response indicator
- `doc/vision-pre-stage.md` : the image path (FASTAPI-TEXT2SQL-114, -275, -281, -307) and its recognition cache
- @doc/MCP.md (MCP server), @doc/RAPIDFUZZ.md (RapidFuzz setup and schema), `doc/entity-resolution-thresholds.md` (how every `min_fuzz_ratio` was measured)
- `maintenance/AGENTS.md` : one-shot operational SQL against production (`T_WC_T2S_CACHE` first); read it before adding or running anything there
- `checks/` : offline checks and benches that import this repo's modules (`verif-*`, `check-*`, `bench-*`, `eval-309`)
- `../text2sql-eval/README.md` : the evaluator, a separate repository since 2026-10-12
- `doc/sql/*.sql` : reference DDL, **read-only** unless the user explicitly asks for schema-doc edits

Keep documentation aligned with every change: `README.md` for user-facing behaviour, configuration, setup, deployment and verification; endpoint docstrings when the API changes (the MCP tool docstrings are the MCP contract); the matching `doc/` file when its subject changes; this file only when agent workflow or safety context changes.

---

## Related repositories (project ecosystem)

`fastapi-text2sql` is the serving stage of **Agent BBB**, a multi-repository movie/TV system (`%USERPROFILE%/Code/<repo>`, `github.com/vaugouin/<repo>`) converging on a shared MariaDB (`T_WC_*`) and a ChromaDB store whose collections `embedding-update` builds. Canonical roster: `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/related-repositories.txt`. `tools` (private) holds the host-side scripts for the shared database.

---

## Clients of this API — read before flipping Blue/Green

Bumping `strapiversion` moves the deployment to the other colour (even patch: Blue, `API_PORT_BLUE`, 8186; odd: Green, 8187). **Only the evaluator follows that parity on its own**; every other client is repointed by hand, so check this list before and after a bump.

| client | how it picks a colour | what to change |
|---|---|---|
| **evaluator** (`text2sql-eval`) | port derived from the parity of `--api-version` | nothing |
| **Claude, via MCP** | `https://www.vaugouin.com/mcp`, routed by NGINX | the `reverseproxy` repo: repoint the upstream port |
| **tmdb-front** | `$strtext2sqlapicolor` hard-coded in `lib/global-light.inc.php`, plus the per-colour label `$strtext2sqlapiblueversion` | swap the commented lines and update the label (the samples page looks executions up by it and renders empty otherwise), deploy the front |
| **voice-agent** | `TEXT2SQL_BASE_URL` in its `.env`, port in full | edit the port, then **recreate** the container (`restart.sh`): `--env-file` is read at `docker run`, a `docker restart` keeps the old value |

- **Redeploying in place** (shipping code without a bump) makes the table a no-op but blinds `api_version`: prove the new code with a **capability probe** (a field only the new code emits) on the bare-identifier fast path (`{"question":"tt0033467"}`, no LLM call, no cache write). Old `T_WC_T2S_CACHE` rows of the same version stay live, so never reuse the version for a change that alters generated SQL.
- **Do not diagnose a deployment on its first requests**: wait for `bktrees_ready: true` in `GET /` (the warm-up competes for CPU for several minutes).
- tmdb-front accepts `?apicolor=Blue` and keeps it in a one-year cookie: a cheap pre-test, and a trap afterwards (your own browser may be pinned).
- From the PC, both colours answer over Tailscale at `100.113.161.122`; read the key from `TEXT2SQL_API_KEY` in `~/Code/text2sql-eval/.env`, never hard-code or print it.

A flip is complete when every client reports the new version and the instance reports `bktrees_ready: true`. Per-client verification commands and the full reasoning: `README.md` § *Blue/Green Deployment*.

---

## Where things live

Edit at the right layer: `main.py` orchestrates only, the LLM calls live in `text2sql.py`, extraction and resolution in `entity.py`. File-by-file map: `doc/pipeline-internals.md` § *Where things live*. Invariants not to break:

- `sql_shapes.py` is shared by the runtime guard in `main.py` and the measurement in `analyze-complex-retry-logs.py`: never fork the predicate back into either caller.
- `vision_cache.identification_payload()` is the cache contract: store only what depends on the image, never on the question.
- `logs.LOGS_FOLDER` and `uploads.UPLOADS_FOLDER` stay **relative**: absolute or per-colour would split the log corpus and make cross-colour image replays fail silently.
- `uploads.f_getuploadfilename()` hashes the raw bytes; do not reuse `logs.f_getlogfilename`, which hashes text.
- `data_watcher.register()` reads its files eagerly: a registered `data/` file missing at import kills the container at boot.
- `llm_costs.PRICES` is the only place a price lives. A model missing from it is reported in `unpriced_models`, never priced at zero: add its row (source and date) when you add a model.
- A new DB connection comes from `get_db_connection()` (its cursor times every statement) and a new ChromaDB call goes inside `with logs.chroma_call():`, or it escapes `server_usage`.
- `maintenance/` writes to operational tables by hand; no code path loads it. Distinct from `doc/sql/` (reference DDL).

---

## Runtime dependencies

The variables are in `README.md`, *Set up environment variables*. What it does not say:

- **`OPENAI_API_KEY` is required at startup even when no OpenAI model is selected**: the ChromaDB embedding function is OpenAI.
- **`MCP_API_KEY` empty means `/mcp` is open**, not weakly protected (`_verify_mcp_bearer` only enforces a bearer `if MCP_API_KEY:`). Startup logs a warning, the only signal.
- **`UPLOADS_FOLDER`, `UPLOAD_RETENTION_DAYS` (30) and `MAX_UPLOAD_IMAGE_BYTES` (25 MB)** are read at import (restart to change), and `UPLOAD_RETENTION_DAYS` must match the `--days` the cron passes to `purge-uploads.sh`.

---

## ChromaDB collections

`t2slocations` is opened with **`get_collection`, never `get_or_create_collection`** (FASTAPI-TEXT2SQL-247): its HNSW configuration is fixed at creation by process 216 of `embedding-update`, and a `get_or_create` would silently recreate it with server defaults the day it is missing (no error, only worse ranking). The same reasoning dropped the old `locations` collection. If schema, entity IDs, document IDs or language-routed fields change, assume the collection needs rebuilding: stale embeddings resolve to IDs that no longer exist.

---

## Hot-reloaded vs restart-required

Anything under `data/` hot-reloads about 5 s after an mtime change (in production `restart.sh` mounts the checkout as `/app`). A restart is required for any `*.py` change, a new placeholder, or a new `closed_vocab` loader or query. Do not bump `strapiversion` automatically (see *Version management workflow*); when a prompt or config change ships without a bump, say that cache rows of the current version may shadow it.

---

## Placeholder dispatch order

Inside `entity.resolve_entities()` four stages run in order (the placeholder-to-stage table is in `README.md`):

1. **Regex-validated** (`_REGEX_PLACEHOLDER_RULES`). Dispatch uses `startswith()`, so **a more specific prefix must be listed before the one it extends** (`IMDb_person_ID` before `IMDb_ID`, `Wikidata_property_ID` before `Wikidata_ID`); getting it wrong is silent. A rejected value leaves the placeholder, which marks the question ambiguous. `is_numeric` follows the target column's SQL type.
2. **Closed vocabulary**, `if/elif` on name prefix calling `closed_vocab.resolve*`: Genre and `Technical_format` substitute a bare integer, the others a quoted string.
3. **Embeddings / RapidFuzz**, driven by `data/entity_resolution.json` `search_list`.
4. **Raw fallback**, SQL-escaped. Anything still unresolved sets `ambiguous_question_for_text2sql`.

## Adding a new placeholder

| Kind | Where the resolver lives | What goes in `entity.py` | Schema edits |
|---|---|---|---|
| Regex (year, ID-style literal) | `_REGEX_PLACEHOLDER_RULES` tuple | nothing | none |
| Closed-vocab string (Status-shape) | `closed_vocab._XXX_QUERY` + `init()` block | name-prefix branch calling `closed_vocab.resolve("XXX", raw)` | optional aliases in `data/closed_vocabularies.json` |
| Closed-vocab integer ID (Genre-shape) | `closed_vocab._XXX_CANONICALS_QUERY` + `init()` + `resolve_xxx()` (mirror `resolve_genre`) | name-prefix branch substituting the integer, no quotes | aliases JSON; optional `_LANG` table |
| Embeddings / RapidFuzz (open-vocab name) | entry in `data/entity_resolution.json` | nothing, config-driven | new ChromaDB collection opened in `main.py` |

Always also: define the placeholder with examples in `data/entity_extraction.md`, reference it (and any column rule) in `data/text_to_sql.md`, update `closed-vocab-entity-checklist.csv` for a closed-vocab entity, ship a **measured** `min_fuzz_ratio` with an embeddings entity (`doc/AGENTS.md`), and bump `strapiversion` only on request.

---

## Pipeline scheduling and the fork-join

LLM calls and the generated SQL run through `asyncio.to_thread`; a blocking call inside the async endpoint serializes every client. `plan_entity_resolutions()` is forked just before the text-to-SQL call and joined after the answer-entity guard: **the join is unconditional and must stay where it is**, because the complex-retry path below it closes the connection the worker uses. The result-entity classifier is a second fork (no DB connection, so an early return is harmless). Details and the one accepted behavioural divergence: `doc/pipeline-internals.md` § *Pipeline scheduling*.

## Generated SQL goes through `_run_generated_sql`, always (FASTAPI-TEXT2SQL-302)

Any place that executes model-written SQL calls `_run_generated_sql` (off the event loop, capped by `SET STATEMENT max_statement_time`, `SQL_MAX_STATEMENT_TIME`, default 60 s). A query killed at the cap returns `sql_timeout` and is **not** regenerated nor retried on the stronger model. `COUNT(...) OVER ()` is refused before MariaDB (-303). The answer-entity guard exempts a single `COUNT` / `AVG` / `SUM` total and an attribute-keyed statistics table, never `MIN` / `MAX` (-303, -311; check with `uv run checks/verif-311.py`). Why and how it was measured: `doc/pipeline-internals.md`.

## The six LLM tasks, and what each one actually costs

`entity_extraction`, `text2sql`, `result_entity`, `complex_question`, `vision_identification` (image only, OpenAI only), and the retired `answer_single_value` (-331, selector ignored). Each carries a `cache_label` (prompt-cache log key and default reasoning effort); find call sites with `grep -n 'cache_label="' text2sql.py entity.py`, never by line number. Extraction and text2sql carry 97 % of the bill: measure there first. `embedding_usage` is deliberately **not** a task of `llm_usage` (consumers sum its entries as chat calls). Measured costs, latencies, client selectors and the bench discipline (noise floor first, three outcomes, never one accuracy number): `doc/llm-tasks-and-costs.md`.

When grepping the `Prompt cache (...)` log lines, use the class `[a-z0-9_]`: `text2sql` carries a digit and `[a-z_]` silently drops the most expensive task.

## Reasoning models and the provider prompt cache

There is no model allowlist: anything starting with `gpt-` goes to OpenAI. A new reasoning family needs **all four** entries of the block in `text2sql.py` (`_REASONING_MODEL_PREFIXES`, `_EFFORT_BY_FAMILY`, a rung for every `cache_label` in `_DEFAULT_EFFORT_TIER`, an endpoint decision in `_CHAT_COMPLETIONS_REASONING_PREFIXES`), or it spends silently. GPT-6 has no `none` rung. Function tools combined with `reasoning_effort` are refused for `gpt-5.6-sol` on chat completions, which is why the vision call's structured output degrades once to plain JSON. On gpt-5.6+ the explicit cache breakpoint at `<!--CACHE_BOUNDARY-->` decides the price: keep `{ui_language}` and anything else that varies below that boundary, and bench the cache with NEW questions only. Offline check: `uv run checks/verif-274.py`. Full reasoning: `doc/llm-tasks-and-costs.md`.

---

## Before and after an evaluation campaign: `off-all.sh`, then `on-all.sh`

Every automated VPS task is started by cron through a script that exits at once while its folder holds `CRON_OFF` (`off.sh` writes it, `on.sh` deletes it). `docker stop` alone is not enough (the next cron tick restarts it), and `embedding-update` rewrites the ChromaDB collections, changing the **answers** being measured.

```bash
bash ~/docker/off-all.sh      # before: every automated task off (one folder: bash ~/docker/<task>/off.sh)
docker stop <what is still running>   # off.sh only prevents the NEXT launch
# ... the campaign(s): English, French, the same-day rescore of the baseline ...
bash ~/docker/on-all.sh       # after the LAST campaign of the session: everything back on
```

`text2sql-eval.sh` checks the "off" half in its pre-flight; nothing checks the "on" half, and forgetting it freezes crawlers and embeddings for days. Rule set by Philippe on 2026-09-26.

**After the campaign, bring the results home** (Philippe, 2026-10-17): on the PC, `cd C:\Users\vaugo\Code\voice-agent\doc\logs-download` then `uv run --no-project --with paramiko python sync_vps_docker.py`. It mirrors the VPS `~/docker` tree additively (exports and API logs). It prompts for the SSH key passphrase, so give Philippe the command and never launch it yourself (it hangs).

Evaluation verdicts (`RESOLUTION_MODE` and the escalation-cause columns): `doc/llm-tasks-and-costs.md`. Keep them out of `ASSERTIONS_TOTAL_SCORE` (comparability between campaigns), and never backfill NULL on old rows.

---

## Entity resolution thresholds (`min_fuzz_ratio`)

Never adjust a threshold by hand on one bad case: each is the midpoint of a measured interval. Re-run `checks/bench-entity-resolution.py` and read `doc/entity-resolution-thresholds.md` (§10 first if a value looks wrong). `document_name_separator` and `score_stopwords` are declared **per entity, never globally**: a title can contain the separator ("Star Trek: The Next Generation"), and a word generic for one type is identifying for another (`Award_name`, `Movement_name` and `List_name` deliberately carry no stopwords). Never strip descriptions out of the embeddings to help the ratio; the durable fix is a bare-name metadata field in `embedding-update`. Adding stopwords to a gated type changes the gate: bench before and after. `rescue_normalizations` (FASTAPI-TEXT2SQL-309) is configured per type from measurement, bar "0 new wrong acceptances"; do not lower a threshold to get the same effect. Method and the `eval-309` stage commands: `doc/pipeline-internals.md` § *Typographic rescue of the gate*.

## Entity-resolution config schema (`data/entity_resolution.json`)

Key-by-key reference (`search_mode`, language gating, `languages` routing, `resolve_to_canonical`, and the opt-in confidence gates `min_fuzz_ratio`, `max_distance`, `rescue_normalizations`, `require_confident`): `doc/pipeline-internals.md` § *Entity-resolution config schema*. Gates use `fuzz.ratio`, **not** `WRatio`. ChromaDB document IDs are always `{entity}_{id}_{lang}`.

---

## Retries, rescues and the cache

The rules; the measurements and traces behind them are in `doc/pipeline-internals.md`.

- **A retried request writes two log files** (inner pass with the rewritten question, outer with the user's wording and the `first_pass_*` fields). Anything counting questions over `logs/` skips the inner file (`request.complex_question_already_resolved` true).
- **`first_pass_entity_extraction` says why a question was routed; `entity_extraction` says how the answer was built** (on a retry it describes the rewritten question). `QUERY_MODE` reads the first, never the second.
- Retry and guard **message prefixes are a contract**: `analyze-complex-retry-logs.py` and `analyze-usage-logs.py` key on them. Grep both scripts before rewording a message.
- A new `except` in the execution block sets its own `sql_execution_failure_code` / `_reason`.
- The no-entity rescue (-244) runs before the stronger model, only on an empty page 1 with nothing extracted; a rescued SQL is adopted whatever its row count, anonymized copy included.
- After a retry, the cache row under the original wording is skipped when the rewrite adds a year absent from the question (-242).
- `complex_retry_seed` (-300) is ignored unless `complex_question_already_resolved` is true, so a client cannot bypass extraction.
- **Entity identity boundary**: Text2SQL never identifies an unnamed real-world entity from clues; `descriptive_identification` routes to the stronger model first. `entity.find_unbacked_entity_literals()` stays before SQL execution and cache writes, and judges only SQL generated in the current request, never an exact-cache hit (-259). `query_mode` is validated but not required (-255). When adding a required key to a prompt contract, update every example of that prompt in the same commit.

---

## Entity endpoints

`data/text_to_sql.md` (generated SQL) and the entity detail endpoints in `main.py` (hand-written SQL, plus their MCP `get_*` tools) are two SQL surfaces over the same data, kept in sync by hand. When working on either, scan the other for drift (filter predicates such as `CAST_CHARACTER` exclusions, default sorting, order of related lists, result columns, the *Aggregated questions* contract) and **surface any discrepancy to the user** rather than patching silently; `data/text_to_sql.md` is the spec unless the user says otherwise.

Contracts that break silently when editing an endpoint (details: `doc/pipeline-internals.md` § *Entity endpoints*):
- A new nested SELECT selects the `_FR` variants, and a new nested array of movie / serie / person / season rows is added to that endpoint's `apply_localized_related_images` call.
- `record_source`: `RECORD_SOURCE_TMDB` only where `TIM_UPDATED` is copied verbatim from TMDb; elsewhere `tmdb_updated_at` stays null.
- `wikipedia_page.lang == data_freshness.wikipedia_lang` on every response; `_resolve_wikipedia_page_row()` is the single home of the language rule, never resolve on a page row's mere existence. The `text` format of Wikipedia content stays byte-identical.
- A new related list goes in the endpoint's `pcollections` registry (with `COUNT(*) OVER() AS _TOTAL_COUNT`, a deterministic `ORDER BY` with unique tiebreaker, no `LIMIT`, no semicolon), never a one-off `cursor.execute`.
- A new collection is listed twice in its MCP tool docstring (relations and valid `collection` values), or MCP clients never see it.
- A new entity endpoint declares `response_class=RoundedJSONResponse` (`checks/verif-308.py` counts them).

## Numbers are rounded on the way out, and only there (FASTAPI-TEXT2SQL-308)

`response_rounding.py` rounds at serialization; the attributes keep raw values. Never round in SQL or in the prompt, and do not reintroduce a `Decimal` path that bypasses the two hooks (a `Decimal` inside `result` would serialize as a string). A new numeric field is rounded by its name; check the default suits it. Any script that execs the `Text2SQLResponse` block needs `field_serializer` and `round_tree` in its namespace.

---

## The representation hint has two consumers, keep them in step (FASTAPI-TEXT2SQL-349, -350)

`result_shape.py` (`classify_result`) emits `representation`, `result_kind` and `result_columns` on every live result. Two fronts dispatch on them: voice-agent (`app/static/app.js`, `chooseText2SqlRepresentation()`) and tmdb-front (`lib/t2s-representation.inc.php`, called by `lib/text2sql-search.inc.php`; TMDB-FRONT-112). Rule set by Philippe on 2026-10-31: a representation added or changed here ships on both fronts in the same batch. Before committing a classifier change, run the offline census (recompute every export of the latest campaign with the old and the new module and diff the representations, as for -350): a rule that looks local can flip a hundred evals, as the first entity-ranking rule did.

---

## Run pyflakes before committing Python, and read the "undefined name" lines

```bash
uv run --with pyflakes python -m pyflakes *.py | grep "undefined name"
```

Blocking. On 2026-08-29 a refactor renamed a variable and left one reader behind; every embeddings resolution raised `NameError` (500) and neither `ast.parse` nor `import` caught it. A refactor that moves a definition is verified by finding who else read the old name.

## A new shell script needs its executable bit set IN GIT, not on disk

`core.filemode` is false in this checkout, so `chmod +x` changes nothing git records and the VPS answers `Permission denied`. It has cost three deployments.

```bash
git update-index --chmod=+x path/to/script.sh
git ls-files -s '*.sh'          # every one of them must read 100755
```

Prefer `bash script.sh` over `./script.sh` when a first run must not be about permissions.

## Code conventions

- **Hungarian notation** for variables (legacy style): `str` strings, `lng` integers, `dbl` floats, `arr` lists, `int` boolean-like flags (`strapiversion`, `lngpage`, `intcleanupenabled`).
- **Function naming**: public pipeline entry points use `f_` (`f_text2sql`, `f_entity_extraction`); private helpers use `_`.
- **Docstrings**: Google-style on public functions.
- **Error handling**: broad try/except with console logging; surface failures via the `error` field and the `messages` trace. Database execution errors are not returned raw to clients; they go through the complex-question retry path when enabled.
- **JSON serialization**: `logs.decimal_serializer()` for `Decimal` and `datetime`.
- **Encoding**: Markdown, prompts, JSON config and logs are UTF-8 with non-ASCII names; avoid operations that rewrite them with mojibake.

---

## Applying a `.sql` file on the VPS: `runsqlvaugouindb.sh`, always

Evaluation-bank scripts (in `text2sql-eval`) and `maintenance/*.sql` run with the `tools` runner, never a hand-built `docker exec ... mariadb`. The `.sql` must be pushed first.

```bash
cd ~/docker/fastapi-text2sql-green        # the clone of the live colour
git pull
~/docker/tools/runsqlvaugouindb.sh ~/docker/text2sql-eval/<file>.sql
# result: ~/docker/text2sql-eval/<file>-YYYYMMDD.txt, errors included
```

`-f` overwrites a same-day result, `-e` stops at the first error. The `pull` also stages the code the next restart of that colour loads. After an evaluation-bank change, rescore with Phase 20 (offline, no token). Reference: `tools/AGENTS.md`, "Running a .sql file".

## SQL handling rules

- **Escaping**: doubled single quotes (`'O''Brien'`), never backslash, which breaks MariaDB. Use `entity._sql_escape_literal()`.
- **Pagination**: LLM-emitted `LIMIT` / `OFFSET` clauses are stripped by regex; a smaller LLM-defined limit is respected.
- **Ambiguous questions**: when the LLM cannot produce a valid query or placeholders stay unresolved, set `ambiguous_question_for_text2sql = True`, skip execution, surface the explanation in `error`. The legacy `##AMBIGUOUS##` marker is gone; do not reintroduce it.
- **Read-only**: generated SQL is SELECT only; never add write queries to prompt examples or generated paths. Cache writes live in `sql_cache.py`, cleanup deletes in `cleanup.py`. Prefer parameterized SQL for application-owned queries.

## Messages array invariant

Every step appends `TextMessage(position=position_counter, text=...)` then increments the counter. Delegated calls (`entity.resolve_entities()`, `_retry_with_resolved_complex_question()`) return the updated counter in their result dict; on a complex retry the outer and inner messages are renumbered and merged.

## Cache API-version filtering

Cache reads and writes take the **formatted** version (`XXX.YYY.ZZZ`, from `format_api_version()`), never the raw `strapiversion`; the `sql_cache` helpers receive it as a parameter, so pass it through. Lookups also filter on `UI_LANGUAGE`, with `OR UI_LANGUAGE IS NULL` for older rows. An empty result is never cached (Gotcha #8b); an `authoritative_empty` vision identification is.

---

## Version management workflow

When updating prompt templates, schema, or resolver behavior:
1. Edit the hot-reloaded file in `data/` directly (no versioned filename suffix).
2. Bump `strapiversion` in `main.py` only when the user explicitly asks for a version bump. This also flips the Blue/Green parity, so the client table above applies.
3. Restart only if you also touched `*.py`, in the checkout whose colour matches the **current** version's parity (`restart.sh` reads its colour from its folder and refuses to run elsewhere). Never infer the live colour from which checkout was restarted last.
4. If `intcleanupenabled = True`, startup cleanup purges cached queries of the previous version.
5. If you do not bump after a prompt/config change, tell the user that current-version cache rows may still shadow the new behavior. The same holds for the recognition cache of `vision_cache.py`.

## Verification workflow

Pick verification by blast radius, and say exactly what was not run and why when MariaDB, ChromaDB, keys or quota are unavailable.

- Python-only change: the narrowest relevant check, plus pyflakes.
- Prompt, placeholder, resolver, cache or schema-facing change: representative `/search/text2sql` questions, with `store_to_cache=false` when inspecting behaviour.
- Evaluation-sensitive change: a focused evaluator subset before a full run (`../text2sql-eval/README.md`).
- Offline checks (no API, no database): `checks/verif-114.py` (vision path), `checks/test-vision-homonyms.py` (vision identity), `checks/verif-311.py` (answer-entity guard), `checks/verif-274.py` (reasoning families), `uv run --with "fastapi>=0.104.1" --with httpx checks/verif-308.py` then `verif-114.py` (serialization), `checks/test-wikipedia-md-mentions.py` (Wikipedia Markdown and mentions).
- **Prefer the MCP tools over raw `curl` for entity-endpoint checks**, and propose them: the `get_*` tools on `https://www.vaugouin.com/mcp` return the endpoint JSON verbatim from the same deployed app, so one call validates both surfaces.

---

## Common gotchas (do NOT step on these)

### Gotcha #1 — SQL Quote Escaping
`''`, never `\'`. See *SQL handling rules*.

### Gotcha #2 — Cache API Version Filtering
Pass the formatted version to `sql_cache` helpers. See *Cache API-version filtering*.

### Gotcha #3 — ChromaDB Document IDs
`{entity}_{id}_{lang}`; the language drives the SQL field through the `languages` map.

### Gotcha #4 — Entity Variable Matching in Embeddings Cache
A cached candidate document is only accepted when **all** extracted entity variables appear in it (`if all(var in doc_entity_vars for var in entity_variables)` in `main.py`).

### Gotcha #5 — Messages Position Counter
Always increment after appending. See *Messages array invariant*.

### Gotcha #6 — Database Connection Lifecycle
Open once per request, pass it around, close in a `finally`. Never call `get_db_connection()` inside loops.

### Gotcha #7 — Custom Embedding Function Interface
`OpenAIEmbeddingFunction` must implement both `__call__()` (batch) and `embed_query()` (single query).

### Gotcha #8 — Complex Question Retry Recursion Guard
The stronger-model retry only fires when `complex_question_already_resolved = False`; the recursive call sets it to `True`.

### Gotcha #8b : An empty result is never cached (FASTAPI-TEXT2SQL-212)
All four cache tiers go through the single `store_to_cache_allowed` / `retry_store_allowed` gate; never reintroduce a bare `request.store_to_cache` in a write. Why, and the `CACHE_EMPTY_RESULTS=1` override: `README.md`.

### Gotcha #8c : Signal (d) of the no-results guard reads the SQL, not the resolution (FASTAPI-TEXT2SQL-211)
`sql_shapes.detect_person_role_collapse` is a **suspicion, not a proof**, deliberately: firing wrongly costs one stronger-model call on an already empty result, missing it hands the user a silent "no results". Before widening it, run `analyze-complex-retry-logs.py` and read its `person-role collapse` column.

### Gotcha #8d : A retried request writes two log files (FASTAPI-TEXT2SQL-241)
Skip the inner file when counting questions over `logs/`; the outer file is the complete record. See *Retries, rescues and the cache*.

### Gotcha #9 — Closed-vocabulary resolution: order, and where aspect ratios live
Canonical exact match runs **before** alias match in `_resolve_closed_vocab`, so remapping noisy DB variants onto one form means **excluding them from the canonicals in the loader query**, never adding an alias. Aspect ratios are rows of `T_WC_T2S_TECHNICAL` (`TECHNICAL_TYPE='aspect_ratio'`, dot-decimal `DESCRIPTION`), resolved through `{{Technical_formatN}}` and `T_WC_T2S_MOVIE_TECHNICAL`; there is no `Aspect_ratio` placeholder and no `T_WC_T2S_MOVIE.ASPECT_RATIO` filter. The placeholder table is in `README.md`.

### Gotcha #10 — Regex Placeholders Reject Malformed Values
See *Placeholder dispatch order*: prefix order, and `is_numeric` follows the target column's SQL type.

### Gotcha #11 — MCP Mount Path
`app.mount("", mcp_app)` (empty string), not `"/mcp"`: FastMCP's routes already live under `/mcp/...`, so mounting under `/mcp` produces `/mcp/mcp`.

### Gotcha #12 — The Fork-Join Must Be Joined
Do not move the join of `plan_entity_resolutions()`, and do not add a `return` between the fork and it. See *Pipeline scheduling and the fork-join*.

### Gotcha #13 : An image_ref is a client string, never a path (FASTAPI-TEXT2SQL-275)
Every `image_ref` goes through `uploads.parse_image_ref()` first; never join it to a folder or `basename()` it. A new format needs its signature in `uploads.py`, `_IMAGE_REF_PATTERN` and `_MEDIA_TYPES`, and only if the vision model reads it (HEIC refused: no image decoder on a path handling a stranger's bytes).

### Gotcha #14 : The vision model identifies, it never writes the question (FASTAPI-TEXT2SQL-114)
`compose_vision_question()` builds the question from `items[]` in code, so cached and fresh turns compose the same question. The path is a **pre-stage**, not a recursive re-entry (one log file): do not "harmonise" it with the retry helper. `_call_vision_llm` is OpenAI only, deliberately. See `doc/vision-pre-stage.md`; `checks/verif-114.py` asserts the invariant.

---

## Database tables and naming

Prompt-visible schema rules: `data/text_to_sql.md`. DDL: `doc/sql/` (`*-tables.sql`, and the `*-rapidfuzz.sql` generated columns and indexes RapidFuzz needs). Entity roster: `README.md` (*Database Schema Coverage*). The cache tables are described in `doc/pipeline-internals.md` and `doc/vision-pre-stage.md`. The API reads the `T_WC_T2S_*` copies (genres, also-known-as), not the `T_WC_TMDB_*` sources. When SQL-facing behaviour changes, update `data/text_to_sql.md`; edit `doc/sql/` only on request.

Naming, to preserve in any new SQL: uppercase snake case (the TMDb genre source tables keep legacy lowercase `id` / `name`); `T_WC_*` persistent, `T_WC_T2S_*` read-model, `T_WC_TMDB_*`, `T_WC_WIKIDATA_*` (staging `STG_T_WC_WIKIDATA_*`), `T_WC_WIKIPEDIA_*`; join tables `T_WC_T2S_{PARENT}_{CHILD}`; keys `ID_{ENTITY}` or `ID_ROW`, foreign keys reuse the referenced name; `DAT_*` dates, `TIM_*` datetimes, `IS_*` or legacy `DELETED` flags, `DISPLAY_ORDER`, `*_COUNT`, `*_PATH`, `_FR` suffixes and `LANG` rows, `*_NORM` / `*_KEY` RapidFuzz columns with `POPULARITY` tie-breakers; indexes keep the mixed legacy style (`IDX_*`, `UK_*`, `FK_*`, `ft_*`).

---

## Build & deployment (Docker)

Build and run are in `README.md` § *Docker Deployment* and `restart.sh`. Odd patch means Green, even means Blue; see *Version management workflow* for which checkout to restart.

### One clock: Paris time, with its offset (FASTAPI-TEXT2SQL-328)

Every date a human reads is **Europe/Paris with its offset**, through `logs.now_paris()` / `PARIS_TZ`, never a fixed `+02:00` (host and container stay on UTC). Compare `uploads.deposited_at()` / `purge_after()` with `logs.now_paris()`, never `datetime.now()` (naive, raises `TypeError`). File names before 2026-10-19 are UTC with no offset; after, Paris time, and every log dict starts with `"ts"`, which is the value to read. Details: `doc/pipeline-internals.md`.

### `logs/` and `uploads/` are shared by every colour

Both are bind-mounted from `shared_data/fastapi-text2sql/` (mounts, retentions and the ownership trap: `README.md`). A log's colour is read from the **version component of its filename**, never its path. `checks/verif-275.sh` verifies the shared mount, the cross-colour read included (`OTHER_BASE_URL=...`).

---

## Backlog (Nestor second-brain)

The prioritized backlog for this repo lives in the **Nestor** repo, not cloned alongside this one:

- This repo: `C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\fastapi-text2sql.md`
- Cross-repo dashboard: `C:\Users\vaugo\Nestor\projets\t2s-backlog\index.md`

Consult it before implementing: tasks are `FASTAPI-TEXT2SQL-NNN` with status, priority and quick-wins. These are local paths on Philippe's PC; they do not resolve on the VPS or on cloud agents.
