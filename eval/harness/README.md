# Voice-agent conversational harness benchmark (MVP)

Measures the **harness**, not the **scaffolding**. The single-turn evaluator in
`../` scores `/search/text2sql` as a black box (and usually *with* the complex
"cheat" enabled). This harness drives the **voice-agent** through its real
`/text-chat` path — which calls the API with `complex_question_processing=False`
— and measures whether the agent **recovers on its own** when the first query
comes back empty, without the parametric cheat.

This MVP established the **recovery baseline WITHOUT the diagnostic signals** (see
`BASELINE.md`), so a later change (surfacing `{reason, unresolved_entities}` to the
agent) can be A/B'd against it. The voice-agent now *emits* a compact `diagnostic`
in its `query_text2sql` output, and the harness **captures** it (observability — see
below); this does not change the agent's behaviour, which stays at the baseline
until a `/text-chat` prompt actually invites reformulation.

## What it measures

For each scenario the harness reads the `/text-chat` `tool_outputs` trace. The
server always forces an initial `query_text2sql`; any *additional* `query_text2sql`
call is the agent's own recovery attempt.

Headline metrics (in `harness_global_<lang>.txt`):
- **task_success_rate** — final result satisfies the (validated) assertion.
- **empty_result_recovery_rate** — among scenarios whose forced first query was
  empty/errored, the share that still ended correct. *This is the baseline number.*
- **retry_attempt_rate**, **avg_t2s_calls** — recovery effort / efficiency.
- **strategy_histogram** — `direct_success`, `recovered_by_retry`,
  `retried_but_failed`, `gave_up_empty`, `wrong_result_no_retry`.
- **answer_without_result** — anti-cheat flag: a non-empty spoken answer on an
  empty final result (possible ungrounded answer; could also be a clarification).
- **initial_diagnostic_histogram** — distribution of the voice-agent `diagnostic`
  `reason` (`empty_result`, `entity_unresolved`, `no_sql`, `sql_error`, …) on the
  forced first query. Per-scenario, the CSV adds `initial_diagnostic_reason` and
  `final_diagnostic_reason`. Observability only (does not affect classification);
  empty when the voice-agent build predates the `diagnostic` field.

## What it reuses (single source of truth)

- the **assertion DSL** `../text2sql_eval_functions.py` (imported via `sys.path`,
  not copied) — same scoring as the single-turn evaluator;
- the **question bank** — read straight from **MariaDB** (`T_WC_T2S_EVALUATION`),
  exactly where the evaluator reads it (same filter: `IS_EVAL = 1` and a non-empty
  `ASSERTIONS_QUERY_RESULT`), reusing `citizenphil.f_getconnection()`. Assertions
  are reused as-is; the harness never invents them.
  - `--source auto` (default): MariaDB when DB creds are present (`DB_HOST` set,
    e.g. via `--env-file`), else the JSON fallback.
  - `--source db` / `--source json` force one or the other.
  - **JSON fallback** (local dev / no DB): the Phase 31 exports, located via
    `$HARNESS_EVALS_DIR` → `/shared/evaluation` → `../data/evaluation`. These are
    not committed, so a fresh checkout/image has none unless the evaluator exported
    them.

## Run

Prereqs (your infra / secrets — not bundled): the voice-agent running and
reachable, itself configured with `OPENAI_API_KEY` and a reachable text2sql API.

```bash
cd eval
python harness/selftest.py                              # offline, no network
python harness/run_harness.py --lang en --limit 30      # live baseline
python harness/run_harness.py --lang en --categories 9,10,11,33,44   # failure-prone cats
```

Config: `VOICE_AGENT_URL` env (default `http://127.0.0.1:3000`) or
`--voice-agent-url`. Outputs land in `$HARNESS_OUT_DIR`, else `/shared/harness`
when `/shared` is mounted, else `harness/results/` (gitignored).

## Running on the VPS (Docker)

This runs in a container exactly like the single-turn evaluator — in fact **the
same image**. The eval `Dockerfile` does `COPY . /app/`, so `harness/` is already
inside `text2sql-eval-python-app`; we only override the entrypoint. It uses the
same `--env-file` as the evaluator (the harness reads the question bank from
MariaDB; it does *not* need an OpenAI key — the voice-agent holds that), and
`--network=host` to reach both MariaDB and the voice-agent on the host.

```bash
# launcher in eval/, modeled on text2sql-eval.sh (build, run detached, tail logs)
cd ..                       # eval/
VOICE_AGENT_URL=http://localhost:3000 ./harness-eval.sh
# the run args (--lang/--limit/--categories) are set inside harness-eval.sh;
# edit that file (a commented variant is provided) to change them.

# equivalent raw docker run (ad-hoc args)
docker run -it --rm --network=host \
  --env-file /home/debian/docker/text2sql-eval/.env \
  -e VOICE_AGENT_URL=http://localhost:3000 \
  -v /home/debian/docker/shared_data/text2sql-eval:/shared \
  --entrypoint python text2sql-eval-python-app \
  harness/run_harness.py --lang en --limit 30
```

Results persist to `/shared/harness/` via the mounted volume.

**Networking (the catch on this VPS).** MariaDB is reached as `DB_HOST=localhost`
(host network only), but the voice-agent runs on the `reverseproxy` bridge network
and is **not** host-published — so `--network=host` reaches the DB but not the
voice-agent on `localhost:3000`. Two ways to run (`harness-eval.sh` picks via env):

- **(A) host network + public voice-agent URL** (default; mirrors how the
  voice-agent reaches the API via a public URL):
  `VOICE_AGENT_URL=https://YOUR_HOST/voice-agent ./harness-eval.sh` — the harness
  calls `$VOICE_AGENT_URL/text-chat`, nginx proxies it to `voice-agent:3000`.
- **(B) join the reverseproxy network + container name** (only if MariaDB is
  reachable from that network):
  `NETWORK=reverseproxy VOICE_AGENT_URL=http://voice-agent:3000 ./harness-eval.sh`.

Quick check of (A) from the VPS host:
`curl -s -X POST https://YOUR_HOST/voice-agent/text-chat -H 'Content-Type: application/json' -d '{"message":"test","context":[]}'`
should return JSON (with a `tool_outputs` array).

> Dependency note: the driver uses `requests` (already in `eval/requirements.txt`)
> — **not** `httpx` — precisely so it runs in the existing eval image with no
> extra packages.

## Files

| File | Role |
|---|---|
| `harness_lib.py` | Core (no network): scenario loading, scoring (DSL reuse), tool-trace parsing, recovery classification, aggregation. |
| `run_harness.py` | Live driver against `/text-chat` + CLI + output writing. |
| `selftest.py` | Offline checks of `harness_lib` on fixtures (real DSL + pandas). |
| `../harness-eval.sh` | Docker launcher in `eval/` (modeled on `text2sql-eval.sh`): build image + run the harness detached. |

## MVP scope & limits

- **Single-turn scenarios** from the bank. Recovery is still observable: it happens
  inside one `/text-chat` call (forced initial query → the model may issue a
  reformulated `query_text2sql` in the same tool loop). The `turns` list in a
  scenario already supports scripted multi-turn follow-ups for a later version —
  but new follow-up assertions need DB knowledge to author, so they are not faked
  here.
- The orchestrator is whatever the voice-agent is configured with
  (`OPENAI_TEXT_MODEL`, e.g. `gpt-5.1`). The harness measures *that* model.
- Non-determinism: for a stable baseline, run a fixed scenario set; repeat for
  variance if needed.

## Next (after the baseline)

Evolution #1 — surface a compact `diagnostic` (`reason`, `unresolved_entities`) in
the voice-agent's `query_text2sql` tool result. **Done**: the voice-agent emits it
and the harness captures it (`initial_diagnostic_histogram` + per-scenario reasons).
What remains for the A/B to mean anything is the **second lever** — a `/text-chat`
(and Realtime) prompt that *invites* reformulation on `empty_result` /
`entity_unresolved`. Add that, re-run, and compare `empty_result_recovery_rate`
against the baseline. The baseline's 0% retry rate shows the signal alone won't move
the needle.
