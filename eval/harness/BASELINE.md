# Voice-agent harness — recovery baseline

Recorded result of the conversational harness benchmark (recovery **without** the
diagnostic signals). This is the reference point against which evolution #1
(surfacing a `diagnostic` + inviting reformulation) will be A/B-compared.

## Run 1 — initial smoke baseline (2026-06-16)

**Config**
- Voice-agent URL: `https://www.vaugouin.com/voice-agent` (via nginx → `voice-agent:3000`)
- Orchestrator model: `gpt-5.1` (the voice-agent's `OPENAI_TEXT_MODEL`)
- Question-bank source: MariaDB `T_WC_T2S_EVALUATION` (718 EN eval rows)
- Scenarios: 30 (first IDs, `--lang en`, all categories), single-turn
- complex_question_processing: **False** (no parametric cheat)

**Result**
```json
{
  "n": 30,
  "run_errors": 0,
  "task_success": 20,
  "task_success_rate": 66.7,
  "n_initial_empty": 2,
  "n_recovered": 0,
  "empty_result_recovery_rate": 0.0,
  "retry_attempt_rate": 0.0,
  "avg_t2s_calls": 1.0,
  "answer_without_result": 2,
  "strategy_histogram": {
    "direct_success": 20,
    "wrong_result_no_retry": 8,
    "gave_up_empty": 2
  }
}
```

| Metric | Value | Reading |
|---|---|---|
| task_success_rate | 66.7% (20/30) | final result satisfies the validated assertion |
| **retry_attempt_rate** | **0.0%** | the agent issues exactly one `query_text2sql` per run |
| **avg_t2s_calls** | **1.0** | only the server-forced initial query; never re-queries |
| empty_result_recovery_rate | 0.0% (0/2) | small denominator (2 empties) — not yet robust |
| wrong_result_no_retry | 8 (27%) | got rows, missed the assertion, did **not** retry |
| answer_without_result | 2 | answered (a clarification) on an empty result |

## Headline finding

**The agent never recovers — because it never retries.** `avg_t2s_calls = 1.0`
and `retry_attempt_rate = 0%`: in every run the only tool call is the one the
server forces. The agent passively reports the first result, on empty *and* on
wrong results.

Root cause is the `/text-chat` prompt: it forces the initial `query_text2sql` and
instructs "*base your answer on that tool result*", which steers the model to
**report**, not to **re-query** — even though `query_text2sql` remains available.

**Implication for evolution #1:** a `diagnostic` signal alone will not move the
needle. It needs **two levers**: (1) the signal
(`reason: empty_result | sql_execution_error | entity_unresolved`), and (2) a
prompt that *permits/invites* reformulation when the result is empty or looks
wrong. The 0% retry rate is the proof.

## Caveats

- **Small empty denominator (2/30).** The first IDs aren't failure-prone. A
  targeted run (`--categories 9,10,11,33,44`, and FR) is needed for a recovery
  baseline with a usable denominator.
- **Masked SQL errors inflate "empty".** Observed: a movie+serie `UNION` with
  mismatched column counts → MySQL error 1222 → `result_count=0` but `error=""`.
  Some "empties" are actually SQL-generation bugs, not absent data. (Separate
  issue, in the text2sql prompt, not the harness.)
- **Not comparable to the single-turn evaluator's ~78.5% EN** — different sample,
  agentic path, no complex cheat, scored on the final agent result.

## Next

1. Targeted recovery baseline over failure-prone categories (EN + FR) to get a
   real `n_initial_empty`.
2. Implement evolution #1 (signal + prompt) and re-run; compare
   `empty_result_recovery_rate` against this baseline.
