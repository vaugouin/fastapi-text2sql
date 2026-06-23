# harness/

## Role

Conversational **harness** benchmark for the `voice-agent` (sibling repo). Drives
the voice-agent `/text-chat` path and measures the agent's **recovery on empty
results without the complex "cheat"**. Complements the single-turn evaluator in
`../`, which scores the `/search/text2sql` scaffolding as a black box.

See `README.md` for metrics, how to run, and scope.

## Conventions & key facts

- **Reuse, don't copy.** The assertion DSL (`../text2sql_eval_functions.py`) and
  the question bank (`../data/evaluation/*.json`) are the single source of truth.
  `harness_lib.py` puts `eval/` on `sys.path` and imports the DSL; it never
  reimplements scoring.
- **Validated assertions only.** Scenarios reuse the bank's `query_result`
  assertions. Do not invent assertions without DB verification.
- **Question-bank source = MariaDB.** Read straight from `T_WC_T2S_EVALUATION`
  (same filter as the evaluator's Phase 11), via `citizenphil.f_getconnection()`.
  `--source auto` uses the DB when `DB_HOST` is set (so the launcher passes
  `--env-file`), else falls back to the Phase 31 JSON exports
  (`$HARNESS_EVALS_DIR` → `/shared/evaluation` → `data/evaluation`; not committed).
  `import citizenphil` is lazy (inside the DB loader) so `harness_lib` stays
  importable offline for `selftest.py`.
- **No network in `harness_lib.py`** so it stays unit-testable (`selftest.py`).
  All HTTP lives in `run_harness.py`.
- **Transient upstream 5xx are retried.** `/text-chat` returns 502 on a transient
  upstream 5xx (observed: the **text2sql API** returning 500, surfaced via the
  `query_text2sql_data` wrapper — not OpenAI). `run_harness._post_with_retry` retries
  5xx / connection / timeout with linear backoff (4xx are not retried) so a single
  blip does not drop a scenario to `run_error`. The voice-agent's `/text-chat` now
  also retries the text2sql call itself (`_post_text2sql_with_retry`), so real users
  are protected too; its OpenAI Responses call remains un-retried.
- **Run artifacts** go to `results/` (local) or `/shared/harness` (VPS) and are
  gitignored (`.gitignore`). Do not commit run outputs.
- **Runs in the existing eval Docker image.** The eval `Dockerfile` does
  `COPY . /app/`, so `harness/` ships in `text2sql-eval-python-app`. The launcher
  `../harness-eval.sh` (in `eval/`, modeled on `text2sql-eval.sh`) builds that
  image and overrides the entrypoint. Keep the harness dependency-free beyond
  `eval/requirements.txt` — the driver uses `requests`, **not `httpx`**, on purpose.
  No `--env-file`: the harness carries no secrets (the voice-agent holds them).
- **Anchoring (verified in code):** the voice-agent uses its own OpenAI tools
  (`query_text2sql` + detail tools), NOT the MCP `sql_search`/`get_*` surface; it
  sends `complex_question_processing=False`. As of June 2026 the `query_text2sql`
  tool output also carries a compact `diagnostic` (`reason`, `unresolved_entities`);
  `parse_tool_trace` captures it and the rollup reports
  `initial_diagnostic_histogram`. This is observability only — it does NOT feed the
  recovery classification (kept on `_is_empty` so baselines stay comparable), and is
  `None`/empty when the voice-agent build predates the field.

## Pitfalls

- This dir is tracked (unlike `../claude/`, which is gitignored). Mind what you
  commit — code yes, `results/` no.
- A baseline must be measured before adding the diagnostic signals, otherwise the
  later A/B has nothing to compare against. *(Done: baseline recorded in
  `BASELINE.md`, 2026-06-16. The diagnostic is now captured but not yet acted on —
  the agent's behaviour is unchanged until the `/text-chat` prompt invites
  reformulation.)*
