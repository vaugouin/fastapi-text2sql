#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-214 / -218: check the scoring metrics without a database.

Sits next to `bench-entity-resolution.py`, which calibrates thresholds against the real
tables. This one needs no database at all: it feeds `rank_candidates` the rows the SELECT
would have returned, which is exactly the layer where both defects lived, and asserts the
behaviour the two tickets specify.

    uv run eval/check-score-metrics.py

Exits non-zero on the first broken expectation, so it can gate a deploy.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rapidfuzz_query as rq  # noqa: E402

CFG = json.load(io.open(ROOT / "data" / "entity_resolution.json", encoding="utf-8"))
ALIAS = next(
    s
    for e in CFG
    if e["placeholder_prefix"] == "Person_name"
    for s in e["search_list"]
    if s["strtablename"] == "T_WC_TMDB_PERSON_ALSO_KNOWN_AS"
)
METRIC = ALIAS.get("score_metric")
EXTRA = ALIAS.get("max_extra_tokens", rq.DEFAULT_MAX_EXTRA_TOKENS)
THRESHOLD = ALIAS["min_fuzz_ratio"]

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, wanted {want!r}")


def rank(q: str, rows: list[dict]) -> list[dict]:
    return rq.rank_candidates(
        "ID_ROW", "PERSON_NAME", "PERSON_NAME_NORM", "POPULARITY",
        q, rows, score_metric=METRIC, max_extra_tokens=EXTRA,
    )


def row(i: int, name: str, pop: float, id_person: int) -> dict:
    return {
        "ID_ROW": i, "PERSON_NAME": name, "PERSON_NAME_NORM": name.lower(),
        "POPULARITY": pop, "ID_PERSON": id_person,
    }


print(f"alias strategy: metric={METRIC} max_extra_tokens={EXTRA} min_fuzz_ratio={THRESHOLD}")
print(f"tie-break column={ALIAS['rapidfuzz_col_popularity']} join={bool(ALIAS.get('popularity_join'))}\n")

print("1. Michael Caine, the case the trace of 2026-08-26 showed")
# The trace retained 'Maurice Maurice' at 71: WRatio gave both candidates 95.0 and the tie fell
# to ID_PERSON, so the recently added unknown beat Michael Caine (id 3895).
caine = [row(1, "Maurice Joseph Micklewhite", 12.4, 3895), row(2, "Maurice Maurice", 0.6, 2400000)]
r = rank("maurice micklewhite", caine)
check("best candidate", r[0]["PERSON_NAME"], "Maurice Joseph Micklewhite")
check("score", r[0]["SCORE"], 100.0)
check("passes the gate", r[0]["SCORE"] >= THRESHOLD, True)
check("ID_PERSON survives for resolve_to_canonical", r[0].get("ID_PERSON"), 3895)

print("\n1bis. The same case with the string TMDb actually holds (Philippe, 2026-08-26)")
# "Maurice Joseph Micklewhite Jr." is +2 tokens from the two-word form, which the extra-token
# guard refused until generational suffixes were neutralised.
DB_CAINE = "maurice joseph micklewhite jr"
check("the two-word form now reaches it", rq.score_token_subset("maurice micklewhite", DB_CAINE, max_extra_tokens=EXTRA), 100.0)
check("the full form still does", rq.score_token_subset("maurice joseph micklewhite", DB_CAINE, max_extra_tokens=EXTRA), 100.0)
check("typing the suffix too is harmless", rq.score_token_subset("maurice micklewhite jr", DB_CAINE, max_extra_tokens=EXTRA), 100.0)
check("plain ratio is untouched by the suffix rule", round(rq.score_ratio("maurice micklewhite", DB_CAINE), 1), 79.2)
check("the wildcard door stays shut", rq.score_token_subset("sarah connor", "sarah connor jones smith", max_extra_tokens=EXTRA) < THRESHOLD, True)

print("\n2. John Wayne, the case -214 was written on")
r = rank("marion morrison", [row(1, "Marion Robert Morrison", 9.8, 4165), row(2, "Marion Yue", 0.1, 1900000)])
check("best candidate", r[0]["PERSON_NAME"], "Marion Robert Morrison")
check("passes the gate", r[0]["SCORE"] >= THRESHOLD, True)

print("\n3. Two-token guard: one word is a prefix, not an inclusion")
check("'marion' alone refused", rq.score_token_subset("marion", "marion robert morrison") < THRESHOLD, True)
check("'maurice' alone refused", rq.score_token_subset("maurice", "maurice joseph micklewhite") < THRESHOLD, True)

print("\n4. Extra-token guard: a middle name, not a wildcard")
check("+1 token accepted", rq.score_token_subset("sarah connor", "sarah connor jones"), 100.0)
check("+2 tokens refused", rq.score_token_subset("sarah connor", "sarah connor jones smith") < THRESHOLD, True)
check("token order irrelevant", rq.score_token_subset("marion morrison", "morrison marion robert"), 100.0)

print("\n5. Monotone: token_subset never scores below ratio, so the old threshold stays valid")
pairs = [
    ("marion morrison", "marion robert morrison"), ("bruce lee", "bruce li"),
    ("maurice scherer", "maurice scherer"), ("zamboni trask", "massimo zamboni"),
    ("quentin tarentino", "quentin tarantino"), ("a b", "c d"),
]
check("min(token_subset - ratio) >= 0",
      min(rq.score_token_subset(a, b) - rq.score_ratio(a, b) for a, b in pairs) >= 0, True)

print("\n6. Collections keep `ratio`: no strategy inherits the new metric by accident")
check("default metric is ratio", rq.resolve_score_metric(None) is rq.score_ratio, True)
check("an unknown name degrades, never raises", rq.resolve_score_metric("nonsense") is rq.score_ratio, True)
coll = rq.rank_candidates("ID", "NAME", "NORM", "POP", "wagonlit collection",
                          [{"ID": 1, "NAME": "Life Collection", "NORM": "life collection", "POP": 5}])
check("the Wagonlit case still scores 76.5", round(coll[0]["SCORE"], 1), 76.5)

print("\n7. decide_autocorrect still reads the WRatio scale it was calibrated on")
auto, best, reason = rq.decide_autocorrect(rank("maurice micklewhite", caine))
check("the reason quotes a WRatio-scale score", "95.0" in reason, True)

print("\n8. The SELECT head keeps the join key it used to get by accident")
sql = rq.build_select_prefix("T_WC_TMDB_PERSON_ALSO_KNOWN_AS", "ID_ROW", "PERSON_NAME",
                             "PERSON_NAME_NORM", "POPULARITY", ALIAS.get("popularity_join"))
check("joins T_WC_T2S_PERSON", "LEFT JOIN `T_WC_T2S_PERSON`" in sql, True)
check("selects ID_PERSON", "`t`.`ID_PERSON`" in sql, True)
check("aliases the joined popularity", "AS `POPULARITY`" in sql, True)
check("no join when unconfigured",
      "JOIN" not in rq.build_select_prefix("T_WC_T2S_PERSON", "ID_PERSON", "PERSON_NAME",
                                           "PERSON_NAME_NORM", "POPULARITY", None), True)

print()
if failures:
    print(f"VERDICT: {len(failures)} FAILURES")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("VERDICT: all green")
print("\nNot covered here, and it is the part that matters next: nothing was run against the")
print("real database. -214 point 3 (recalibrate the threshold on the bench) and the evaluations")
print("both need it.")
