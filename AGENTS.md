# AGENTS.md - Agent Guide for FastAPI Text2SQL

This file gives you the agentic context you need to work on this codebase safely. For project overview, features, install / deploy steps, API request / response examples, sample queries, and human-facing security / performance / troubleshooting material, read @README.md — that file is canonical and not duplicated here.

This is the single canonical guide for autonomous coding agents in this repository. Assistant-specific files such as @CLAUDE.md, and any future tool-specific guide such as `GEMINI.md`, should only point here and should not duplicate repository instructions.

Deeper specs live in their own files:
- @data/AGENTS.md : the hot-reloaded prompts and configuration, what each file must keep, and the three rules twinned between `complex_question.md` and `vision_identification.md` that must stay different
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
- **Infrastructure** — `python` (shared crawler base image), `chromadb` (vector service), `reverseproxy` (NGINX TLS ingress), `chromadb-security-test` (firewall validation), `tools` (host-side operational scripts for the shared MariaDB: backups per perimeter, one-off `.sql` runs; **private repo**, it documents where the database lives and how it is restored).
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
- `strapiversion` lives at [main.py:137](main.py#L137) (also drives Blue/Green port parity and `MCP_INTERNAL_BASE_URL`)
- `Text2SQLRequest` / `Text2SQLResponse` Pydantic models around [main.py:214-269](main.py#L214-L269)
- `POST /search/text2sql` : main pipeline endpoint. Its first stage is the vision pre-stage
  when the request carries an `image_ref` (FASTAPI-TEXT2SQL-114): identify, compose the
  question, then fall through to the ordinary pipeline
- `POST /uploads/vision` / `GET /uploads/vision/{image_ref}` : the binary deposit and its
  replay read (FASTAPI-TEXT2SQL-275), the only routes in this repo that carry bytes
- 18 entity detail endpoints (movies, series, seasons, episodes, persons, companies, networks, collections, topics, lists, movements, technicals, genres, groups, deaths, awards, nominations, locations). `seasons` and `episodes` are keyed on composite paths (`/seasons/{id_serie}/{season_number}`, `/episodes/{id_serie}/{season_number}/{episode_number}`) and currently read from `T_WC_TMDB_*` source tables — see [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §6.1. `genres` reads the closed-vocabulary reference table `T_WC_TMDB_GENRE` (legacy lowercase PK `id`, no `ID_WIKIDATA`, so no Wikipedia arrays).
- FastMCP instance + 17 MCP tools (`sql_search` + 16 entity tools), 1 resource (`context://database-scope`), bearer-token middleware, `app.mount("", mcp_app)` at root. The `seasons` and `episodes` HTTP endpoints do not yet have MCP wrappers (tracked in [SEASONS_AND_EPISODES.md](doc/SEASONS_AND_EPISODES.md) §3 "MCP coverage")

**[text2sql.py](text2sql.py)** — core LLM logic.
- `_call_chat_llm()` — unified multi-provider dispatcher (OpenAI / Anthropic / Google). Routes on prefix: `gpt-*`/`o1*`/`o3*` → OpenAI; `claude-*` → Anthropic; `gemini-*` → Google.
- `f_text2sql(user_question, model, ui_language)` — text-to-SQL conversion; replaces `{ui_language}` in the prompt template so the LLM generates the `answer` field in the requested language.
- `f_resolve_complex_question()` / `f_resolve_complex_question_retry_payload()` — complex-question simplification via stronger model.
- `f_build_retry_question_from_reasoning()` — deterministic retry-question composer (typed entities + years).
- `f_answer_single_value()` — direct-answer path for single-cell zero-count results.
- `f_identify_from_image()` / `_call_vision_llm()` : the sixth task, the only one whose input
  is an image (FASTAPI-TEXT2SQL-114). OpenAI route only, and the error says so.
- `compose_vision_question()` / `select_vision_candidates()` / `question_targets_the_image()` :
  the deterministic half of the vision path: what the model identified becomes a question here,
  never in the model. See *The vision pre-stage*.
- Hot-reloads `text_to_sql.md`, `complex_question.md` and `vision_identification.md` via
  `data_watcher`.

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

**[vision_cache.py](vision_cache.py)** : the recognition cache of the vision path
(FASTAPI-TEXT2SQL-114), keyed on the MD5 of the image bytes and the formatted API version, in
its own table `T_WC_T2S_VISION_CACHE`.
- `search_vision_cache()` / `write_vision_cache_entry()` : degrade to a silent miss when the
  table is absent, so the path works before the migration runs.
- `identification_payload()` : **the contract**, what is stored is what depends on the image
  and not on the question. Adding a question-dependent key here makes the cache serve
  yesterday's answer to today's question.

**[sql_shapes.py](sql_shapes.py)** : structural predicates over a generated SQL query. Pure string analysis, no DB and no LLM: it answers *what shape does this query have*, never *is it right*.
- `detect_person_role_collapse(sql_query, result_entity)` : true when a person-listing query pins the `ID_PERSON` it projects to a person named in the question, a shape that can only ever return that named person (FASTAPI-TEXT2SQL-211).
- It exists as its own module so the runtime guard in `main.py` and the measurement in `analyze-complex-retry-logs.py` share the **exact same predicate**. A guard measured with a rule other than the one it runs is a number about nothing; do not fork the logic back into either caller.

**[cleanup.py](cleanup.py)** — version-scoped purge utilities (off by default; see `intcleanupenabled` at [main.py:70-71](main.py#L70-L71)).

**[auth.py](auth.py)** — `get_api_key()` Security dependency. Multi-key via `API_KEYS` (comma-separated); `secrets.compare_digest()` for constant-time comparison.

**[data_watcher.py](data_watcher.py)** — `register(filename, callback)`; daemon thread polls `./data/` every 5 s on mtime; logs hot reloads via `logs.log_hot_reload()`.

**[language_family.py](language_family.py)** — `guess_language_family()` from Unicode code points (Latin / Hangul / Japanese / Chinese / Cyrillic / Arabic / Hebrew / Devanagari / etc.).

**[logs.py](logs.py)** — `log_usage(endpoint, content, strapiversion)` and `log_hot_reload(filename)`. Filenames are `YYYYMMDD-HHMMSS_{endpoint}_{version}_{md5hash}.json`; never overwrite existing files.
- `LOGS_FOLDER` is the **relative** `"logs"`, and that is load-bearing. Making it absolute or
  configurable would re-split the corpus per colour; see *`logs/` and `uploads/` are shared*.

**[uploads.py](uploads.py)** — the vision-mode image deposits (FASTAPI-TEXT2SQL-275), the only binary path in this repo.
- `store_vision_image(imagebytes, strapiversion)` — magic-number check, house filename, write, and the `image_ref` returned to the client.
- `f_getuploadfilename()` — twin of `logs.f_getlogfilename`, same `YYYYMMDD-HHMMSS_<kind>_<version>_<md5>` shape, **hash over the raw bytes**; do not reuse the log one, it hashes `contenttext.encode('utf-8')`.
- `parse_image_ref()` / `vision_image_path()` — the guard between a client string and the filesystem. Anything the generator could not have produced is refused before a path exists.
- `load_vision_image()` — the replay read, raising `UploadUnavailable` **with the deposit date and the purge** when the file is gone.
- `UPLOADS_FOLDER` is relative for exactly the same reason, and with a sharper failure mode:
  absolute or per-colour makes a post-flip replay fail **silently**.

**[data/](data/)** : hot-reloaded prompts and config. [data/AGENTS.md](data/AGENTS.md) carries
what only matters when editing one of these files, in particular the three rules twinned
between `complex_question.md` and `vision_identification.md`, which share a motive and must
keep different instructions:
- `text_to_sql.md` — main Text2SQL prompt (loaded by [text2sql.py](text2sql.py))
- `complex_question.md` — complex-question resolver prompt (loaded by [text2sql.py](text2sql.py))
- `entity_extraction.md` — entity extraction prompt (loaded by [entity.py](entity.py))
- `entity_resolution.json` — per-placeholder resolution strategy list (loaded by [entity.py](entity.py))
- `closed_vocabularies.json` — alias dictionaries (loaded by [closed_vocab.py](closed_vocab.py))
- `vision_identification.md` : the image-reading prompt (loaded by [text2sql.py](text2sql.py))

**[maintenance/](maintenance/)** — one-shot operational SQL, run by hand against the production DB, no code path loads it. Distinct from `doc/sql/` (reference DDL, read-only) and from `eval/assertions-*.sql` (which writes to the evaluation bank): this folder writes to operational tables, `T_WC_T2S_CACHE` first among them. Conventions and the cache facts a cleanup relies on are in [maintenance/AGENTS.md](maintenance/AGENTS.md); read it before adding or running anything there.

---

## Runtime dependencies

The variables are documented in `README.md`, *Set up environment variables*. Three things that
file does not say, and that bite an agent:

- **`OPENAI_API_KEY` is required at startup even when no OpenAI model is selected**: `main.py`
  initializes the OpenAI embedding function for ChromaDB before it serves anything.
- **`MCP_API_KEY` empty means `/mcp` is open**, not weakly protected. `_verify_mcp_bearer` only
  enforces a bearer `if MCP_API_KEY:`, so `sql_search` and the 16 entity tools answer anyone who
  reaches the port. Verified 2026-08-23: both colours and the public NGINX route returned 200 to
  `tools/list` with no token and with a wrong one. Startup logs a warning, the only signal there is.
- **`UPLOADS_FOLDER`, `UPLOAD_RETENTION_DAYS` (30) and `MAX_UPLOAD_IMAGE_BYTES` (25 MB)** are not
  in that README block. They are read at import time like the three pipeline-shape flags, so a
  change needs a restart, and `UPLOAD_RETENTION_DAYS` must match the `--days` the cron passes to
  `purge-uploads.sh`.

---

## ChromaDB collections

`main.py` opens 14 entity collections with `get_or_create_collection` (the roster is in
`README.md`, *Key Architecture Components*), then opens `t2slocations` with **`get_collection`,
never `get_or_create_collection`** (FASTAPI-TEXT2SQL-247): that collection's HNSW configuration
(`space l2`, `ef_search 100`) is written at creation by process 216 of `embedding-update` and
cannot be changed afterwards, so the first program to create it decides it for every reader. A
`get_or_create` here would silently recreate it with the server defaults on the day it is
missing, with no error at query time, only worse ranking. The old QID-keyed `locations`
collection was dropped from the list for the same reason: leaving it would recreate it empty
once `embedding-update` deletes it.

If schema, entity IDs, collection document IDs, or language-routed fields change, assume the
relevant collection may need rebuilding or resyncing: stale embeddings resolve to IDs that no
longer exist in the SQL tables.

---

## Hot-reloaded vs restart-required

**Hot-reloaded** (~5 s after an mtime change): anything under `data/`, see `README.md`.

**Restart required** — consider whether a user-requested `strapiversion` bump is also needed so
the cache key flips and the Blue/Green parity moves:
- Any change to `*.py`.
- Any new placeholder (it must dispatch through `entity.py`).
- New `closed_vocab` canonical loader or query (touched in `closed_vocab.py`).

Do not bump `strapiversion` automatically, see *Version management workflow*. When a prompt or
config change ships without a bump, say so: cache rows for the current version may shadow it.

---

## Placeholder dispatch order

Inside `entity.resolve_entities()` the four stages run in this order, and the order is the
content of this section. `README.md` lists which placeholder belongs to which stage, with the
patterns, the canonical sources and the substitution kinds; it does not say what follows.

1. **Regex-validated** ([entity.py](entity.py) `_REGEX_PLACEHOLDER_RULES`). Dispatch uses
   `startswith()`, so **a more specific prefix must be listed before the prefix it extends**:
   `IMDb_person_ID` before `IMDb_ID`, `Wikidata_property_ID` before `Wikidata_ID`. Getting this
   wrong is silent: the shorter rule swallows the longer name and its pattern rejects the value.
   A rejected value leaves the placeholder in place, which marks the question ambiguous.
2. **Closed-vocabulary branches**, dispatched by name prefix in an `if/elif` chain calling
   `closed_vocab.resolve*`. Genre and `Technical_format` substitute a bare integer, the other
   three a single-quoted string; pick by the target column's SQL type.
3. **Embeddings / RapidFuzz**, driven by `data/entity_resolution.json` `search_list` strategies,
   with optional per-strategy language-family gating.
4. **Raw fallback**: the raw extracted value, SQL-escaped, substituted directly. Anything still
   unresolved after the loop sets `ambiguous_question_for_text2sql = 1`.

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

- **Four calls, not three, since the vision task.** `f_identify_from_image` goes through
  `asyncio.to_thread` for the same reason as the other three: it is the slowest call of the
  six, and blocking the event loop on it would serialize every concurrent request behind one
  photo.
- **Requests now genuinely interleave.** Per-request state (the DB connection, the messages list) is local; module state touched at request time is either read-only after startup (prompts, closed-vocab canonicals) or lock-protected (`_BKTREE_CACHE`). The prompt-cache buffer is a `ContextVar` holding a list, and `asyncio.to_thread` copies the context by reference, so appends from worker threads still reach the response.
**The fork-join (FASTAPI-TEXT2SQL-201).** Entity resolution iterates over the extraction payload, not over the placeholders found in the SQL, and `f_text2sql` only ever sees `input_text_anonymized`. The two branches are therefore independent, and `plan_entity_resolutions()` is started in a worker thread just before the text-to-SQL call, then joined right after the answer-entity guard. **The join is unconditional and must stay where it is**: the complex-question retry path below it closes the connection the worker thread is using. A plan that raised degrades to `resolve_entities()` on the sequential path.

**One accepted behavioural divergence.** When a placeholder is extracted but appears nowhere in the SQL, the justification or the answer, the old resolver ran *every* strategy and logged each one before discarding the result; the planner stops at the first strategy that resolves. The three texts come out identical, only the message trace is shorter. Everything else is byte-identical, message traces included.

---

## The six LLM tasks, and what each one actually costs

There are **six** LLM calls in this pipeline, not the three the `llm_model_*` parameters
suggested until FASTAPI-TEXT2SQL-232. Five route through `text2sql._call_chat_llm` and the
sixth, which reads an image, through `text2sql._call_vision_llm`; each is tagged with a
`cache_label` that is also its key in the prompt-cache log and its default reasoning effort.
Since -232 each has its own request selector, its own response field naming the model that
served it, and since -233 its own wall clock.

| # | Task (`cache_label`) | Call site | Fires on | Selector |
|---|---|---|---|---|
| 1 | `entity_extraction` | `entity.py:269` | 100 % | `llm_model_entity_extraction` |
| 2 | `text2sql` | `text2sql.py:518` | 100 % | `llm_model_text2sql` |
| 3 | `result_entity` | `text2sql.py:629` | 99.9 % | `llm_model_result_entity` |
| 4 | `complex_question` | `text2sql.py:663` | ~1 % | `llm_model_complex` |
| 5 | `answer_single_value` | `text2sql.py:835` | < 1 % | `llm_model_answer_single_value` |
| 6 | `vision_identification` | `text2sql._call_vision_llm` | only with an `image_ref` | `llm_model_vision` |

Line numbers move; the `cache_label` does not. `grep -n 'cache_label="' text2sql.py entity.py`
is the durable way to find all six.

**Task 6 is priced apart from the five, and it is not in the table below.** It fires only on a
request carrying an image, so it has no frequency in a text campaign; it costs about **4 cents
a photo** (1229 tokens of image at `detail: "high"` plus the reasoning output, at gpt-6-astra's
$10 / $50 per million), which is two orders of magnitude above any other task per call. That is
what the recognition cache of *The vision pre-stage* exists to spend once rather than twice.

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

### Who can drive the six, and the two gaps

| client | how it selects | state |
|---|---|---|
| **evaluator** (`eval/text2sql-eval.py`) | `--entity-extraction-model`, `--text2sql-model`, `--complex-model`, `--result-entity-model`, `--answer-single-value-model` | five of six; it cannot send an image at all, which is FASTAPI-TEXT2SQL-277 |
| **tmdb-front** | request params / cookies `eemodel`, `t2smodel`, `complexmodel`, `resultentitymodel`, `answermodel`, radio groups on the settings page | five of six; it sends `image_ref` but no vision-model selector (TMDB-FRONT-088) |
| **Claude, via MCP** | the six arguments of `sql_search`, `llm_model_vision` included | all six |
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

## An evaluation declares the path that must resolve it (FASTAPI-TEXT2SQL-257)

`complex_model_used` was an **observation**: it described what happened and could never
fail. Since -257 the bank declares, per question, which path *must* resolve it, in
`T_WC_T2S_EVALUATION.RESOLUTION_MODE`.

| value | meaning | verdict |
|---|---|---|
| `standard` | must resolve without escalation | escalation fired = **regression of the normal path**, even when the final answer is right |
| `complex` | cannot resolve without escalation | resolved without it = the assertion is too loose, or the question is easier than thought |
| `any` or NULL | no expectation | never judged |

**NULL is not `any` in disguise.** Both are judged the same way, which is not at all, but
only NULL lets you find what is still unqualified. Do not backfill the 1445 existing rows
for tidiness: NULL says "this question was never examined under this angle".

**The verdict stays out of `ASSERTIONS_TOTAL_SCORE`, and that is the important design
decision.** That score is the one thing that makes a campaign comparable to the previous
one. Folding a new failure reason into it would make 1.1.19 incomparable with 1.1.18,
which is precisely the mistake this whole line of work exists to avoid. The mode verdict
lives in its own column, `RESOLUTION_MODE_RESPECTED`, and the end-of-run recap prints the
escalation rate per declared mode beside the assertion score. Two measures, two readings.

**A `complex` evaluation tests the model, not the database.** *Groundhog Day* is not found
by a join; it is named by the LLM from its parametric memory and then looked up. So its
assertion must bear on the resolved title or id, never on a row set that depends on the
read-model, and it is inherently unstable across a model swap. That is a feature for the
GPT-5.6 comparison: descriptive questions are the most discriminating ground available,
where gpt-4o already plateaus above 96 % on factual ones.

**Why two extra columns shipped with it.** The verdict is computed on what the campaign
records, and the recording was a quarter short. Measured 2026-09-14 on `001.001.018`:
`complex_model_used` true on **46** executions, `COMPLEX_QUESTION_PROCESSING_TIME` positive
on **34**. The missing 12 go through the direct scalar answer, which banks into
`answer_single_value_processing_time`. Both are now persisted columns, so a campaign is
sliced in SQL and never by reopening `JSON_RESULT`.

**The schema change is not applied here.** `maintenance/eval-mode-de-resolution.sql` holds
the five `ADD COLUMN`, its rollback and its verification queries. The database is not
reachable from a developer workstation, so that file has been validated syntactically and
never run. Apply it on the VPS before the next campaign, or the evaluator writes columns
that do not exist.

### The cause of the escalation, not only its existence (FASTAPI-TEXT2SQL-271)

-257 answers *did this row escalate, and was it allowed to*. It cannot answer *why*, and the
three causes that raise `requires_complex_resolution` do not carry the same verdict at all:
`descriptive_identification` is the dispositif doing its job, `requires_complex_resolution` is
Text2SQL admitting defeat, `unbacked_entity_literal` is a hallucination being caught. Two of
them used to reach `first_pass_failure_code` under the **same** label, distinguishable only by
the free-text `first_pass_failure_reason`, which no campaign can group by. `main.py` now sets
`complex_resolution_code` at each point of decision, and `descriptive_identification` is a value
of the closed vocabulary in its own right. Rows written before that carry the mixed label, and
it was not a harmless one: measured 2026-09-17 on the 505 local logs, **35** retries filed under
`requires_complex_resolution` and all 35 were descriptive routings, none from Text2SQL. The
shared label carried the name of the case never observed, which does not look like an error, it
looks like a statistic.

Two columns follow, `FIRST_PASS_FAILURE_CODE` and `QUERY_MODE`, in
`maintenance/eval-executions-cause-escalade.sql`, not applied either.

**`QUERY_MODE` must be read from `first_pass_entity_extraction`, never from
`entity_extraction`.** On a retried row the second describes the inner pass over the *rewritten*
question, so it reads `named_entity_query`: measured 2026-09-17 on the 505 local logs, 30 rows
classified `descriptive_identification` in the first pass, of which 27 show `named_entity_query`
in `entity_extraction` and 3 show nothing. Reading the convenient field would have made the
campaign report almost no descriptive questions at all, which is the failure mode this whole
column exists to prevent.

**`FIRST_PASS_FAILURE_CODE` NULL with `COMPLEX_MODEL_USED = 1` is a cause, not a gap.** It is
the signature of the direct scalar answer, the only path that escalates without going through
the retry helper. And `QUERY_MODE` is the only denominator available, since the failure code
exists on retried rows alone: a rate of "descriptive questions that escalated" needs a
classification on every row, escalated or not.

## The vision pre-stage: an image becomes a question (FASTAPI-TEXT2SQL-114)

`README.md` documents what a client sends and gets back: the optional `image_ref`, the
`llm_model_vision` selector, and the five response fields. Below is only what breaks when you
edit this path.

**It is a PRE-STAGE, not a recursive re-entry, and that is the whole design.** The
complex-question retry re-enters `search_text2sql`, which is why it has to merge and renumber
two message arrays (`main.py`) and why it writes **two** log files per request (Gotcha #8d).
The vision path composes the question in place and falls through to the ordinary pipeline: one
message counter, **one** log file, and nothing new to teach whatever counts questions over
`logs/`. Do not "harmonise" it with the retry helper.

**The model identifies; the CODE composes the question.** `f_identify_from_image` returns
`items[]` and never a question, and `compose_vision_question` builds the question from those
items. That split is what makes the recognition cache sound: the identification of an image
does not depend on the question asked about it, so it is stored under the MD5 of the bytes and
reused on later turns. If the model composed the question, a cached turn and a fresh turn
would produce **different questions for the same photo**, and the divergence would only show
up on the second turn in production. `eval/verif-114.py` asserts the invariant directly: the
identification round-tripped through the cache composes the same question as the fresh one.

**Two shapes of composition, and the second one is the one to protect.** A lone photo goes
through `f_build_retry_question_from_reasoning`, the same deterministic composer the
complex-question retry uses. A photo carrying a question keeps the question and has the entity
substituted into it (`who directed this film?` -> `who directed the movie Blade Runner
(1982)?`). Flattening the second case into an entity card returns the film and answers
nothing, which is the defect recorded as **-263**, and the vision prompt inherits that rule in
so many words.

**Three outcomes never reach the catalogue**, and none of them is an error: a question about
the pixels (`about_image`, answered from the image), an image with nothing of cinema in it,
and an image the model could not read. All three return an `answer`, an empty `result`, no SQL
and `error: ""`, which is the `authoritative_empty` shape of **-221**: an affirmative
emptiness. Do not turn them into errors to make them easier to spot.

**`question_targets_the_image()` is a may-call gate, not a verdict.** It decides whether the
vision model is called on an image the cache already holds, because a question about the
pixels cannot be answered from a stored identification. When it is wrong in one direction it
costs one cached turn; it cannot produce a wrong answer, because the model has the final word
through `about_image` whenever it is actually called. Add markers to it freely; do not build a
decision on it.

**The two confidence constants are PROVISIONAL and unmeasured.** `VISION_CONFIDENCE_DOMINANT`
(0.70) and `VISION_CONFIDENCE_MARGIN` (0.20) decide whether one candidate opens its entry with
the alternative reported beside it, or whether all candidates are searched so the client can
ask which one is meant (rule VOICE-AGENT-093). The ticket is explicit that the threshold is
settled **on the twenty-image bench** and not guessed; that bench is FASTAPI-TEXT2SQL-277 and
it does not exist yet. They are named constants so the measurement has somewhere to land.

**`gpt-6-astra` is the default here, and it is the only default in this repository that is not
`gpt-4o`.** It is the model the feature was tried on, it is the one the ~4 cents a photo figure
was computed from, and its family is declared in the reasoning block (**-274**) with
`vision_identification` at the cheapest rung, `reasoning_effort: "low"`. Raise the rung only if
recognition weakens on the bench.

**`_call_vision_llm` is OpenAI only, deliberately.** It is not folded into `_call_chat_llm`
because that dispatcher takes a string and every provider encodes an image differently.
Anthropic and Gemini both read images and neither is wired: an untested branch that formats
bytes for a provider nobody has exercised is a liability. A non-OpenAI model name raises an
error that says exactly that.

**Structured outputs degrade once.** The contract is sent as a strict `json_schema`, which
OpenAI documents as compatible with `reasoning_effort` on `chat.completions`. On a refusal
`_VISION_STRUCTURED_OUTPUTS_AVAILABLE` flips and the rest of the process uses the plain-JSON
contract the other five tasks use, cleaned and validated by `json_guardrails`. The fallback is
there because a neighbouring combination IS refused (function tools with `reasoning_effort` on
gpt-5.6-sol, see *The reasoning-family block*) and because this repository has never sent a
`response_format` to the live API before.

### The recognition cache (`vision_cache.py`, `T_WC_T2S_VISION_CACHE`)

No tier of `T_WC_T2S_CACHE` indexes bytes: its key is the question. Without this module the
image path caches the **cheap** half of the work and repays the expensive one, about 4 cents,
on every re-deposit. The key costs nothing because it already exists: `f_getuploadfilename`
hashes the raw bytes into the deposit filename, so the same photo yields a new timestamp and
the **same** MD5.

- **Its own table**, not a column on `T_WC_T2S_CACHE`, whose contract is question to SQL.
- **Scoped by formatted API version**, because the prompt is hot-reloaded: without the scope a
  prompt correction shipped with no bump would keep serving identifications made by the old
  one.
- **Only the question-independent half is stored** (`hints`, `items`, `authoritative_empty`,
  `justification`). `about_image` and `image_answer` are dropped by
  `vision_cache.identification_payload`, and that function is the contract: adding a
  question-dependent field to it makes the cache serve yesterday's answer to today's question.
- **An `authoritative_empty` IS cached**, unlike the empty SQL result of Gotcha #8b. A photo of
  a meal will still be a photo of a meal tomorrow.
- **`retrieve_from_cache` and `store_to_cache` govern it** like every other tier, which is how
  a model comparison switches it off without a new flag.
- **The 30-day image purge does not invalidate a row**: the key is the fingerprint of the
  bytes, not the file. The row then serves the identification and never the pixels.
- The migration is `maintenance/vision-recognition-cache.sql`, **run in production on
  2026-09-20 at 12:53:25**; its output sits beside it in
  `maintenance/vision-recognition-cache-20260920.txt` and matches the DDL column for column and
  index for index. The graceful degradation stays, for the day a deployment points at another
  database: `vision_cache` flips to disabled on the first `Table doesn't exist` and the vision
  path works, uncached. **That flag never flips back**, so a process that met the missing table
  once stays uncached until it is restarted.

**Offline check:** `uv run eval/verif-114.py` (62 cases, no API, no database and no image). It
covers everything deterministic on this path: the may-call gate, the confidence rule, both
shapes of composition, the cache round-trip invariant, the guardrail, the `image_ref` refusals
and the Pydantic contract the two front clients depend on.

**Before editing `data/vision_identification.md`, read [data/AGENTS.md](data/AGENTS.md).** Three
of its rules have a twin in `complex_question.md`; they agree on the motive and disagree on the
instruction, because the two tasks fill opposite fields. The confidence guard is the one place
where letting them drift apart is dangerous rather than merely untidy.

**Not done, and deliberately so: no bench, no evaluation campaign.** The twenty-image bench of
FASTAPI-TEXT2SQL-277 does not exist, so recognition quality is unmeasured, the two confidence
constants are unmeasured, and `T_WC_T2S_EVALUATION_EXECUTION` still has no column for a sixth
model. Everything above is verified offline or by reading; nothing here was run against a live
model.

## The reasoning-family block in `text2sql.py` (FASTAPI-TEXT2SQL-231, -274)

`README.md` states the user-visible rule: reasoning models reject `temperature` and get
`reasoning_effort` instead, `_openai_sampling_kwargs` builds that half of the call per family,
`gpt-4o` is unchanged, and effort is the real cost knob. What it cannot say is how the block fails
when you extend it.

**There is no allowlist, so an undeclared family does not bounce, it leaves.** `_call_chat_llm`
routes on the prefix, anything starting with `gpt-` goes to OpenAI, and the five `llm_model_*`
fields of `Text2SQLRequest` are `Optional[str]` with no validator. Before -274,
`llm_model_text2sql: "gpt-6-astra"` was accepted, sent with `temperature=0` attached, and answered
400; on a route that tolerates the parameter it would instead have run at the model's default
effort with nobody able to read or set it. A family that is not declared here is a family that
spends silently.

**The four things a new family needs**, all in the same block and all four or none: the prefix in
`_REASONING_MODEL_PREFIXES` (or `temperature` stays attached), a row in `_EFFORT_BY_FAMILY` (or
the effort resolution falls back to the o-series vocabulary), a rung for every `cache_label` in
`_DEFAULT_EFFORT_TIER`, and an endpoint decision via `_CHAT_COMPLETIONS_REASONING_PREFIXES`.

**Note the indirection**: `_DEFAULT_EFFORT_TIER` holds a **tier name**, not a provider value, and
`_EFFORT_BY_FAMILY` turns it into one, because the families share no vocabulary (`minimal` was a
GPT-5.0-era value and exists nowhere now). **GPT-6 has no `none` rung**, and that one cell decides
the bill: copying the GPT-5 row would 400 on every call, while "fixing" it to `medium` would
quietly buy a thinking budget on the three tasks that fire on 100 % of requests. Only the two
rungs this pipeline selects are declared, because a rung nobody selects is a rung nobody has
measured. `vision_identification` sits in the table at the cheapest rung ahead of the task itself
(-114), so the family table is complete the day it lands.

**Four things NOT to assume.**

- **The `responses.create` branch is restricted to the o-series.** GPT-5.x and GPT-6 both go
  through `chat.completions`, which is also where the prompt-cache accounting this pipeline
  reports was measured; the two routes name their usage fields differently, so a campaign compared
  against the `gpt-4o` baseline needs both on the same route.
- **The o-series was never getting its effort**, a defect found while deciding that branch.
  `responses.create` takes `reasoning={"effort": "low"}`, not the flat `reasoning_effort="low"` of
  `chat.completions`. The flat form was passed, rejected, and swallowed by the `try/except` that
  falls back, so the o-series reached the fallback on **every** call and ran at its default
  effort. `_as_responses_api_kwargs` now translates. Neither GPT-5.x nor GPT-6 uses that path.
- **The cached prefix is 24.2 K tokens, not the 14.8 K measured in June.** Any cost estimate
  starting from the old figure is a third too low. Full protocol and figures:
  `%USERPROFILE%/Nestor/projets/t2s-backlog/topics/prompt-caching.md` PROMPT-CACHING-009.
- **Function tools combined with `reasoning_effort` are refused for `gpt-5.6-sol`** on
  `/v1/chat/completions`. It does not bite today, since this pipeline uses neither tools nor
  `response_format`. It will the moment someone adds structured outputs.

**Offline check:** `uv run eval/verif-274.py` (31 cases, no API and no database). It reads the
family block out of `text2sql.py` and executes it in isolation, so it runs on a machine without
the full stack.

**Not done, and deliberately so: no evaluation campaign has been run on `gpt-6-astra`.** The
family is selectable and its cache behaviour is measured; whether its SQL is as good as
`gpt-4o`'s is unknown. `T_WC_T2S_EVALUATION_EXECUTION` already carries the model columns, so the
comparison is mechanical when someone wants to spend the run.

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

## A new shell script needs its executable bit set IN GIT, not on disk

`core.filemode` is **false** in this checkout, which is the Windows default: a `chmod +x` on
the working copy changes the file and changes nothing git records, so the script lands in the
repository as `100644` and the VPS answers `Permission denied` on the first `./script.sh` after
the pull. The fix is one command, and it is the only one that works from Windows:

```bash
git update-index --chmod=+x path/to/script.sh
git ls-files -s '*.sh'          # every one of them must read 100755
```

**This is the third time the same bit has cost a deployment.** `archive-logs.sh` never ran once
before 2026-08-21, partly for this reason (the other being an impossible redirect target, both
recorded in its own header), and `migrate-logs-to-shared.sh` was added on 2026-09-19 as `100644`
and failed on its first run the next day. `eval/verif-206.sh` was found carrying the same defect
while fixing it, never having been run. Check the listing above whenever a `.sh` is added, and
prefer `bash script.sh` over `./script.sh` when a first run must not be about permissions.

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

### Entity endpoints: the contracts to preserve

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
or (second belt) when the inner extraction produced a `Release_year` / `Birth_year` /
`Death_year` placeholder while the original question holds no year. The decision is written to
the messages and to `complex_retry_cache_policy`, whose values `README.md` lists. The rewritten
question stays cached under its own wording by the inner pass, so nothing is lost. Not done:
marking retry-derived rows, which would need a column in `T_WC_T2S_CACHE`.

## Cache API-version filtering

Reads and writes take the **formatted** version (`XXX.YYY.ZZZ`), never the raw `strapiversion`;
the `sql_cache` helpers already receive it as a parameter, so pass it through rather than
recomputing it. Lookups also filter on `UI_LANGUAGE`, with `OR UI_LANGUAGE IS NULL` for rows
written before that column existed. Which SQL column a hit prefers is in *Where things live*,
under `sql_cache.py`.

---

## Version management workflow

When updating prompt templates, schema, or resolver behavior:
1. Edit the hot-reloaded file in `data/` directly — no versioned filename suffix; hot-reload picks the change up within ~5 s without a restart.
2. Bump `strapiversion` in [main.py:137](main.py#L137) only when the user explicitly asks for a version bump. This also flips Blue/Green port parity when the patch number changes.
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
- For the vision path, run `uv run eval/verif-114.py` (no API, no database, no image): it
  covers the deterministic half, which is the half that fails silently. Recognition quality
  itself needs the twenty-image bench of FASTAPI-TEXT2SQL-277, which does not exist yet, and a
  real image deposited through `POST /uploads/vision`.
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
Format `{entity}_{id}_{lang}` (e.g. `movie_12345_fr`); the language drives the SQL field through
the `languages` map. See *Entity-resolution config schema*.

### Gotcha #4 — Entity Variable Matching in Embeddings Cache
A candidate document is only accepted when **all** extracted entity variables appear in it ([main.py:671](main.py#L671)):
```python
if all(var in doc_entity_vars for var in entity_variables):
```

### Gotcha #5 — Messages Position Counter
Always increment after appending. See *Messages array invariant* for how the counter comes back
from a delegated call.

### Gotcha #6 — Database Connection Lifecycle
Open once per request, pass the connection around, close in a `finally`. Do NOT call `get_db_connection()` inside loops.

### Gotcha #7 — Custom Embedding Function Interface
`OpenAIEmbeddingFunction` ([main.py:80](main.py#L80)) must implement both `__call__()` (batch) and `embed_query()` (single query) — ChromaDB needs both.

### Gotcha #8 — Complex Question Retry Recursion Guard
The pipeline can retry via the stronger model, but only when `complex_question_already_resolved = False`. The recursive call sets it to `True` to prevent runaway retries.

### Gotcha #8b : An empty result is never cached (FASTAPI-TEXT2SQL-212)
`README.md` says why (the anonymized row freezes the whole **template**, so one defective query
poisons every entity pair on that pattern) and how to override it (`CACHE_EMPTY_RESULTS=1`). The
code rule: all four tiers go through the single `store_to_cache_allowed` / `retry_store_allowed`
gate, so do not reintroduce a bare `request.store_to_cache` in a write.

### Gotcha #8c : Signal (d) of the no-results guard reads the SQL, not the resolution (FASTAPI-TEXT2SQL-211)
The three original signals of **-156** all watch **entity resolution**, so an empty result whose entities all resolved was declared authoritative. Signal (d) is the first one to look at the query itself, via `sql_shapes.detect_person_role_collapse`. It is a **suspicion, not a proof**, and that is deliberate: firing wrongly costs one stronger-model call on a result that was **already empty**, while missing it hands the user a silent "no results" on an answerable question. Keep that asymmetry in mind before tightening it. Before widening it, run `analyze-complex-retry-logs.py`, whose `person-role collapse` column reports how many blocked empties, and how many **authoritative** ones, the signal moves. Local corpus on 2026-08-26: 4 fires out of 438 logs, all 4 the same defect, 2 of them previously classified AUTHORITATIVE.

### Gotcha #8d : A retried request writes two log files (FASTAPI-TEXT2SQL-241)
See *The first pass of a retried request is recorded*. Counting questions over `logs/` without
skipping the inner file counts a retried question twice; the outer file is the complete record.

### Gotcha #9 — Closed-vocabulary resolution: order, and where aspect ratios live
`README.md` lists the six placeholders, their canonical sources, their substitution kinds (integer
for the genres and `Technical_format`, quoted string for the other three), the `APPLIES_TO_MOVIE` /
`APPLIES_TO_SERIE` split, the `Department_name` crew-only rule and which placeholders have a
`_LANG` companion table. Two things it does not carry:

**Resolver order matters.** In `_resolve_closed_vocab`, canonical exact match runs **before** alias
match. If a user-typed value happens to be a literal canonical, the canonical wins and the alias
never fires, so remapping noisy DB variants onto one dominant form means **excluding them from the
canonicals in the loader query**, never adding an alias.

**Aspect ratios are rows of `T_WC_T2S_TECHNICAL`**, carrying `TECHNICAL_TYPE='aspect_ratio'` and
dot-decimal `DESCRIPTION` values (`'1.85'`, `'2.35'`), with the surface variants as aliases under
`Technical_format`. There is no `Aspect_ratio` placeholder and no `T_WC_T2S_MOVIE.ASPECT_RATIO`
filter: everything goes through `{{Technical_formatN}}` and the `T_WC_T2S_MOVIE_TECHNICAL`
junction like every other technical, which is what makes a movie shipping in several ratios match
on any of them.

### Gotcha #10 — Regex Placeholders Reject Malformed Values
Rejection and the prefix-ordering rule are in *Placeholder dispatch order*; the patterns are in
`README.md`. The one choice left when adding a rule: `is_numeric` follows the **target column's
SQL type**, since numeric rules substitute a bare integer (stripping surrounding quotes in two
regex passes) and string rules substitute a quoted SQL literal.

### Gotcha #11 — MCP Mount Path
`app.mount("", mcp_app)` (empty string), not `"/mcp"`. Nginx strips/preserves `/mcp` upstream, and FastMCP's own routes live under `/mcp/…`. Mounting under `/mcp` produces `/mcp/mcp` paths.

### Gotcha #12 — The Fork-Join Must Be Joined
See *Pipeline scheduling*: `plan_entity_resolutions()` holds this request's DB connection and the
retry path closes it. Do not move the join, and do not add a `return` between the fork and it.

### Gotcha #13 : An image_ref is a client string, never a path (FASTAPI-TEXT2SQL-275)
Anything arriving as an `image_ref` goes through `uploads.parse_image_ref()` first, which accepts
only a name the generator itself could have produced. Do not join it to a folder, do not
`os.path.basename()` it and hope: the whole upload path takes no filename from the client, and the
extension comes from the magic number of the bytes.

### Gotcha #14 : The vision model identifies, it never writes the question (FASTAPI-TEXT2SQL-114)
`compose_vision_question()` builds the question from `items[]`, in code. Letting the model
return the question instead would look simpler and would break the recognition cache: a cached
turn and a fresh turn would compose **different questions for the same photo**, so the page-2
hash would miss and the second turn of a conversation would repay the whole pipeline. The same
rule forbids putting anything question-dependent into `vision_cache.identification_payload()`.
See *The vision pre-stage*, and `eval/verif-114.py`, which asserts the invariant.

---

## Database tables you'll touch most

Prompt-visible schema rules live in [data/text_to_sql.md](data/text_to_sql.md), the DDL in
[doc/sql/](doc/sql/), the entity roster in `README.md` (*Database Schema Coverage*), the naming
rules below in *SQL Object Naming Conventions*, and MCP clients also see the
`context://database-scope` resource. One table is described nowhere else:

- `T_WC_T2S_VISION_CACHE` : the recognition cache of the vision path, keys `IMAGE_MD5` (the
  fingerprint of the deposited bytes, read off the `image_ref`) and `API_VERSION`
  (`XXX.YYY.ZZZ`), payload `IDENTIFICATION` (JSON), plus `IMAGE_REF`, `VISION_MODEL`,
  `AUTHORITATIVE_EMPTY`, `VISION_IDENTIFICATION_PROCESSING_TIME`, `DELETED` and the two
  timestamps. Read and written by [vision_cache.py](vision_cache.py) with graceful
  degradation: while the table is absent the whole module is a silent miss. Created by
  `maintenance/vision-recognition-cache.sql`, run in production 2026-09-20.
- `T_WC_T2S_CACHE` — keys `QUESTION`, `QUESTION_HASHED`, `SQL_QUERY`, `SQL_PROCESSED`,
  `JUSTIFICATION`, `ANSWER`, `RESULT_ENTITY`, `API_VERSION` (`XXX.YYY.ZZZ`), `UI_LANGUAGE`,
  `IS_ANONYMIZED`, `DELETED`, plus timing columns. `RESULT_ENTITY` is written and read by
  [sql_cache.py](sql_cache.py) with **graceful degradation**: when the column is absent
  (pre-migration), reads and writes fall back to the legacy column set and treat it as empty
  rather than failing.

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

### Entity identity boundary

Text2SQL owns relational structure, never the identification of an unnamed real-world entity from remembered clues. `data/entity_extraction.md` classifies each request with `query_mode`; `descriptive_identification` routes to the stronger model before Text2SQL. Text2SQL may also emit `requires_complex_resolution: true`. The two reach `first_pass_failure_code` as distinct values since FASTAPI-TEXT2SQL-271, so a campaign can tell a deliberate routing from an admission of defeat. Independently of both prompts, `entity.find_unbacked_entity_literals()` rejects resolvable entity equalities whose value occurs in neither the original question nor extracted entities. Keep this guard before SQL execution and cache writes. A literal explicitly present in the original question remains grounded even when extraction missed it, which preserves the `Pour le plaisir` rescue path.

**The guard judges SQL generated in the current request, never an exact-question cache hit (FASTAPI-TEXT2SQL-259).** Two facts make it unsatisfiable on that path, and both are properties of the cache rather than accidents: `sql_cache` returns `SQL_PROCESSED`, the already entity-resolved SQL whose literal is the canonical database value, and entity extraction is skipped on a cache hit, so `entity_extraction` is `None`. Left ungated, the guard rejected SQL the pipeline itself had resolved and stored, for every cached question whose title needed any normalization at all: a colon, an accent, a leading article, a French title resolved onto the English column. Grounding also folds case, diacritics and punctuation before comparing, so `2001: A Space Odyssey` matches a user who typed `2001 A space odyssey`; it folds surface form only, never words, so a title recalled from a plot description still shares nothing with the question. The anonymized and embeddings cache paths keep the guard: extraction runs there, and their SQL still carries placeholders, which `find_literal_equalities` skips.

`query_mode` is a soft field (FASTAPI-TEXT2SQL-255): [json_guardrails.py](json_guardrails.py) validates its value against the closed vocabulary but does not require its presence. A missing mode costs the descriptive routing only, while rejecting the payload discarded a usable extraction and handed Text2SQL the raw, non-anonymized question. The lesson for any prompt-and-guardrail pair: a rule stated once in the spec loses to the shape demonstrated by the examples. When adding a required key to a prompt contract, update every example in that prompt in the same commit, or the model will keep answering in the shape it was shown.

---

## Encoding

Keep Markdown, prompt files, JSON config, and logs UTF-8. These files contain non-ASCII names and multilingual examples. Avoid editor or terminal operations that rewrite them with mojibake.

---

## Build & deployment (Docker)

The API/MCP server is built and run as a Docker container via the repo's `Dockerfile` (base image `python:3.12-slim-bookworm`, `PYTHONUNBUFFERED=1`). The build compiles SQLite 3.40.1 from source (set on `LD_LIBRARY_PATH`) for ChromaDB compatibility, installs `requirements.txt`, copies `*.py` and `./data/`, and runs `CMD ["python", "./main.py"]`. The `Dockerfile` does not declare an `EXPOSE` or `VOLUME`; the runtime config (the `.env` variables in "Runtime dependencies", including the Blue/Green `API_PORT_*` ports) is supplied at `docker run` time. Note `data/` is hot-reloaded from inside the image, so prompt/config edits need a rebuilt (or volume-mounted) `data/` to take effect in a running container.

### Which Blue/Green slot is live: read it off the version's patch number

Odd patch means Green, even patch means Blue. The rule itself, the real ports and the four
clients that have to be repointed are in "Clients of this API" above; the consequence here is
narrower. After touching a `*.py`, run the restart script for the colour matching the **current**
version's parity, `restart-green.sh` on an odd patch, `restart-blue.sh` on an even one. Never
infer the live colour from which script happened to be run last.

### `logs/` and `uploads/` are shared by every colour, with opposite retentions

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

**Verifying the shared mount.** `eval/verif-275.sh` exercises the upload path against a running
deployment. Its one check that cannot run on a laptop is the cross-colour read that proves the
mount is really shared, `OTHER_BASE_URL=...`.

---

**Last Updated**: 2026-09-20
**Current Version**: 1.1.19 (see `strapiversion` in [main.py:137](main.py#L137))

## Backlog (Nestor second-brain)

The prioritized, agent-ready implementation backlog for this repo lives in the **Nestor**
knowledge repo (a separate repo, not cloned alongside this one):

- This repo: `C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\fastapi-text2sql.md`
- Cross-repo dashboard: `C:\Users\vaugo\Nestor\projets\t2s-backlog\index.md`

Consult it before implementing: tasks are `FASTAPI-TEXT2SQL-NNN` with status (done / in-progress /
todo), priority, and quick-wins. NOTE: these are local paths on Philippe's PC and do not
resolve on the VPS or on cloud agents (claude.ai/code).
