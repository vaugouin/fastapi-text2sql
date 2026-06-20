"""Core logic for the voice-agent conversational harness benchmark (no network).

This module is deliberately free of HTTP/LLM calls so it can be unit-tested
offline (see selftest.py). The live driver lives in run_harness.py.

What it does:
- loads scenarios from the existing question bank (eval/data/evaluation/*.json),
  reusing the *validated* result-set assertions — we never invent assertions;
- scores a tool result against an assertion by reusing the canonical DSL
  (eval/text2sql_eval_functions.py), exactly as the single-turn evaluator does;
- parses the voice-agent `/text-chat` tool_outputs trace and classifies the run
  (did the agent recover when the forced first query_text2sql came back empty?).

Why this measures the *harness* and not the *scaffolding*: the voice-agent calls
`/search/text2sql` with complex_question_processing=False (no parametric "cheat"),
so when the first query returns nothing, any recovery is the agent's own doing —
issuing a reformulated query_text2sql within the same turn's tool loop. We read
that from the tool trace.
"""
import html
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# eval/ is the parent of harness/ — put it on the path so we can reuse the
# canonical assertion DSL instead of copying it (single source of truth).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import text2sql_eval_functions as t2s_eval  # noqa: E402


def resolve_evals_dir() -> Path:
    """Locate the question-bank JSON exports.

    The question bank lives in MariaDB; the JSON files are Phase 31 exports and
    are NOT committed to git, so a fresh repo checkout / Docker image does not
    contain them. Resolution order:
      1. $HARNESS_EVALS_DIR (explicit override);
      2. /shared/evaluation  (the eval's export volume, mounted in the container);
      3. eval/data/evaluation (local dev copy).
    """
    env = os.getenv("HARNESS_EVALS_DIR")
    if env:
        return Path(env)
    shared = Path("/shared/evaluation")
    if shared.is_dir() and any(shared.glob("*.json")):
        return shared
    return ROOT / "data" / "evaluation"


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
# A "record" is the source-agnostic shape we normalize both MariaDB rows and JSON
# exports into: {id, category_id, question_en, question_fr, assertion}.

# Same table + filter as the evaluator's Phase 11 (text2sql-eval.py).
_DB_SQL = (
    "SELECT ID_T2S_EVALUATION AS id, ID_T2S_EVALUATION_CATEGORY AS category_id, "
    "QUESTION, QUESTION_FR, ASSERTIONS_QUERY_RESULT "
    "FROM T_WC_T2S_EVALUATION "
    "WHERE IS_EVAL = 1 "
    "AND (ASSERTIONS_QUERY_RESULT <> '' AND ASSERTIONS_QUERY_RESULT IS NOT NULL) "
    "AND (DELETED = 0 OR DELETED IS NULL) "
    "ORDER BY ID_T2S_EVALUATION ASC"
)


def _load_records_db() -> list[dict[str, Any]]:
    """Read evaluations straight from MariaDB, exactly where the evaluator reads
    them (T_WC_T2S_EVALUATION), reusing the same connection helper."""
    import citizenphil as cp  # lazy: keeps harness_lib importable without a DB
    conn = cp.f_getconnection()
    with conn.cursor() as cur:
        cur.execute(_DB_SQL)
        rows = cur.fetchall()
    print(f"Question bank: MariaDB T_WC_T2S_EVALUATION ({len(rows)} eval rows)")
    return [{
        "id": r.get("id"),
        "category_id": r.get("category_id"),
        "question_en": r.get("QUESTION"),
        "question_fr": r.get("QUESTION_FR"),
        "assertion": r.get("ASSERTIONS_QUERY_RESULT"),
    } for r in rows]


def _load_records_json() -> list[dict[str, Any]]:
    """Fallback: read the Phase 31 JSON exports (local dev / no DB creds)."""
    evals_dir = resolve_evals_dir()
    files = sorted(evals_dir.glob("*.json"))
    print(f"Question bank: {evals_dir} ({len(files)} json files)")
    if not files:
        print("  [!] No question-bank JSON found and no DB. The bank lives in MariaDB;")
        print("      set DB_HOST/DB_USER/... (e.g. via --env-file) to read it directly,")
        print("      or set HARNESS_EVALS_DIR to a folder of evaluation/*.json exports.")
    records: list[dict[str, Any]] = []
    for p in files:
        with p.open(encoding="utf-8") as f:
            e = json.load(f)
        if int(e.get("is_eval") or 0) != 1:
            continue
        records.append({
            "id": e.get("evaluation_id"),
            "category_id": e.get("evaluation_category_id"),
            "question_en": e.get("question_en"),
            "question_fr": e.get("question_fr"),
            "assertion": (e.get("assertions") or {}).get("query_result"),
        })
    return records


def _records_to_scenarios(records: list[dict[str, Any]], *, lang: str,
                          limit: Optional[int], category_ids: Optional[set[int]]) -> list[dict[str, Any]]:
    q_field = "question_en" if lang == "en" else "question_fr"
    scenarios: list[dict[str, Any]] = []
    for r in records:
        assertion = (r.get("assertion") or "").strip()
        if not assertion:
            continue
        cat_id = r.get("category_id")
        if category_ids is not None and cat_id not in category_ids:
            continue
        question = (r.get(q_field) or "").strip()
        if not question:
            continue
        scenarios.append({
            "id": r.get("id"),
            "category_id": cat_id,
            "lang": lang,
            "turns": [question],          # MVP: single user turn
            "assertion": assertion,
        })
    scenarios.sort(key=lambda s: (s["id"] if s["id"] is not None else 0))
    if limit is not None:
        scenarios = scenarios[:limit]
    return scenarios


def load_scenarios(
    *,
    lang: str = "en",
    limit: Optional[int] = None,
    category_ids: Optional[set[int]] = None,
    source: str = "auto",
) -> list[dict[str, Any]]:
    """Build 1-turn scenarios from the question bank.

    Source of truth is **MariaDB** (`T_WC_T2S_EVALUATION`), read exactly where the
    evaluator reads it. `source`:
      - "auto" (default): DB when DB creds are present (`DB_HOST` set), else JSON;
      - "db": force MariaDB;
      - "json": force the Phase 31 JSON exports.
    Only `is_eval == 1` rows with a non-empty `query_result` assertion are kept
    (the assertion is reused as-is — never invented). The `turns` list leaves room
    for scripted multi-turn follow-ups later.
    """
    if lang not in ("en", "fr"):
        raise ValueError("lang must be 'en' or 'fr'")
    if source not in ("auto", "db", "json"):
        raise ValueError("source must be 'auto', 'db' or 'json'")

    if source == "auto":
        source = "db" if os.getenv("DB_HOST") else "json"

    records = _load_records_db() if source == "db" else _load_records_json()
    return _records_to_scenarios(records, lang=lang, limit=limit, category_ids=category_ids)


# --------------------------------------------------------------------------- #
# Scoring (reuses the canonical DSL)
# --------------------------------------------------------------------------- #
def rows_to_df(rows: list[Any]) -> pd.DataFrame:
    """Mirror the single-turn evaluator's DataFrame construction."""
    return pd.DataFrame([
        (r.get("data") if isinstance(r, dict) else r)
        for r in (rows or [])
    ])


def score_result(rows: list[Any], assertion: str) -> tuple[bool, list[dict]]:
    """Score a result-set against a query_result assertion via the canonical DSL."""
    df = rows_to_df(rows)
    cleaned = html.unescape(str(assertion).strip())
    return t2s_eval.evaluate_dataframe_assertions(df, cleaned)


# --------------------------------------------------------------------------- #
# Tool-trace parsing + run classification
# --------------------------------------------------------------------------- #
def parse_tool_trace(tool_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a /text-chat tool_outputs list into query_text2sql calls and others.

    Each query_text2sql call is summarized as {args, result_count, error, rows,
    answer, forced}. The order is preserved so the first call is the server-forced
    one and any subsequent calls are the agent's own recovery attempts.
    """
    t2s_calls: list[dict[str, Any]] = []
    detail_calls: list[dict[str, Any]] = []
    for o in (tool_outputs or []):
        name = o.get("name")
        out = o.get("output") or {}
        if name == "query_text2sql":
            rows = out.get("rows") if isinstance(out, dict) else None
            rc = out.get("result_count") if isinstance(out, dict) else None
            if rc is None and isinstance(rows, list):
                rc = len(rows)
            t2s_calls.append({
                "args": o.get("args") or {},
                "result_count": rc,
                "error": (out.get("error") or "") if isinstance(out, dict) else "",
                "answer": (out.get("answer") or "") if isinstance(out, dict) else "",
                "rows": rows or [],
                # The voice-agent now surfaces a compact failure diagnostic in the
                # tool output (reason + unresolved_entities). Capture it so the
                # harness can report why a query came back empty; None when the
                # voice-agent build predates the diagnostic field.
                "diagnostic": out.get("diagnostic") if isinstance(out, dict) else None,
                "forced": bool(o.get("forced")),
            })
        else:
            detail_calls.append({"name": name, "args": o.get("args") or {}})
    return {
        "t2s_calls": t2s_calls,
        "detail_calls": detail_calls,
        "n_t2s": len(t2s_calls),
        "n_detail": len(detail_calls),
        "final_t2s": t2s_calls[-1] if t2s_calls else None,
        "first_t2s": t2s_calls[0] if t2s_calls else None,
    }


def _is_empty(call: Optional[dict[str, Any]]) -> bool:
    if not call:
        return True
    if call.get("error"):
        return True
    rc = call.get("result_count")
    return (rc is None) or (rc == 0)


def _reason(call: Optional[dict[str, Any]]) -> Optional[str]:
    """The diagnostic `reason` for one query_text2sql call, or None if absent.

    Observability only: it does NOT feed the recovery classification (that stays
    based on _is_empty so baseline runs remain comparable). None when the
    voice-agent build did not emit a `diagnostic`.
    """
    if not call:
        return None
    diag = call.get("diagnostic")
    return diag.get("reason") if isinstance(diag, dict) else None


def classify_run(trace: dict[str, Any], assertion: str,
                 final_answer_text: str = "") -> dict[str, Any]:
    """Score the final result and label the recovery behaviour of one run."""
    final = trace.get("final_t2s")
    first = trace.get("first_t2s")
    n_t2s = trace.get("n_t2s", 0)

    if final is not None:
        passed, details = score_result(final["rows"], assertion)
    else:
        passed, details = False, [{"passed": False, "message": "no query_text2sql call"}]

    initial_empty = _is_empty(first)
    final_empty = _is_empty(final)
    retry_attempted = n_t2s > 1
    recovered = bool(initial_empty and passed)

    if passed and not retry_attempted:
        strategy = "direct_success"
    elif passed and retry_attempted:
        strategy = "recovered_by_retry"
    elif (not passed) and retry_attempted:
        strategy = "retried_but_failed"
    elif (not passed) and initial_empty:
        strategy = "gave_up_empty"
    else:  # not passed, not retried, had rows
        strategy = "wrong_result_no_retry"

    # Anti-cheat heuristic: a non-empty spoken answer on an empty final result set
    # may be an ungrounded (parametric) answer. We can't be certain (it could be a
    # clarification), so we only flag it.
    answer_without_result = bool(final_empty and (final_answer_text or "").strip())

    return {
        "passed": passed,
        "initial_empty": initial_empty,
        "final_empty": final_empty,
        "retry_attempted": retry_attempted,
        "recovered": recovered,
        "strategy": strategy,
        "answer_without_result": answer_without_result,
        "n_t2s_calls": n_t2s,
        "n_detail_calls": trace.get("n_detail", 0),
        "final_result_count": (final or {}).get("result_count"),
        # Diagnostic reason of the forced first query and of the final query
        # (None when the voice-agent build predates the diagnostic field).
        "initial_diagnostic_reason": _reason(first),
        "final_diagnostic_reason": _reason(final),
        "details": details,
    }


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-scenario classifications into the headline metrics."""
    scored = [r for r in results if not r.get("run_error")]
    n = len(scored)
    if n == 0:
        return {"n": 0}

    n_pass = sum(1 for r in scored if r["passed"])
    n_initial_empty = sum(1 for r in scored if r["initial_empty"])
    n_recovered = sum(1 for r in scored if r["recovered"])
    n_retry = sum(1 for r in scored if r["retry_attempted"])
    n_answer_without_result = sum(1 for r in scored if r["answer_without_result"])
    t2s_calls = [r["n_t2s_calls"] for r in scored]

    strat: dict[str, int] = {}
    for r in scored:
        strat[r["strategy"]] = strat.get(r["strategy"], 0) + 1

    # Distribution of the diagnostic reason the agent saw on the forced first query.
    # Empty when the voice-agent build did not emit a diagnostic (observability only).
    diag_hist: dict[str, int] = {}
    for r in scored:
        reason = r.get("initial_diagnostic_reason")
        if reason:
            diag_hist[reason] = diag_hist.get(reason, 0) + 1

    return {
        "n": n,
        "run_errors": sum(1 for r in results if r.get("run_error")),
        "task_success": n_pass,
        "task_success_rate": round(100.0 * n_pass / n, 1),
        "n_initial_empty": n_initial_empty,
        "n_recovered": n_recovered,
        # the headline metric of the baseline:
        "empty_result_recovery_rate": (
            round(100.0 * n_recovered / n_initial_empty, 1) if n_initial_empty else None
        ),
        "retry_attempt_rate": round(100.0 * n_retry / n, 1),
        "avg_t2s_calls": round(sum(t2s_calls) / n, 2),
        "answer_without_result": n_answer_without_result,
        "strategy_histogram": dict(sorted(strat.items(), key=lambda kv: -kv[1])),
        "initial_diagnostic_histogram": dict(sorted(diag_hist.items(), key=lambda kv: -kv[1])),
    }
