# AGENTS.md - Agent Guide for FastAPI Text2SQL

This file gives you the agentic context you need to work on this codebase safely. For project overview, features, install / deploy steps, API request / response examples, sample queries, and human-facing security / performance / troubleshooting material, read @README.md — that file is canonical and not duplicated here.

This is the single canonical guide for autonomous coding agents in this repository. Assistant-specific files such as @CLAUDE.md, and any future tool-specific guide such as `GEMINI.md`, should only point here and should not duplicate repository instructions.

Deeper specs live in their own files:
- @doc/AGENTS.md : index of the reference documentation, and the rule that a new entity ships with a measured threshold
- @doc/MCP.md — full MCP integration guide (tool code, resource reference, client setup, bearer token, end-to-end flow)
- @doc/RAPIDFUZZ.md — RapidFuzz setup and SQL schema requirements
- @eval/README.md — evaluation harness
- @doc/sql/*.sql — reference DDL for the database schema; treat these files as read-only unless the user explicitly asks you to edit schema documentation

- For any project update, keep documentation aligned:
  - Update `README.md` for user-facing behavior, configuration, setup, deployment, troubleshooting, or verification changes.
  - Update also docstrings for API endpoints documentation when there are changes in the API. 
  - Update this file only when agent workflow or safety context changes.

---

## Related repositories (project ecosystem)

`fastapi-text2sql` is one stage of **Agent BBB**, a multi-repository movie/TV database system owned by GitHub user `vaugouin`. All sibling repos live under `%USERPROFILE%/Code/<repo>` and at `github.com/vaugouin/<repo>`; they are interdependent stages of one pipeline that converges on a shared MySQL/MariaDB database (`T_WC_*` tables) and a ChromaDB vector store. The canonical roster of sibling repositories is kept in `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/related-repositories.txt` (documentation repo `Nestor`, outside `Code/`).

Pipeline stages:
- **Infrastructure** — `python` (shared crawler base image), `chromadb` (vector service), `reverseproxy` (NGINX TLS ingress), `chromadb-security-test` (firewall validation).
- **Acquisition** — `tmdb-crawler`, `imdb-crawler`, `sparql-crawler`, `sparql-movies-persons`, `wikidata-crawler`, `wikipedia-crawler`, `selenium-tmdb`, `download-images`, `synthetic-images` (style-locked illustrations for entities with no real image), `sqlite-plex-to-tmdb`, `movieparadise`.
- **Preprocessing → `T_WC_T2S_*`** — `tmdb-movie-preprocess`, `tmdb-person-preprocess`, `keywords-processing`.
- **Semantic index & name resolution** — `embedding-update`, `embedding-query`, `rapidfuzz_query`.
- **Serving** — `fastapi-text2sql` (NL→SQL API + MCP server), `voice-agent`, `tmdb-front` (PHP web front-end).
- **Evaluation** — `extract-movie-questions`. (`eval-text2sql` was removed; the evaluator now lives in this repo under `eval/`.)
- **Maintenance & tooling** — `plex-duplicates`, `subtitle-translate`, `powershell`, `playwright-test`.
- **Monitoring & observability** — `data-monitoring`.

**This repository's role:** Serving stage and the engine of the system. A REST API (plus an MCP server) that converts natural-language questions into SQL over the `T_WC_T2S_*` read-model, resolving entities via the ChromaDB collections (`embedding-update`) and the `rapidfuzz_query` person-name module. It is the backend behind `tmdb-front`'s `text2sql-search.php` and the `voice-agent` conversational client, and the target scored by the evaluator in `eval/`.

---

## Clients of this API — read before flipping Blue/Green

Bumping `strapiversion` moves the deployment to the other colour (even patch → Blue, `API_PORT_BLUE`, 8186; odd → Green, 8187). **Only one client follows that parity on its own.** Every other client has to be pointed by hand, and each does it differently, so the list below is the thing to check before and after a bump. Verified 2026-08-21 while moving to 1.1.18 on Blue.

| client | how it picks a colour | what to change |
|---|---|---|
| **evaluator** (`eval/text2sql-eval.py`) | derives the port from the parity of `--api-version`, [line 563](eval/text2sql-eval.py#L563), exactly like `main.py` does | nothing: pass the right `--api-version` |
| **Claude, via MCP** | `https://www.vaugouin.com/mcp`, routed by **NGINX** | the `reverseproxy` repo, repoint the upstream port |
| **tmdb-front** (PHP) | `$strtext2sqlapicolor`, **hard-coded** in `lib/global-light.inc.php` (~line 144); both URLs already sit in its `.env` as `TEXT2SQL_API_BLUE_URL` / `TEXT2SQL_API_GREEN_URL` | swap the two commented lines, then deploy the front |
| **voice-agent** | `TEXT2SQL_BASE_URL` in its `.env`, port written in full | edit the port, restart the service |

Two things worth knowing.

**tmdb-front can be tested on the other colour without switching anyone.** It accepts `?apicolor=Blue` on the URL and remembers it in a cookie, so the new version can be exercised through the real front-end, for one browser only, while everyone else stays on the live colour. That is the cheapest validation available and it needs no deployment.

**The evaluator's working copy on the VPS is `~/docker/text2sql-eval`, not a git checkout.** It holds its own `.env`, `Dockerfile` and copies of the `eval/*.py` files, which drift from this repo silently. Compare sizes before trusting a run. `~/docker/fastapi-text2sql-blue` had the same problem until 2026-08-21, when it was converted to a git clone.

**Not clients, despite appearances:** `data-monitoring` (one mention, a design analogy in its `AGENTS.md`), `extract-movie-questions` (no reference at all). `eval-text2sql` no longer exists, 404 on GitHub.

### Redeploying in place, without bumping the version

Sometimes the right call is to ship code **without** changing `strapiversion`, so the colour
does not move and no client has to be repointed. Decided this way on 2026-08-30 for
FASTAPI-TEXT2SQL-231/-232/-233, which stay on `1.1.18` on Blue.

**What it buys.** Nothing to repoint. The evaluator derives its port from `--api-version`
parity, tmdb-front keeps `$strtext2sqlapicolor` and `$strtext2sqlapiblueversion` as they are,
NGINX keeps its upstream, voice-agent keeps its `.env`. The entire four-client table above
becomes a no-op, which is the whole point.

**What it costs, and it is not small: `api_version` stops discriminating.** `GET /` answers
`1.1.18` before and after, so the standard check, "every client reports the new version", is
blind. There is no way to tell the old code from the new one by asking for a version.

**Use a capability probe instead of a version probe.** Ask for something only the new code can
answer. For -232 that is the presence of `llm_model_result_entity` in a `/search/text2sql`
payload. The cheapest form is the bare-identifier fast path, which costs no LLM call and writes
no cache entry, and whose response carries the five model fields like any other:

```bash
curl -s -H "X-API-Key: …" -X POST http://<host>:8186/search/text2sql   -H "Content-Type: application/json" -d '{"question":"tt0033467"}'   | jq '{api_version, llm_model_result_entity, answer_single_value_processing_time}'
```

A response missing `llm_model_result_entity` is the old container, whatever the version says.

**Two traps specific to redeploying in place.**

1. **`T_WC_T2S_CACHE` is filtered by API version, so old rows written by the old code stay
   live.** Harmless for -231/-232/-233, whose gpt-4o behaviour is byte-identical, and the
   evaluator sends `retrieve_from_cache: False` anyway. It would NOT be harmless for a change
   that alters generated SQL: there, reusing the version means serving yesterday's answers from
   cache and concluding the change did nothing.
2. **The execution folder collides with the baseline.** A run on `1.1.18` moving only
   `--result-entity-model` writes into the existing
   `001.001.018_en_gpt-4o_gpt-4o_gpt-4o` folder, because that model is not part of the run
   signature (FASTAPI-TEXT2SQL-234). Staying on the version makes -234 bite immediately rather
   than eventually. Measure such a change with an **offline bench**, which writes no execution
   row at all, not with the evaluator.

### Verifying the flip actually took

Changing a client's configuration is not evidence that it followed. Each one hides its
upstream differently, and on 2026-08-23, moving all three to 1.1.18, none of them could be
checked without first working out how. Here is what works, per client, so nobody has to
work it out again.

| what to check | how, and what it costs |
|---|---|
| **an instance's own version** | `curl -s -H "X-API-Key: …" http://<host>:8186/` returns `api_version` beside `bktrees_ready` (FASTAPI-TEXT2SQL-203). Free. An instance predating that ticket omits the key entirely, which is itself the answer. |
| **evaluator** | nothing to check: the port is derived from `--api-version`. |
| **voice-agent** | `curl -s https://www.vaugouin.com/voice-agent/tool/health` returns `api_version` and `api_ready` (VOICE-AGENT-166). Free. Before that endpoint existed, the version was reachable at `upstream.api_version` inside a `/tool/text2sql` answer, but reading it that way runs the whole pipeline and spends LLM tokens on a cache miss. |
| **Claude, via MCP** | call `sql_search` with a **bare IMDb id** (`{"question": "tt0033467"}`): the bare-identifier fast path answers from an indexed lookup with no LLM call and no cache write, and the payload carries `api_version`. |
| **tmdb-front** | no runtime marker is exposed to the outside; verification is at configuration level, `$strtext2sqlapicolor` **and** `$strtext2sqlapiblueversion` in `lib/global-light.inc.php`. |

**What does NOT discriminate the colours, so do not spend time on it.** The MCP `tools/list`
payload is byte-identical between Blue and Green, and so is `GET /samples`; `serverInfo.version`
in an MCP `initialize` is FastMCP's own version (3.4.7), not the API's. All three were tried on
2026-08-23 before the `sql_search` route above was found.

**Four traps, each of which cost time on 2026-08-23.**

1. **`--env-file` is read by Docker at `docker run`, not at process start.** A `docker restart`
   relaunches the container with the old value baked into its configuration. A client whose
   colour lives in an env file must be **recreated** (`restart.sh` does), never merely restarted.
   This is voice-agent's case.
2. **Do not diagnose a deployment on its first request.** Right after a restart `bktrees_ready`
   is `false` for several minutes while the warm-up runs (FASTAPI-TEXT2SQL-145), and it competes
   for CPU with the request path. Measured that day: 53 s on an entity extraction that takes
   1.1 s once warm, and one `GET /` over 15 s between answers at 0.1 s. Both resolved on their
   own. Wait for `bktrees_ready: true` before reading anything into a latency.
3. **tmdb-front remembers the colour in a one-year cookie.** The same mechanism that makes
   `?apicolor=` such a cheap pre-test, described above, is a trap afterwards: a browser that
   ever used the switch stays pinned whatever the default says, so your own browser is the
   worst place to validate the deployment. `index.php?apicolor=Blue` rewrites it.
4. **tmdb-front's per-colour version label is not decorative.** `text2sql-samples.inc.php`
   reformats `$strtext2sqlapiblueversion` into `001.001.018` to look up
   `T_WC_T2S_EVALUATION_EXECUTION`. Flipping the colour while leaving the label on the old
   version points the samples page at executions that do not exist, and it renders empty.

**A flip is complete when** every client reports the new version by the means above, and the
instance reports `bktrees_ready: true`.

---

## Where things live (file → role)

Edit at the right layer; the architecture is intentionally split.

**[main.py](main.py)** (~2460 lines) — FastAPI app, ChromaDB / DB startup, request orchestration only.
- Version utilities: `format_api_version()` ([main.py:33](main.py#L33)), `compare_versions()` ([main.py:38](main.py#L38))
- `strapiversion` lives at [main.py:105](main.py#L105) (also drives Blue/Green port parity and `MCP_INTERNAL_BASE_URL`)
- `Text2SQLRequest` / `Text2SQLResponse` Pydantic models around [main.py:214-269](main.py#L214-L269)
- `POST /search/text2sql` — main pipeline endpoint
- 18 entity detail endpoints (movies, series, seasons, episodes, persons, companies, networks, collections, topics, lists, movements, technicals, genres, groups, deaths, awards, nominations, locations). `seasons` and `episodes` are keyed on composite paths (`/seasons/{id_serie}/{season_number}`, `/episodes/{id_serie}/{season_number}/{episode_number}`) and currently read from `T_WC_TMDB_*` source tables — see [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §6.1. `genres` reads the closed-vocabulary reference table `T_WC_TMDB_GENRE` (legacy lowercase PK `id`, no `ID_WIKIDATA`, so no Wikipedia arrays).
- FastMCP instance + 17 MCP tools (`sql_search` + 16 entity tools), 1 resource (`context://database-scope`), bearer-token middleware, `app.mount("", mcp_app)` at root. The `seasons` and `episodes` HTTP endpoints do not yet have MCP wrappers (tracked in [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §3 "MCP coverage")

**[text2sql.py](text2sql.py)** — core LLM logic.
- `_call_chat_llm()` — unified multi-provider dispatcher (OpenAI / Anthropic / Google). Routes on prefix: `gpt-*`/`o1*`/`o3*` → OpenAI; `claude-*` → Anthropic; `gemini-*` → Google.
- `f_text2sql(user_question, model, ui_language)` — text-to-SQL conversion; replaces `{ui_language}` in the prompt template so the LLM generates the `answer` field in the requested language.
- `f_resolve_complex_question()` / `f_resolve_complex_question_retry_payload()` — complex-question simplification via stronger model.
- `f_build_retry_question_from_reasoning()` — deterministic retry-question composer (typed entities + years).
- `f_answer_single_value()` — direct-answer path for single-cell zero-count results.
- Hot-reloads `text_to_sql.md` and `complex_question.md` via `data_watcher`.

**[entity.py](entity.py)** — entity extraction + resolution.
- `f_entity_extraction()` — LLM-based extraction + anonymization.
- `_run_extraction_prompt()` — the prompt-call + JSON-cleanup body behind it.
- `plan_entity_resolutions()` — the expensive, SQL-independent half of resolution (regex, closed vocab, ChromaDB, RapidFuzz, row lookups). Returns `{"entities": [...], "planning_time": float}`.
- `apply_entity_resolutions()` — the cheap half: substitution into SQL / justification / answer, plus the recorded diagnostics.
- `resolve_entities()` — the two back to back; unchanged signature, still the right call when there is nothing to overlap with.
- `_match_regex_placeholder_rule()` — dispatch helper for regex placeholders.
- `_REGEX_PLACEHOLDER_RULES` — list of `(prefix, regex, is_numeric)` tuples; **order matters** (uses `startswith()`).
- Hot-reloads `entity_extraction.md` and `entity_resolution.json` via `data_watcher`. Both must exist on disk at import time: `data_watcher.register()` reads them eagerly and raises if one is missing, which kills the container at boot.

**[closed_vocab.py](closed_vocab.py)** — closed-vocabulary lookups (DB canonicals + JSON aliases + RapidFuzz typo tolerance).
- `init(connection)` — loads canonicals at startup. Called once from `main.py` startup.
- `resolve(entity, raw_value)` — string-canonical lookup (`Status_name`, `Serie_type`, `Department_name`).
- `resolve_genre(raw)` / `resolve_technical(raw)` — integer-ID lookups (`ID_GENRE`, `ID_TECHNICAL`).
- Aliases hot-reload from [data/closed_vocabularies.json](data/closed_vocabularies.json).

**[rapidfuzz_query.py](rapidfuzz_query.py)** — lexical matching.
- `search_first_match()` — exact-norm → key prefix → FULLTEXT → LIKE last resort, ranked with `fuzz.WRatio`.
- Thresholds: `AUTO_SCORE = 90`, `MIN_MARGIN = 5`, `TOP_K = 10`.
- Requires `*_NORM` / `*_KEY` generated columns and (optional) FULLTEXT index — see [RAPIDFUZZ.md](doc/RAPIDFUZZ.md).

**[sql_cache.py](sql_cache.py)** — cache helpers.
- `search_sql_cache_by_question_hash()`, `search_sql_cache_by_question_text()`, `write_sql_cache_entry()` — all take the **formatted** API version (`XXX.YYY.ZZZ`).
- `_normalize_cache_row()` — picks `SQL_QUERY` over `SQL_PROCESSED` when needed to preserve a smaller LLM-defined `LIMIT` (see `used_raw_query_to_preserve_limit`).

**[sql_shapes.py](sql_shapes.py)** : structural predicates over a generated SQL query. Pure string analysis, no DB and no LLM: it answers *what shape does this query have*, never *is it right*.
- `detect_person_role_collapse(sql_query, result_entity)` : true when a person-listing query pins the `ID_PERSON` it projects to a person named in the question, a shape that can only ever return that named person (FASTAPI-TEXT2SQL-211).
- It exists as its own module so the runtime guard in `main.py` and the measurement in `analyze-complex-retry-logs.py` share the **exact same predicate**. A guard measured with a rule other than the one it runs is a number about nothing; do not fork the logic back into either caller.

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

**[maintenance/](maintenance/)** — one-shot operational SQL, run by hand against the production DB, no code path loads it. Distinct from `doc/sql/` (reference DDL, read-only) and from `eval/assertions-*.sql` (which writes to the evaluation bank): this folder writes to operational tables, `T_WC_T2S_CACHE` first among them. Conventions and the cache facts a cleanup relies on are in [maintenance/AGENTS.md](maintenance/AGENTS.md); read it before adding or running anything there.

---

## Runtime dependencies

The app loads environment variables from `.env` via `python-dotenv`.

- MariaDB: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
- API auth: `API_KEYS` (comma-separated) or legacy `API_KEY`.
- LLMs: `OPENAI_API_KEY` for `gpt-*`, `o1*`, `o3*`, and embeddings; `ANTHROPIC_API_KEY` for `claude-*`; `GOOGLE_API_KEY` for `gemini-*`; `OPENROUTER_API_KEY` for OpenRouter-routed models.
- ChromaDB: `CHROMADB_HOST`, `CHROMADB_PORT`.
- Blue/Green and MCP: `API_PORT_BLUE`, `API_PORT_GREEN`, `MCP_API_KEY`, `MCP_INTERNAL_API_KEY`, `MCP_INTERNAL_BASE_URL`.
  - **`MCP_API_KEY` empty means `/mcp` is open.** `_verify_mcp_bearer` only enforces a bearer `if MCP_API_KEY:`, so an unset value is not a weak configuration, it is no configuration: `sql_search` and the 16 entity tools answer anyone who reaches the port. Verified on 2026-08-23, when both colours and the public NGINX route returned 200 to `tools/list` with no token and with a wrong one. Startup now logs a warning when it is empty, and that log is the only signal.
- Pipeline shape: `BKTREE_ENABLED` (default 1), `ENTITY_RESOLUTION_PARALLEL` (default 1), `CACHE_EMPTY_RESULTS` (default 0). All three are read at import time, so changing one needs a restart.

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

## Pipeline scheduling: what runs in parallel

`/search/text2sql` used to be an `async def` that never awaited anything, so every LLM call blocked the event loop and requests serialized. Three calls now go through `asyncio.to_thread`: `f_text2sql`, `f_classify_result_entity` and the answer-entity guard's regeneration. Consequences worth knowing:

- **Requests now genuinely interleave.** Per-request state (the DB connection, the messages list) is local; module state touched at request time is either read-only after startup (prompts, closed-vocab canonicals) or lock-protected (`_BKTREE_CACHE`). The prompt-cache buffer is a `ContextVar` holding a list, and `asyncio.to_thread` copies the context by reference, so appends from worker threads still reach the response.
**The fork-join (FASTAPI-TEXT2SQL-201).** Entity resolution iterates over the extraction payload, not over the placeholders found in the SQL, and `f_text2sql` only ever sees `input_text_anonymized`. The two branches are therefore independent, and `plan_entity_resolutions()` is started in a worker thread just before the text-to-SQL call, then joined right after the answer-entity guard. **The join is unconditional and must stay where it is**: the complex-question retry path below it closes the connection the worker thread is using. A plan that raised degrades to `resolve_entities()` on the sequential path.

`embeddings_processing_time` deliberately adds the overlapped planning time back in, so the metric keeps meaning "what entity resolution cost" and stays comparable with campaigns run before the fork-join. The saving appears in `total_processing_time`.

**One accepted behavioural divergence.** When a placeholder is extracted but appears nowhere in the SQL, the justification or the answer, the old resolver ran *every* strategy and logged each one before discarding the result; the planner stops at the first strategy that resolves. The three texts come out identical, only the message trace is shorter. Everything else is byte-identical, message traces included.

---

## The five LLM tasks, and what each one actually costs

There are **five** LLM calls in this pipeline, not the three the `llm_model_*` parameters
suggested until FASTAPI-TEXT2SQL-232. All five route through `text2sql._call_chat_llm`, and
each is tagged with a `cache_label` that is also its key in the prompt-cache log and its
default reasoning effort. Since -232 each has its own request selector, its own response
field naming the model that served it, and since -233 its own wall clock.

| # | Task (`cache_label`) | Call site | Fires on | Selector |
|---|---|---|---|---|
| 1 | `entity_extraction` | `entity.py:269` | 100 % | `llm_model_entity_extraction` |
| 2 | `text2sql` | `text2sql.py:518` | 100 % | `llm_model_text2sql` |
| 3 | `result_entity` | `text2sql.py:629` | 99.9 % | `llm_model_result_entity` |
| 4 | `complex_question` | `text2sql.py:663` | ~1 % | `llm_model_complex` |
| 5 | `answer_single_value` | `text2sql.py:835` | < 1 % | `llm_model_answer_single_value` |

Line numbers move; the `cache_label` does not. `grep -n 'cache_label="' text2sql.py entity.py`
is the durable way to find all five.

### Measured token profile (gpt-4o, v1.1.17–1.1.18)

Not estimates. Prompt and cache figures come from the 424 `Prompt cache (…)` records in
`logs/`; frequencies and latencies from the 1,690 executions of eval run `001.001.018`
(EN + FR). Reproduce with:

```bash
grep -rho "Prompt cache ([a-z0-9_]*): provider=[a-z]*, model=[^,]*, prompt_tokens=[0-9]*, cached_tokens=[0-9]*" logs/
```

Note the `[a-z0-9_]` character class: `text2sql` carries a digit, and a `[a-z_]` class
silently drops the single most expensive task in the pipeline from the tally.

| Task | Prompt tok | Cache hit | Uncached in | Output tok |
|---|---:|---:|---:|---:|
| `entity_extraction` | 8,555 | 73.9 % | 2,339 | ~25 |
| `text2sql` | 19,146 | 62.0 % | 7,378 | ~217 |
| `result_entity` | 577 | 0 % | 577 | ~2 |
| `complex_question` | 1,107 | 3.3 % | 1,073 | ~120 (est.) |
| `answer_single_value` | ~60 | 0 % | 60 | ~5 (est.) |

**`result_entity` never caches, and that is not a bug to fix by tuning.** At 577 tokens it
sits under OpenAI's ~1,024-token caching floor. Making it cacheable would mean padding the
prompt, which costs more than it saves.

**Tasks 1 and 2 carry 97 % of the bill.** Anything spent optimising 3, 4 and 5 is rounding
error, so measure before moving them. On gpt-4o the whole pipeline costs about **$50.69 per
1,000 requests**, which puts a full 1,690-execution evaluator run at roughly **$86**.

Latency baseline from the same run, for comparing any model swap against:

| Phase | mean | p50 | p90 | max |
|---|---:|---:|---:|---:|
| `entity_extraction` | 1.06 s | 0.91 s | 1.34 s | 7.65 s |
| `text2sql` | 3.61 s | 3.23 s | 5.39 s | 36.24 s |
| embeddings | 0.38 s | 0.02 s | 0.56 s | 99.09 s |
| query execution | 0.08 s | 0.00 s | 0.07 s | 10.66 s |
| **total** | **6.04 s** | **5.45 s** | **8.26 s** | **114.09 s** |

### Who can drive the five, and the one gap

| client | how it selects | state |
|---|---|---|
| **evaluator** (`eval/text2sql-eval.py`) | `--entity-extraction-model`, `--text2sql-model`, `--complex-model`, `--result-entity-model`, `--answer-single-value-model` | all five since 2026-08-30 |
| **tmdb-front** | request params / cookies `eemodel`, `t2smodel`, `complexmodel`, `resultentitymodel`, `answermodel`, radio groups on the settings page | all five since 2026-08-30 |
| **Claude, via MCP** | the five arguments of `sql_search` | all five |
| **voice-agent** | does not send any; takes the server defaults | unchanged |

**The gap, and it bites the evaluator only.** `T_WC_T2S_EVALUATION_EXECUTION` has columns for
`ENTITY_EXTRACTION_MODEL`, `TEXT2SQL_MODEL` and `COMPLEX_MODEL`, and none for the two new
tasks. The execution folder name is built from those columns
(`<version>_<lang>_<ee>_<t2s>_<complex>`), so **two runs that differ only in
`--result-entity-model` write into the same folder and cannot be told apart from the path**.
Until FASTAPI-TEXT2SQL-234 adds the columns, separate such runs by hand and read the per-row
truth from `api_output.llm_model_result_entity` inside each execution file, which the API now
returns and which is never wrong. The folder signature was deliberately **not** extended: the
two extra slugs would have to come from the CLI rather than from the row, which mislabels any
re-export of rows written by an earlier run sharing the same triple, and it would break
`eval/claude/*.py`, which hard-code the three-model folder shape.

### Measuring a model change on one task

Two off-production benches exist, one per classification task, and they follow the same
discipline: two configurations over the same questions in one process, no API server, no
execution row, no cache write.

| bench | task | ground truth |
|---|---|---|
| `eval/bench-entity-extraction.py` | 1, entity extraction | `ASSERTIONS_ENTITY_EXTRACTION` in the bank |
| `eval/bench-result-entity.py` | 3, answer-entity classifier | `result_entity` of executions that PASSED |

**Always measure the noise floor first, by running one model against itself.** At
temperature 0 a configuration still disagrees with itself, and until that number exists a
small delta cannot be told from a coin flip. Measured for the classifier on 2026-08-30,
`gpt-4o` against `gpt-4o`, 689 EN questions: **1 confident error on the 631 questions in
decidable classes, and 13 self-disagreements out of 689**. Eleven of those thirteen are an
abstention appearing or vanishing, which costs nothing; the run repeated a day apart gave
11 then 13, so treat the disagreement count as approximate and the confident-error floor,
1, as the number the verdict uses. Latency was identical on both sides, median 0.59 s.

So the bar for a challenger on this task is exact: **adopt it if it makes at most one more
confident error than `gpt-4o` on the decidable classes**. The FR floor has not been
measured.

**Result, `gpt-5.6-luna` against `gpt-4o`, 689 EN questions, 2026-08-30: HOLD.**

| | correct | abstained | **wrong** |
|---|---:|---:|---:|
| gpt-4o | 659 | 28 | **2** |
| gpt-5.6-luna | 678 | 5 | **6** |

On decidable classes only, which is what the verdict uses: 1 against 3, so **+2 against a
floor of 1**. Latency is a wash (median 0.59 s against 0.64 s; Luna's worst case is
actually better, 3.16 s against 13.58 s).

**This is the case the three-outcome design exists for.** A single accuracy number would
read "98.4 % against 95.6 %, adopt it", because Luna is right more often overall. It is
right more often because it abstains 23 times less, and an abstention costs nothing: the
caller falls back to the text-to-SQL model's own answer. What Luna actually does is convert
those abstentions into answers, most of them right and four of them **confidently wrong**,
and a confident error overrides a query that may have been correct. More correct and more
dangerous at the same time.

**The qualitative signal is worse than the count.** Of Luna's six, one is the known bad
label on evaluation 948, two are defensible readings of genuinely ambiguous questions
("Documentaries", "What talk shows are in the database?", both answered `genre`), and one
is the exact failure the classifier exists to prevent: **"Which people died from a heart
attack?" answered `death`**, taking the filter for the answer, when the prompt gives that
very shape as a worked example. `gpt-4o` gets it right.

**And the upside was never large.** This task costs $1.46 per 1,000 requests against Luna's
$0.12: the swap saves **$1.34 per 1,000, 2.7 % of the pipeline's $50.69**. Four extra
confident errors per 689 questions is a bad price for 2.7 %. Worth remembering when
sequencing the remaining swaps: `text2sql` ($35.33) and `entity_extraction` ($13.87) hold
97 % of the bill, so they are where a model change is worth the risk of measuring.

**French, 643 questions, floor 2: HOLD more clearly still.**

| | correct | abstained | **wrong** | wrong, decidable classes |
|---|---:|---:|---:|---:|
| gpt-4o | 618 | 23 | 2 | **0** |
| gpt-5.6-luna | 630 | 6 | 7 | **5** |

Same shape as English, wider gap: +5 against a floor of 2, and `gpt-4o` makes **no**
confident error at all on the decidable classes in French (both of its errors are in the
unscored tail). Latency again a wash.

**The FR floor is 2 where the EN floor is 1**, and `gpt-4o` is a little less accurate in
French across the board. That is the documented EN/FR gap showing up in this task too, and
it means a French comparison tolerates more slack before it means anything.

**Running both languages is what turns the result from a count into a diagnosis.** Three of
Luna's failures reproduce in both:

| eval | question | truth | Luna |
|---|---|---|---|
| 2467 | "Which people died from a heart attack?" / "Quelles personnes sont mortes d'une crise cardiaque ?" | person | **death** |
| 2321 | "Documentaries" / "Documentaires" | movie | **genre** |
| 825 | the Gendarme de Saint-Tropez collection | (differs, see below) | wrong both ways |

Eval 2467 in both languages is the finding. It is not noise, it is not an ambiguous label,
and it is exactly the confusion this classifier exists to prevent: the cause of death is the
**filter**, the people are the answer, and the prompt gives that shape as a worked example.
Luna takes the filter for the answer in both languages; `gpt-4o` gets it right in both.
Together with the `-> genre` pair, the failure mode is systematic: **a weaker model
generalises "the words in the question" into "the type of the answer"**, which is the single
thing this task must not do.

**A ground-truth caveat the two runs expose, and it is new.** The same evaluation carries a
**different label in EN and FR on 5 of 622** shared questions (825, 948, 2179, 2323, 2457).
The labels come from two separate executions, so this is the pipeline's own EN/FR divergence
leaking into the ground truth. Half of Luna's raw errors land on those five. The verdict is
unaffected, because only one of them (825) sits in a decidable class and the FR gap is +5
against a floor of 2 with or without it, but any future reading of a small delta must check
whether it rests on one of these.

**Where to look next on this task, if it is worth revisiting:** the `-> genre` and
`-> death` errors all say the same thing, that the prompt's "a genre used to scope a search
is a filter, not the answer" guidance is not emphatic enough for a weaker model. That prompt
is inline in `text2sql.f_classify_result_entity`, not a hot-reloaded file, so testing a
rewrite means a code change and four bench runs, before and after in both languages. Given
the task is 2.7 % of the bill, that is a poor use of the next hour compared with benching
`entity_extraction` or `text2sql`.

**Three outcomes, never one accuracy number**, and this is the part that transfers to any
future classifier. *Correct*; *abstained*, where the caller falls back to the pre-existing
behaviour so nothing is lost; and *confidently wrong*, a different valid label, which is
the only outcome that overrides a query that may have been right. A model that abstains
more is not a model that errs more, and one accuracy figure hides exactly that difference.

**The label distribution decides how the result can be read.** `movie`, `person` and
`serie` carry 90 % of the classifier's ground truth, so answering "movie" every time
already scores 55.2 %. Eleven classes have fewer than 30 examples. The bench therefore
prints the majority baseline beside every score and refuses a percentage below
`--min-decidable`, listing those classes as counted-but-unscored instead. Same lesson as
the ChromaDB `lists` check that returned OK at 9 % on 23 documents: a proportion computed
on a handful of rows cannot discriminate, and a check that reports "fine" from too little
data is worse than no check.

**`--limit` samples round-robin across classes, rarest first, not off the top.** The
exports open on a long run of `movie` questions, so a head slice of 12 was twelve movies
and a perfect score. The stratified version surfaced something on its first 14-question
run that the head slice could never have reached, and it turned out to be about the
ground truth rather than about the model. See below.

**A passing execution proves its assertions were satisfied, NOT that its `result_entity`
is the label a human would pick.** That distinction is the one real weakness of harvesting
labels this way, and it showed up immediately. Evaluation 948 is the single `serie_image`
row in the EN set; its question is `Serie game of thrones`, which asks for nothing about
images, yet the execution ran against `T_WC_T2S_SERIE_IMAGE` and passed. `gpt-4o` answers
`serie`, which is defensible, and the bench scores it a confident error. So a
confident-error line on a class with n=1 is a prompt to go read the case, never a verdict
on the model. This is also why `--min-decidable` exists: at n=1 a single questionable
label is 100 % of the class.

**Bench artefacts are gitignored** (`eval/data/bench/`), for the same reason as the
execution exports: they carry the evaluation questions verbatim.

**Both benches preflight one call per model and abort before spending anything.** The
failure they guard against is not a crash but a plausible-looking report: the classifier
turns an exception into `""`, which scores as an abstention, and entity extraction turns
one into `{"error": ...}`, which `score()` maps to `None` and which therefore leaves the
DENOMINATOR rather than counting against the model. A configuration failing on every call
reads as "abstained a lot" in one and "scored: 0" in the other; failing on half reads as a
perfect record on the survivors. The entity bench now also states, at the top of its report
rather than at the bottom, how many questions were dropped and warns past a tenth.

**They do not run in the same places.** `bench-result-entity.py` reads its ground truth
from the execution exports on disk and needs **no database**, so it runs anywhere the repo
is checked out. `bench-entity-extraction.py` reads the bank from MariaDB and therefore only
runs where the database is reachable, which is not a developer laptop. Plan the entity work
on the VPS or behind a tunnel.

## Reasoning models reject `temperature` (FASTAPI-TEXT2SQL-231)

**The trap, and it is a hard failure, not a degradation.** Every one of the five tasks passes
`temperature=0` on purpose. Reasoning models, the whole o-series and the entire GPT-5.x family
including the 5.6 Sol / Terra / Luna tiers, accept only the default and answer **HTTP 400,
`Unsupported value: 'temperature' does not support 0 with this model`**. Before -231 the model
router at `text2sql.py` matched anything starting with `gpt-` and sent it to
`chat.completions` with the parameter attached, so a swap as innocent as
`gpt-4o` → `gpt-5.6-terra` failed on the **first request of all five tasks**. Four call sites
fed it: `_complex_question_temperature`, which exempted only `o1`/`o3`, plus three hard-coded
`temperature=0` arguments in `entity.py` and `text2sql.py`. Those arguments are still there and
still correct: the guard is central, in `_call_chat_llm`, so no caller had to learn about model
families.

**The fix.** `_openai_sampling_kwargs(model_norm, temperature, cache_label, reasoning_effort)`
builds the sampling half of the call per model family. Non-reasoning models keep
`temperature` and their behaviour is byte-identical. Reasoning models get `reasoning_effort`
and **no `temperature` at all**: the parameter is omitted rather than pinned to `1`, because
passing the default explicitly is still rejected on some routes.

**`reasoning_effort` is the real cost and latency knob, and it dwarfs the choice of tier.**
The same model spans roughly **1.8 s to first token at `low` and 115 s at `max`**, and
reasoning tokens are billed at the output rate, so effort multiplies the output bill severalfold
before the tier's price list is even consulted. `_DEFAULT_REASONING_EFFORT` therefore gives
`minimal` to the four tasks on the 100 % path, where the p50 is 5.45 s end to end and there is
no room for a thinking budget, and `medium` only to the complex-question pair that fires on
~1 % of requests. Override per call with the `reasoning_effort` argument; `"default"` omits
the parameter and lets the API decide.

**Two things NOT to assume.**

- **GPT-5.x goes through `chat.completions`, not the Responses API.** The `responses.create`
  branch is now restricted to the o-series. The prompt-cache accounting this pipeline reports
  is the one measured on `chat.completions`, and the two routes name their usage fields
  differently.
- **Reported incompatibility, not yet hit here:** function tools combined with
  `reasoning_effort` are refused for `gpt-5.6-sol` on `/v1/chat/completions`. This pipeline
  uses neither tools nor `response_format`, so it does not bite today. It will the moment
  someone adds structured outputs.

---

## Entity resolution thresholds (`min_fuzz_ratio`)

Every resolver now carries a rejection threshold. Do NOT adjust one by hand on the strength of a
single bad case: each value is the midpoint of a measured equivalence interval, and the method
that produced it, the data it used and the traps it walked into are written up in
[doc/entity-resolution-thresholds.md](doc/entity-resolution-thresholds.md). Re-run
[eval/bench-entity-resolution.py](eval/bench-entity-resolution.py) and read the interval instead.

Three things from that document are worth knowing before touching this area at all.

The gate lives on **both** paths since 2026-08-25. `min_fuzz_ratio` used to be read only in the
embeddings branch, so declaring it on a rapidfuzz strategy did strictly nothing, which is why
`Person_name` could never fail and invented names resolved to real people. An exact normalized
match always passes; a rejection falls through to the next strategy and then to the raw fallback.

The **ratio, not the distance**, and that was measured: 42 total errors against 94 for the vector
distance over the twelve embeddings types, the conjunction saving only seven more at the price of
a second parameter per entity. The expectation was the opposite.

The `Person_name` alias strategy carries a **provisional, unmeasured** 90.0. That table was
unreachable while the first strategy always resolved, and a strategy that cannot be reached cannot
be measured, so calibrating it needs a second bench run after deployment. The two stages cannot be
collapsed.

## The indexed document is not the name (`document_name_separator`)

Some collections index `name + " : " + description`, which helps the vector search a great deal
and ruins the lexical one. Measured 2026-08-25: "Blaxploitation" against
"Blaxploitation: Here is the list of..." scores **2.3** on `fuzz.ratio`, a perfect match graded as
a disaster. 97% of `Death_name` candidates carry a description, 82% of `Nomination_name`, 81% of
`Award_name`, 21% of `Movement_name`.

Do NOT strip descriptions out of the embeddings to fix this. They are what lets "crise cardiaque"
find "cardiac arrest", which the bare name cannot do. The description belongs in the vector space
and has no business in an edit-distance ratio; the defect was in the score, not the indexing.

`document_name_separator` declares the separator **per entity** in
[data/entity_resolution.json](data/entity_resolution.json), and only the part before it is
compared. Per entity and never globally, because a name can legitimately contain the separator:
splitting "Star Trek: The Next Generation" blindly truncates it to "Star Trek", and 12% of
`Movie_title` candidates carry a colon. The stripped name is also what gets reported as the
candidate, so bench and logs show what was really compared.

The durable fix belongs to `embedding-update`: store the bare name in the ChromaDB **metadata**
alongside the document, and no separator can mislead anyone again.

## Descriptor words in entity scoring (`score_stopwords`)

A word shared by the value sought and the candidate found inflates the similarity without
carrying any identifying signal. Measured 2026-08-24: `"wagonlit collection"` against
`"Life Collection"` scores **76.5**, clears `Collection_name`'s threshold of 72, and returns
three films for a collection that does not exist. Strip the descriptor from both sides and the
same pair scores 33.3.

Moving from `WRatio` to `fuzz.ratio` had already been tried against this family of defect
(FASTAPI-TEXT2SQL-062, the "Mad Max collection" case) and was not enough: the descriptor
survives the change of metric, only removing it works.

`score_stopwords` declares that list **per strategy** in
[data/entity_resolution.json](data/entity_resolution.json), and `entity.py` applies it to both
sides before scoring. `fuzz_ratio_raw` in the response keeps the pre-strip score so the effect
stays auditable.

**Per entity, never global, and this is the whole point.** What is generic for a collection is
identifying for an award. `Collection_name` and `Topic_name` are configured, on measured
evidence from 3404 harvested values (`collection` x48 and `trilogy` x37 out of 128 collection
values). `Award_name` is deliberately NOT: it carries `award` x28, `academy` x25 and `best` x19,
but "Academy Award for Best Picture" is the canonical name, and stripping those words would draw
distinct awards together instead of separating them. Same for `Movement_name` ("New Wave") and
`List_name` ("Top 250", "Sight & Sound").

Adding a list to a type that has a `min_fuzz_ratio` changes the gate, so measure before and
after with [eval/bench-entity-resolution.py](eval/bench-entity-resolution.py). Note the effect
runs both ways: neutralisation closed a false positive (76.5 to 33.3) and a false NEGATIVE in
the same move ("star wars universe" against "Star Wars Collection", 57.9 to 100, where 57.9 sat
below the threshold and would have been refused).

## Adding an indicator to the response

The measurement chain is already generic, and knowing that saves most of the work.
`eval/text2sql-eval.py` stores the **entire** HTTP response body in
`T_WC_T2S_EVALUATION_EXECUTION.JSON_RESULT`, and the export phase copies that JSON verbatim
into `api_output` in `/shared/evaluation_execution/`. So:

1. **Add the field to `Text2SQLResponse` and populate it.** That alone puts it in the API
   answer, in the database and in the export. Give it a default so the early-return response
   sites (cache miss, bare-identifier fast path, complex-question retry) keep working.
2. **Add a dedicated column only if you need to aggregate it in SQL.** The columns are a
   duplicate of what `JSON_RESULT` already holds, kept so a campaign can be sliced without
   `JSON_EXTRACT` on every row (the PHP graphs under `eval/lib/` rely on them). That step is
   four edits, not one: [doc/sql/T2S_EVALUATION-tables.sql](doc/sql/T2S_EVALUATION-tables.sql)
   for the reference DDL, a migration under [maintenance/](maintenance/) for the live table,
   the write in `eval/text2sql-eval.py`, and the `timings` block of the export in that same
   file. That fourth one is a hand-kept list and does **not** inherit from `JSON_RESULT` the
   way `api_output` does, so forgetting it is invisible: the export keeps writing, simply
   without the column. It happened, and 1.1.18 exports described a five-step pipeline while
   six columns existed. `eval/README.md` shows the block, so it drifts too.
3. **Document it in `README.md`**, which describes the response in three separate places: the
   example JSON, the detailed field list and the summary list. All three drift on their own.

Rows written before an indicator existed keep `NULL`. That is the point: `NULL` says "not
measured then", `0` would claim "measured at zero".

---

## Run pyflakes before committing Python, and read the "undefined name" lines

```bash
uv run --with pyflakes python -m pyflakes *.py | grep "undefined name"
```

**Why this is written down.** On 2026-08-29 a refactor moved
`_score_stopwords = search_cfg.get("score_stopwords")` into a new closure under another name and
left one reader behind, in the `match_scores` append. That line is unconditional, so **every**
resolution reaching the embeddings branch raised `NameError` and returned 500: `Collection_name`,
`Topic_name`, `Network_name`, `Company_name`, the titles, the awards. A total outage on that path,
shipped and only found on the next restart.

**Neither `ast.parse` nor `import` can catch it.** Both passed on the broken file: a name lookup
inside a function body is resolved at call time, and no test imported that branch. `pyflakes`
flagged it in under a second, by name and line number. The one-line command above is the cheapest
guard this repo has against a whole class of defect, and the class is specific: **a refactor that
moves a variable's definition is not verified by re-reading the new block, but by finding who else
read the old name.**

Read the `undefined name` lines as blocking. The `assigned to but never used` lines are worth a
look too, since they usually mean a refactor left something behind, but they do not break anything.

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

[data/text_to_sql.md](data/text_to_sql.md) (drives LLM-generated SQL for `/search/text2sql`) and the 18 entity detail endpoints in [main.py](main.py) (hand-written SQL for `/movies/{id}`, `/persons/{id}`, `/seasons/{id_serie}/{season_number}`, etc., plus their MCP `get_*` proxies where they exist) are two independent SQL surfaces over the same data. They are kept in sync by hand, not enforced by code.

When working on either side, scan the other for divergence and **surface any discrepancy to the user** — do not silently patch one to match the other, and do not treat this as an automatic refactor target. Default expectation: `data/text_to_sql.md` is the spec; the endpoints should match unless the user says otherwise. Categories of drift to watch for:

- **Filter predicates** — e.g. the `CAST_CHARACTER NOT IN (...)` exclusion for non-documentary movie cast ([data/text_to_sql.md:850-851](data/text_to_sql.md#L850-L851)), `IS_DOCUMENTARY` / `IS_MOVIE` toggles, Criterion Collection criteria, technical / genre / aspect-ratio filters.
- **Sort order** — the "Default Sorting" section (around line 876+) governs both: `ORDER BY` inside endpoint SQL, and the directional rules (e.g. movies-for-a-person vs persons-for-a-movie) that drive what the text-to-SQL prompt emits.
- **Included related lists and their key order** — the order in which related-entity lists appear in entity detail responses should track the order of rules in the "Default Sorting" section.
- **Result columns**: the `Result Columns` section of [data/text_to_sql.md](data/text_to_sql.md) specifies which columns each entity surface should expose. Its opening subsection, *Aggregated questions: the contract survives `GROUP BY`*, is the one to re-read before touching anything about counting or ranking: a `COUNT` query that drops the entity's image column (`PROFILE_PATH` / `POSTER_PATH` / `LOGO_PATH`) returns correct rows the client cannot render, and one that omits `GROUP BY` entirely collapses the ranking to a single arbitrary row (FASTAPI-TEXT2SQL-191 and -186).

When you spot a divergence, describe it (which side has which behavior, where in the spec/code), and let the user decide which side is authoritative for the fix.

### Entity endpoint localization (`ui_language`)

Every entity detail endpoint and its MCP `get_*` proxy take a `ui_language` parameter (query param for REST, tool arg for MCP), normalized by `normalize_ui_language()` to `en`/`fr` (default/fallback `en`). Responses are localized by `localize_response()`, which recursively collapses each `<COL>`/`<COL>_FR` pair into the single canonical `<COL>` (French value when present, English fallback) and drops the `_FR` keys — on both the primary entity and nested related rows. The real localizable columns are `MOVIE_TITLE`, `SERIE_TITLE`, `TOPIC_NAME`, `LIST_NAME`, `COLLECTION_NAME`, `MOVEMENT_NAME`, `AWARD_NAME`, `NOMINATION_NAME`, `GROUP_NAME`, `DEATH_NAME`, `ITEM_LABEL`, and technical `DESCRIPTION`; person `BIOGRAPHY` and company `DESCRIPTION` have no `_FR` variant. `SERIE_TITLE_FR` exists on `T_WC_T2S_SERIE` (and is collapsed into `SERIE_TITLE`): the base `/series/{id}` row picks it up via `SELECT *`, and every nested series SELECT (parent-series nav stubs in `/seasons` & `/episodes`, and the series lists in `/persons`, `/companies`, `/networks`, `/collections`, `/movements`, `/awards`, `/nominations`, `/locations`) explicitly selects `SERIE_TITLE_FR` alongside `SERIE_TITLE`. `_fetch_wikipedia_images` / `_fetch_wikipedia_content` filter by `ui_language` with English fallback. When adding a nested related-entity SELECT that exposes a localizable name/description column, also select its `_FR` variant so `localize_response()` can resolve it. Usage logs (`logs.log_usage`) capture the pre-localization row, so logged responses retain both language columns.

`apply_localized_main_image()` ([main.py](main.py)) is the image counterpart to `localize_response()`: image paths have no `_FR` column, so for a non-default `ui_language` it overrides the **top-level** entity's canonical main-picture path with the `IMAGE_PATH` of the main (lowest `DISPLAY_ORDER`) related image whose `LANG` matches the requested language, falling back to the canonical path when no localized image exists. It runs after `logs.log_usage` (so logs keep the canonical path) and before `localize_response`. Wired on the entities that carry a language-tagged image array: `/movies/{id}`, `/series/{id}`, and `/seasons/{...}` (`posters` → `POSTER_PATH`) and `/persons/{id}` (`portraits` → `PROFILE_PATH`).

`apply_localized_related_images(conn, grouped_rows, ui_language)` ([main.py](main.py)) extends the same idea to **nested related rows** (the "collections" embedded in each detail response — `cast`, `crew`, `movie_cast`, `movies`, `series`, `persons`, the parent-series/season nav stubs, the `seasons` array, …). Nested rows carry a main image path but not their own image array, so the localized path is fetched in one batched query per entity kind. `grouped_rows` maps a kind in `_RELATED_IMAGE_SOURCES` (`movie` → `T_WC_T2S_MOVIE_IMAGE`/`ID_MOVIE`/`poster`/`POSTER_PATH`; `serie` → `T_WC_T2S_SERIE_IMAGE`/`ID_SERIE`/`poster`/`POSTER_PATH`; `person` → `T_WC_T2S_PERSON_IMAGE`/`ID_PERSON`/`profile`/`PROFILE_PATH`; `season` → `T_WC_TMDB_SEASON_IMAGE`/`ID_SEASON`/`poster`/`POSTER_PATH`) to a list of row collections (each a list of dicts, or a single dict stub). For each id it keeps the lowest-`DISPLAY_ORDER` image in the requested `LANG`, overwriting the row's path field (canonical kept as fallback). It runs in the same slot as `apply_localized_main_image` (after `logs.log_usage`, before `localize_response`) and is a no-op for the default language. Wired on every detail endpoint that returns localizable person/movie/serie/season nested rows. When adding a nested array of movie/serie/person/season rows, add it to that endpoint's `apply_localized_related_images` call so its main picture is localized too. Episodes are excluded — `STILL_PATH` frames are not language-specific.

### Entity endpoint data freshness (`data_freshness`)

Every entity detail endpoint returns a top-level `data_freshness` block on its **full** response (not on a targeted `?collection=` page), built by `_build_data_freshness(cursor, row, record_source, ui_language)` ([main.py](main.py)) right beside the `_fetch_wikipedia_*` calls. Nothing in a response is fetched live, so this block is the only way a consumer (`voice-agent`) can date an answer.

Keys: `record_source`, `record_updated_at` (base row `TIM_UPDATED`), `tmdb_updated_at`, `wikidata_updated_at` (`TIM_WIKIDATA_COMPLETED`), `wikipedia_updated_at` / `wikipedia_crawled_at` / `wikipedia_lang`.

**The `record_source` argument is the thing to get right when adding or changing an endpoint.** It is what licenses labelling `TIM_UPDATED` as a TMDb date:

- `RECORD_SOURCE_TMDB`: `/movies`, `/series`, `/seasons`, `/episodes`, `/persons`, `/companies`, `/networks`. `tmdb-movie-preprocess` copies `TIM_UPDATED` **verbatim** from the `T_WC_TMDB_*` source row into the `T2S_*` read-model row (`INSERT ... SELECT ... TIM_UPDATED ... FROM T_WC_TMDB_MOVIE`, and the same shape for serie / person / company / network / season / episode), so on these entities `TIM_UPDATED` **is** the TMDb refresh datetime. `tmdb_updated_at` mirrors it.
- `RECORD_SOURCE_WIKIDATA`: `/collections`, `/topics`, `/lists`, `/movements`, `/technicals`, `/groups`, `/deaths`, `/awards`, `/nominations`, `/locations`. Built from Wikidata (`wikidata-crawler` sets `TIM_WIKIDATA_COMPLETED`; `T_WC_T2S_ITEM` is rebuilt from `T_WC_WIKIDATA_ITEM_V1`), so `tmdb_updated_at` **must stay null**. Labelling a Wikidata refresh as a TMDb date would be a lie a voice client repeats out loud.
- `RECORD_SOURCE_REFERENCE`: `/genres` only. `T_WC_TMDB_GENRE` is a static reference table with no timestamp columns, so every field comes back null.

`_fetch_wikipedia_freshness()` reads `T_WC_WIKIPEDIA_PAGE_LANG` (`LAST_SUCCESS_AT` = last *successful* fetch = the real data date of the served content; `LAST_CRAWLED_AT` = last attempt) via `_resolve_wikipedia_page_row()`, which **mirrors the language resolution of `_fetch_wikipedia_content`**: the requested language wins only when it actually has sections, English otherwise. If you ever change the fallback rule in `_fetch_wikipedia_content` or `_fetch_wikipedia_images`, change it in `_resolve_wikipedia_page_row` too or `wikipedia_lang` will date the wrong language's content *and* `wikipedia_page` will credit the wrong article. Entities whose base table has no `ID_WIKIDATA` (`companies`, `networks`, `genres`) skip the query entirely and get nulls.

### Entity endpoint Wikipedia page reference (`wikipedia_page`)

The 15 detail endpoints that can serve `wikipedia_content` also return a top-level `wikipedia_page` object (`lang` / `title` / `url`, from `WIKIPEDIA_PAGE_TITLE` and `WIKIPEDIA_PAGE_URL`), built by `_fetch_wikipedia_page()` and attached by `_attach_wikipedia_page()` right before `logs.log_usage`. It exists because displaying `wikipedia_content` requires CC BY-SA attribution to the source article, and a client holding only an `ID_WIKIDATA` cannot derive that URL: the article title is not the entity title and differs per language.

Three rules to preserve when touching this:

- **One resolution, two consumers.** `_resolve_wikipedia_page_row()` is the single home of the language resolution; `_fetch_wikipedia_freshness()` *dates* the content and `_fetch_wikipedia_page()` *credits* it from the same row. The invariant `wikipedia_page.lang == data_freshness.wikipedia_lang` must hold on every response, and it is the cheapest regression check available (internal, no fixture needed). Do not add a third resolution.
- **Resolve on the content, never on the page row's existence.** A page row can exist for a language that carries **zero sections**, so an entity can have a French page row while the served prose falls back to English. Crediting the French article there would be a false attribution, which is worse than no credit: it states something untrue about the source of the text on screen.
- **Absent, not null.** The key is omitted when the entity has no page (or the row has no title/url), so a client never renders a hollow credit. Detail responses only: never on `/search/text2sql`, never on related-entity rows, and not on a targeted `?collection=` page.

`verify_wikipedia_page.py` at the repo root checks all of the above against a deployed API (it discovers one live id per entity type by walking a seed movie's relations, and reports what it could not reach as SKIPPED rather than passing it).

All source columns live in allowed tables (`T2S_*`, `TMDB_*` only where seasons/episodes already read from them, `WIKIPEDIA_*`), so this respects the restricted-DB table-scope contract (DATA-DISTRIBUTION-008) without new promotions.

### Entity endpoint collection pagination (`collection` / `page` / `rows_per_page`)

Every entity detail endpoint (and its MCP `get_*` proxy) paginates its **related-entity lists** so large results stay bounded. Each endpoint declares a local `pcollections` registry mapping `collection_name -> (sql, params, image_kind)`; the shared driver `_run_collections()` ([main.py](main.py)) runs it. The registry is the single source of truth and is used for both modes:

- **Untargeted** (`collection is None`): every list is fetched at page 1 (using the requested `rows_per_page`); the response is assembled as before plus a top-level `pagination` block (`name -> {total, page, rows_per_page, returned}`). Non-paginated extras (scalar lists, image arrays, `videos`, Wikipedia arrays) are fetched only in this branch.
- **Targeted** (`?collection=<name>`): only that list is fetched at the requested `page`; `_targeted_collection_response()` returns a lean payload (identifier echo + that one list + its `pagination`), then runs the usual `apply_localized_related_images` / `localize_response`. An unknown name → HTTP 400.

Each registry SQL **must** select `COUNT(*) OVER() AS _TOTAL_COUNT` (one-query window total, stripped by `_paginate_collection`), carry a deterministic `ORDER BY` with a unique tiebreaker (usually the related entity `ID_*`), and omit its own `LIMIT`/semicolon (the helper appends `LIMIT %s OFFSET %s`). `cast`/`crew` (movies/series/seasons/episodes) and `movie_cast`/`movie_crew`/`series_cast`/`series_crew` (persons) are split into separate per-`CREDIT_TYPE` queries with the `CAST_CHARACTER_EXCLUSIONS` filter pushed into SQL (movies: only when non-documentary; persons `movie_cast`: per-row on the host movie's `IS_DOCUMENTARY`). The `image_kind` (a `_RELATED_IMAGE_SOURCES` key or `None`) drives related-image localization via `_localized_image_groups()`. Constants `COLLECTION_ROWS_PER_PAGE_DEFAULT` (50) / `COLLECTION_ROWS_PER_PAGE_MAX` (200) live near the helpers. **When adding a new nested related-entity list, add it to the endpoint's `pcollections` registry** (not as a one-off `cursor.execute`) so it is paginated and localized consistently. Note: `COUNT(*) OVER()` requires MariaDB ≥ 10.2.

**MCP alignment (keep the two surfaces in sync).** The MCP `get_*` tools relay the endpoint's JSON **verbatim** (`_mcp_get` → `return r.text`, no field filtering), so a new collection's **data** shows up in MCP automatically — no code needed. But each MCP tool's **docstring** (the description an MCP client actually sees) is hand-maintained, so when you add or rename a returned collection you **must also list it in that tool's docstring** — both in the relations enumeration *and* among the valid `collection` values for targeted pagination — or the collection stays invisible to MCP clients even though the data is present. The docstrings are the MCP contract; treat them like the OpenAPI docstrings on the REST endpoints and update both together.

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

**Confidence gating (opt-in, per strategy).** By default both search modes always substitute their best candidate — a degraded shortlist or a near-miss then produces a *confidently wrong* entity rather than an error. Three optional keys make a strategy fail safe (fall through to the next strategy, then to raw fallback / ambiguous) instead:
- `min_fuzz_ratio` (embeddings): reject the chosen candidate when `fuzz.ratio(query, candidate) < min_fuzz_ratio`. Uses `fuzz.ratio` (edit distance), **not** `WRatio` — titles sharing a suffix (e.g. "… Collection") inflate WRatio's token_set component and let unrelated entries through. An exact normalized document match always passes. When rejected, a diagnostic message logs the chosen candidate and the top-5 shortlist with distances.
- `max_distance` (embeddings): reject when the ChromaDB distance of the chosen candidate exceeds this. Weak discriminator for short proper nouns (near-duplicates sit at similar distances), so prefer `min_fuzz_ratio`; combine both only when distances are meaningful for that collection.
- `require_confident` (rapidfuzz): only accept an exact / high-confidence auto-correct (`auto` True); a low-confidence lexical guess falls through. Off by default so `Person_name` keeps always-resolve behaviour.

`Collection_name` uses both: a `require_confident` **rapidfuzz** strategy first (exact-normalized DB match — robust and independent of ChromaDB/RAM state), then the gated **embeddings** strategy (`min_fuzz_ratio: 72`) as a semantic/French fallback. The rapidfuzz strategy needs the generated columns in [doc/sql/T2S_COLLECTION-rapidfuzz.sql](doc/sql/T2S_COLLECTION-rapidfuzz.sql); until that migration runs it no-ops and only the embeddings strategy is active.

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
- For RapidFuzz behavior, check @doc/RAPIDFUZZ.md and the relevant `doc/sql/*-rapidfuzz.sql` generated-column/index requirements.
- **Prefer the MCP tools over raw `curl` for entity/detail checks, and propose MCP as the verification path.** The MCP server is the *same deployed app* as the REST API (mounted at `/mcp`, same `strapiversion`, same Blue/Green process) and its `get_*` tools return the endpoint JSON **verbatim**, so exercising a detail endpoint through its MCP tool (e.g. `get_movie(id=…)` on `https://www.vaugouin.com/mcp`) validates both surfaces at once and needs no API-key/URL juggling. When suggesting how to verify a detail-endpoint change, propose an MCP-tool call rather than a `curl`. This relies on the MCP tools staying aligned with the REST endpoints — see *Entity endpoint collection pagination → MCP alignment*.
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

### Gotcha #8b : An empty result is never cached (FASTAPI-TEXT2SQL-212)
A query returning **0 rows on page 1** is written to no cache tier: not the exact row, not the anonymized row, not the embeddings row, and not the row the stronger-model retry writes for the original question. All four go through the single `store_to_cache_allowed` / `retry_store_allowed` gate, so do not reintroduce a bare `request.store_to_cache` in a write. The reason is not tidiness: the **anonymized** row freezes the whole template, so one defective query poisons every entity pair on that pattern. Measured on 2026-08-25, a broken "costumière du film {{Movie_title1}} avec {{Person_name1}}" was written at 18:05:03 and served back verbatim at 18:06:36. `CACHE_EMPTY_RESULTS=1` restores the old behaviour. A page **beyond the first** returning empty is unaffected: that only means the result set ended.

### Gotcha #8c : Signal (d) of the no-results guard reads the SQL, not the resolution (FASTAPI-TEXT2SQL-211)
The three original signals of **-156** all watch **entity resolution**, so an empty result whose entities all resolved was declared authoritative. Signal (d) is the first one to look at the query itself, via `sql_shapes.detect_person_role_collapse`. It is a **suspicion, not a proof**, and that is deliberate: firing wrongly costs one stronger-model call on a result that was **already empty**, while missing it hands the user a silent "no results" on an answerable question. Keep that asymmetry in mind before tightening it. Before widening it, run `analyze-complex-retry-logs.py`, whose `person-role collapse` column reports how many blocked empties, and how many **authoritative** ones, the signal moves. Local corpus on 2026-08-26: 4 fires out of 438 logs, all 4 the same defect, 2 of them previously classified AUTHORITATIVE.

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

### Gotcha #12 — The Fork-Join Must Be Joined
`plan_entity_resolutions()` runs in a worker thread holding **this request's** DB connection. The complex-question retry path calls `connection.close()`. The join therefore sits right after the answer-entity guard, before any path that can close the connection or return early. Do not move it, and do not add a `return` between the fork and the join.

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
- [doc/sql/T2S_PERSON-rapidfuzz.sql](doc/sql/T2S_PERSON-rapidfuzz.sql), [doc/sql/T_WC_TMDB_PERSON_ALSO_KNOWN_AS-rapidfuzz.sql](doc/sql/T_WC_TMDB_PERSON_ALSO_KNOWN_AS-rapidfuzz.sql), and [doc/sql/T2S_COLLECTION-rapidfuzz.sql](doc/sql/T2S_COLLECTION-rapidfuzz.sql) — generated columns, indexes, and FULLTEXT setup required by RapidFuzz.

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

### Which Blue/Green slot is live — read it off the version's patch number

The live color is determined by the **parity of the `strapiversion` patch number** (the `ZZZ` in `X.Y.ZZZ`), so you never have to guess which slot to restart:

- **Odd** patch → **Green** is live (mnemonic: "Green" has 5 letters — odd). E.g. `1.1.17` → Green.
- **Even** patch → **Blue** is live (mnemonic: "Blue" has 4 letters — even). E.g. `1.1.16` / `1.1.18` → Blue.

Restarting a `*.py` change therefore means running the script for the color matching the current version's parity: `restart-green.sh` for an odd patch, `restart-blue.sh` for an even one. This also explains why an explicit `strapiversion` bump flips the parity — the deploy moves to the other color's port.

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
