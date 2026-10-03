"""FASTAPI-TEXT2SQL-301: offline checks of the subset helpers (no database, no API).

    uv run --no-project --with pandas eval/test-subset-301.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import text2sql_eval_functions as t2s_eval

failures = 0


def check(label, got, expected):
    global failures
    ok = got == expected
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n      got      {got!r}\n      expected {expected!r}"))


# parse_eval_ids: separators, comments, duplicates, order
check("ids: commas, spaces, newlines, comments, duplicates",
      t2s_eval.parse_eval_ids("12, 7\n# the Varda ones\n7 3;40  # trailing\n\n"), [3, 7, 12, 40])
check("ids: empty text", t2s_eval.parse_eval_ids(""), [])
try:
    t2s_eval.parse_eval_ids("12, x7")
    check("ids: a non-number is refused", "accepted", "ValueError")
except ValueError:
    check("ids: a non-number is refused", "ValueError", "ValueError")

# ids_in_clause: an empty subset matches nothing, never everything
check("clause: sorted and deduplicated", t2s_eval.ids_in_clause("EE.ID_T2S_EVALUATION", [5, 2, 5]),
      "AND EE.ID_T2S_EVALUATION IN (2, 5) ")
check("clause: empty subset matches nothing", t2s_eval.ids_in_clause("ID_T2S_EVALUATION", []),
      "AND ID_T2S_EVALUATION IN (-1) ")


# escalated_subset: the union, its halves, and the baseline it reads
class FakeCursor:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.answers.pop(0)


cur = FakeCursor([[{"id": 10}, {"id": 11}], [{"id": 11}, {"id": 99}]])
ds = t2s_eval.escalated_subset(cur, "001.001.019", "gpt-6-sol", "gpt-6-sol", "gpt-4o",
                               "AND (x.RESULT_ENTITY_MODEL = 'gpt-4o' OR x.RESULT_ENTITY_MODEL IS NULL) ", ["en"])
check("subset: union of escalated and declared", ds["ids"], [10, 11, 99])
check("subset: halves", (ds["escalated"], ds["declared"], ds["declared_not_escalated"]), (2, 2, 1))
sql, params = cur.calls[0]
check("subset: baseline read with the swapped complex model and the challenger's other models",
      params, ("001.001.019", "gpt-6-sol", "gpt-6-sol", "gpt-4o", "en"))
check("subset: only escalated baseline rows", "x.COMPLEX_MODEL_USED = 1" in sql, True)
check("subset: late clause inserted once, no doubled AND", ("AND AND" in sql, sql.count("x.RESULT_ENTITY_MODEL = 'gpt-4o'")), (False, 1))
check("subset: declared half reads RESOLUTION_MODE", "RESOLUTION_MODE = 'complex'" in cur.calls[1][0], True)
cur = FakeCursor([[], []])
ds = t2s_eval.escalated_subset(cur, "001.001.019", "a", "b", "c", "", ["*"])
check("subset: '*' reads both languages", cur.calls[0][1][-2:], ("en", "fr"))


# head_to_head: compared pairs, wins, losses, and what is counted apart
def row(i, lang, score, esc, total=None, cx=None):
    return {"ID_T2S_EVALUATION": i, "LANG": lang, "ASSERTIONS_TOTAL_SCORE": score,
            "COMPLEX_MODEL_USED": esc, "TOTAL_PROCESSING_TIME": total, "COMPLEX_QUESTION_PROCESSING_TIME": cx}


base = [row(1, "en", 1, 1, 4.0, 1.0), row(2, "en", 0, 1, 6.0, 2.0), row(3, "en", 1, 1), row(4, "en", 0, 0),
        row(5, "en", 1, 1), row(6, "en", None, 1), row(7, "en", 1, 1)]
chal = [row(1, "en", 1, 1, 10.0, 7.0), row(2, "en", 1, 1, 30.0, 25.0), row(3, "en", 0, 1), row(4, "en", 1, 1),
        row(5, "en", 0, 0), row(6, "en", 1, 1), row(8, "en", 1, 1)]
h = t2s_eval.head_to_head(base, chal)
check("h2h: compared = both scored and both escalated", h["compared"], [(1, "en"), (2, "en"), (3, "en")])
check("h2h: pass counts", (h["baseline_pass"], h["challenger_pass"]), (2, 2))
check("h2h: won and lost", (h["won"], h["lost"]), ([(2, "en")], [(3, "en")]))
check("h2h: not escalated, per side", (h["not_escalated_baseline"], h["not_escalated_challenger"]), ([(4, "en")], [(5, "en")]))
check("h2h: unscored apart", h["unscored"], [(6, "en")])
check("h2h: one-sided pairs", (h["only_baseline"], h["only_challenger"]), ([(7, "en")], [(8, "en")]))
check("h2h: times only on compared pairs that carry them",
      (h["baseline_total_time"], h["challenger_complex_time"]), ([4.0, 6.0], [7.0, 25.0]))
check("h2h: languages are separate pairs",
      t2s_eval.head_to_head([row(1, "en", 1, 1)], [row(1, "fr", 1, 1)])["compared"], [])
check("median", (t2s_eval.median([3, 1, 2]), t2s_eval.median([4, 1, 2, 3]), t2s_eval.median([])), (2, 2.5, None))

print(f"\n{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
