"""Offline self-test for harness_lib (no network, no LLM).

Exercises the scorer (real DSL + pandas), the recovery classification, and the
aggregation, plus a real load of a few scenarios from the question bank.

Run:  cd eval && python harness/selftest.py
"""
import harness_lib as H


def _t2s(rows, result_count=None, error="", forced=False, diagnostic=None):
    out = {"rows": rows, "result_count": result_count if result_count is not None else len(rows), "error": error}
    if diagnostic is not None:
        out["diagnostic"] = diagnostic
    return {"name": "query_text2sql", "args": {}, "output": out, "forced": forced}


def _row(d):
    return {"index": 0, "data": d}


def case(tool_outputs, assertion, answer_text=""):
    trace = H.parse_tool_trace(tool_outputs)
    return H.classify_run(trace, assertion, final_answer_text=answer_text)


def main() -> None:
    failures = []

    def check(name, cond):
        print(f"  [{'OK ' if cond else 'XX '}] {name}")
        if not cond:
            failures.append(name)

    print("1. scoring reuses the canonical DSL")
    passed, _ = H.score_result([_row({"ID_MOVIE": 22596})], "ID_MOVIE IN (22596)")
    check("present value passes", passed is True)
    passed, _ = H.score_result([_row({"ID_MOVIE": 111})], "ID_MOVIE IN (22596)")
    check("absent value fails", passed is False)
    passed, _ = H.score_result([], "COUNT(*) == 0")
    check("empty df passes COUNT(*)==0", passed is True)
    passed, _ = H.score_result([], "COUNT(*) == 1")
    check("empty df fails COUNT(*)==1", passed is False)

    print("2. run classification")
    direct = case([_t2s([_row({"ID_MOVIE": 22596})], forced=True)], "ID_MOVIE IN (22596)")
    check("direct_success", direct["strategy"] == "direct_success" and direct["passed"] and not direct["initial_empty"])

    recovered = case(
        [_t2s([], result_count=0, forced=True), _t2s([_row({"ID_MOVIE": 22596})])],
        "ID_MOVIE IN (22596)",
    )
    check("recovered_by_retry", recovered["strategy"] == "recovered_by_retry"
          and recovered["recovered"] and recovered["initial_empty"] and recovered["n_t2s_calls"] == 2)

    gave_up = case([_t2s([], result_count=0, forced=True)], "COUNT(*) == 1", answer_text="There are none.")
    check("gave_up_empty", gave_up["strategy"] == "gave_up_empty" and not gave_up["recovered"])
    check("answer_without_result flagged", gave_up["answer_without_result"] is True)

    retried_failed = case(
        [_t2s([], result_count=0, forced=True), _t2s([], result_count=0)],
        "COUNT(*) == 1",
    )
    check("retried_but_failed", retried_failed["strategy"] == "retried_but_failed" and not retried_failed["recovered"])

    wrong = case([_t2s([_row({"ID_MOVIE": 111})], forced=True)], "ID_MOVIE IN (22596)")
    check("wrong_result_no_retry", wrong["strategy"] == "wrong_result_no_retry" and not wrong["initial_empty"])

    print("2b. diagnostic reason captured (observability, no behaviour change)")
    diag = case(
        [_t2s([], result_count=0, forced=True,
              diagnostic={"reason": "entity_unresolved", "unresolved_entities": ["Rohmer"]})],
        "COUNT(*) == 1",
    )
    check("initial_diagnostic_reason surfaced", diag["initial_diagnostic_reason"] == "entity_unresolved")
    check("final_diagnostic_reason surfaced", diag["final_diagnostic_reason"] == "entity_unresolved")
    check("strategy unaffected by diagnostic", diag["strategy"] == "gave_up_empty")
    no_diag = case([_t2s([], result_count=0, forced=True)], "COUNT(*) == 1")
    check("reason None without diagnostic", no_diag["initial_diagnostic_reason"] is None)

    print("3. aggregation")
    agg = H.aggregate([direct, recovered, gave_up, retried_failed, wrong, diag])
    check("n == 6", agg["n"] == 6)
    check("n_initial_empty == 4", agg["n_initial_empty"] == 4)
    check("avg_t2s_calls == 1.33", agg["avg_t2s_calls"] == 1.33)
    check("answer_without_result == 1", agg["answer_without_result"] == 1)
    check("initial_diagnostic_histogram counts the reason",
          agg["initial_diagnostic_histogram"] == {"entity_unresolved": 1})

    print("4. real scenario loading from the question bank (json source)")
    scen = H.load_scenarios(lang="en", limit=3, source="json")
    check("loaded up to 3 scenarios", 0 < len(scen) <= 3)
    check("scenarios well-formed", all(
        s.get("assertion") and s.get("turns") and s.get("id") is not None for s in scen
    ))

    print()
    if failures:
        print(f"SELFTEST FAILED: {len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("SELFTEST PASSED (all checks green)")


if __name__ == "__main__":
    main()
