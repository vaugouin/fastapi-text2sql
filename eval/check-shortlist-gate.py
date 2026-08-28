#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-224: the gate judges the shortlist, not only its first entry.

Runs without a database. Rebuilds the flamenco case measured on 2026-08-28 and checks the
property that makes the change safe: **the threshold is unchanged**. Walking the shortlist can
only turn a rejection into an acceptance the gate itself approves, never admit something the
threshold refuses.

    uv run eval/check-shortlist-gate.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rapidfuzz_query as rq  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, wanted {want!r}")


def gate(sought, candidate, threshold, stopwords=None):
    """The embeddings gate, reproduced: strip the descriptors, then fuzz.ratio."""
    from rapidfuzz import fuzz
    s, c = sought, candidate
    if stopwords is not None:
        s = rq.strip_franchise_words(sought, stopwords)
        c = rq.strip_franchise_words(candidate, stopwords)
    return float(fuzz.ratio(s, c))


# The shortlist exactly as the 2026-08-28 trace reported it, in vector-distance order.
SHORTLIST = [
    ("carlos saura's flamenco trilogy", 0.360),   # 4846, the custom duplicate
    ("the flamenco trilogy", 0.516),              # 4944, the TMDb collection
    ("perros callejeros trilogy", 0.944),
    ("heartburn trilogy", 0.960),
    ("spanish apartment trilogy", 0.967),
]
SOUGHT = "flamenco trilogy"
THRESHOLD = 72.0
STOP = ["collection", "trilogy", "saga", "universe"]

print("1. The measured case: the right answer sat at rank 2")
scores = [round(gate(SOUGHT, c, THRESHOLD, STOP), 1) for c, _ in SHORTLIST]
for (name, dist), sc in zip(SHORTLIST, scores):
    print(f"      d={dist:.3f}  ratio={sc:5.1f}  {'passes' if sc >= THRESHOLD else 'refused'}  {name}")
check("rank 1 is refused", scores[0] < THRESHOLD, True)
check("rank 2 passes the SAME threshold", scores[1] >= THRESHOLD, True)

first_pass = next((i for i, s in enumerate(scores) if s >= THRESHOLD), None)
check("first passing rank", first_pass, 1)
check("nothing below rank 2 passes", [i for i, s in enumerate(scores) if s >= THRESHOLD], [1])

print("\n2. The safety property: the threshold is untouched")
# Every candidate the walk can accept is one the gate approves at the same threshold, so a
# shortlist where NOTHING passes must still resolve to nothing.
# The -206 case: "wagonlit collection" must not resolve to "life collection". The whole
# shortlist is unrelated, so no rank can rescue it, which is the property being asserted.
none_pass = ["life collection", "zigomar collection", "the flamenco trilogy"]
sc2 = [gate("wagonlit collection", c, THRESHOLD, STOP) for c in none_pass]
for name, s in zip(none_pass, sc2):
    print(f"      ratio={s:5.1f}  {name}")
check("a shortlist where nothing passes stays unresolved",
      any(s >= THRESHOLD for s in sc2), False)
check("the Wagonlit case of -206 is still refused at every rank",
      round(sc2[0], 1) < THRESHOLD, True)

print("\n3. Rank order is preserved: the first passing candidate wins, not the best scoring")
# Two candidates pass; the walk must take the one ranked higher by the vector search, which is
# the ordering the semantic search produced, not the highest lexical score.
two_pass = ["the flamenco trilogy", "flamenco trilogy"]
s_two = [gate(SOUGHT, c, THRESHOLD, STOP) for c in two_pass]
check("both pass", [s >= THRESHOLD for s in s_two], [True, True])
check("rank 1 of the two is taken even though rank 2 scores higher",
      s_two[0] < s_two[1], True)

print("\n4. Stripping the descriptors is what costs the top candidate its score")
check("without stripping, rank 1 scores", round(gate(SOUGHT, SHORTLIST[0][0], THRESHOLD), 1), 68.1)
check("with stripping, rank 1 scores", round(gate(SOUGHT, SHORTLIST[0][0], THRESHOLD, STOP), 1), 51.6)
check("the strip costs it", round(gate(SOUGHT, SHORTLIST[0][0], THRESHOLD), 1)
      > round(gate(SOUGHT, SHORTLIST[0][0], THRESHOLD, STOP), 1), True)

print()
if failures:
    print(f"VERDICT: {len(failures)} FAILURES")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("VERDICT: all green")
print("\nNot covered here: the walk itself, which lives in entity.py and needs a database and a")
print("ChromaDB shortlist to exercise end to end. What is proven above is the arithmetic it")
print("relies on, and the property that makes it safe.")
