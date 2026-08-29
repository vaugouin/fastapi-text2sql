#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-224: execute the real branch, not a reimplementation of its arithmetic.

Why this exists. On 2026-08-29 the -224 refactor shipped a NameError that broke every
embeddings resolution and was only found on the next restart. `ast.parse` passed, `import
entity` passed, and `eval/check-shortlist-gate.py` passed too, because it reproduced the
arithmetic in a standalone function and never entered `plan_entity_resolutions`. An unexercised
branch is what that outage cost, so this drives the branch itself.

`plan_entity_resolutions` takes its ChromaDB collections as a parameter, so the shortlist
measured in production can be injected verbatim. The rapidfuzz strategy that runs first needs a
real cursor; its block ends in `except Exception: continue`, so a cursor that raises makes it
fall through to the embeddings strategy exactly as it did in production, where
`require_confident` refused on a zero margin.

    uv run eval/check-shortlist-gate-branch.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import entity  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, wanted {want!r}")


class _Cursor:
    """A database that answers, and finds nothing.

    Raising was the first attempt and it taught something: the exception surfaced only on the
    flamenco run, never on the one where no candidate passes. The rescue had therefore accepted
    a candidate and moved on to the row lookup that follows acceptance. Returning empty rows
    instead keeps the rapidfuzz strategy falling through, as it does in production where
    require_confident refuses on a zero margin, and lets the post-gate lookup end quietly.
    """
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return None

    def fetchone(self, *a, **k):
        return None

    def fetchall(self, *a, **k):
        return []


class _Connection:
    def cursor(self):
        return _Cursor()


class _Collection:
    """The shortlist exactly as production reported it on 2026-08-28."""
    def query(self, query_texts=None, n_results=10, where=None):
        return {
            "documents": [[
                "Carlos Saura's Flamenco trilogy",   # 4846, refused at 52
                "The Flamenco Trilogy",              # 4944, passes at 80
                "Perros Callejeros Trilogy",
                "Heartburn Trilogy",
                "Spanish Apartment Trilogy",
            ]],
            "ids": [["collectionid_4846_en", "collectionid_4944_en", "collectionid_1350_en",
                     "collectionid_4116_en", "collectionid_1141_en"]],
            "distances": [[0.360, 0.516, 0.944, 0.960, 0.967]],
        }


def run(value):
    result = entity.plan_entity_resolutions(
        connection=_Connection(),
        entity_extraction={"question": "Movies in the {{Collection_name1}}",
                           "Collection_name1": value},
        chromadb_collections_by_name={"collections": _Collection()},
    )
    notes = []
    for planned in result.get("entities") or []:
        notes.extend(getattr(planned, "messages", None) or getattr(planned, "notes", None) or [])
    return [str(n) for n in notes]


print("1. The branch runs at all (the check yesterday's outage did not have)")
try:
    notes = run("flamenco trilogy")
    ran = True
except Exception as exc:                                        # noqa: BLE001
    ran = False
    notes = []
    print(f"       raised: {type(exc).__name__}: {exc}")
check("plan_entity_resolutions completes without raising", ran, True)

joined = " | ".join(notes)
print("\n   trace emitted:")
for n in notes:
    print(f"       {n[:120]}")

print("")
print("2. On bare names the pre-existing rerank already picks the right row")
# A correction of what this file first claimed. It asserted "the rescue fires", and the rescue
# never ran: on bare collection names the WRatio rerank of 2026-06-24 scores "the flamenco
# trilogy" at 95 against 90 for "carlos saura's flamenco trilogy", so it selects rank 2 by
# itself and the gate accepts it at 80. The -224 walk has nothing left to do here.
#
# Which means production, where the gate DID refuse rank 1, is not comparing bare names. What
# it indexes cannot be known from this side, and the rejection trace now prints the documents
# so the next occurrence answers it. Until then this file does NOT cover the rescue path, and
# saying so is the point: an assertion that passes for a reason other than the one it names is
# worse than an absent one, which is the lesson of -216.
check("resolution lands on the TMDb collection 4944", "docid=4944" in joined, True)
check("no rejection was emitted", "rejected best embeddings candidate" in joined, False)
check("the rescue did NOT need to fire here", "found at rank" in joined, False)

print("\n3. A shortlist where nothing passes still refuses")


class _NoneMatch(_Collection):
    def query(self, query_texts=None, n_results=10, where=None):
        return {
            "documents": [["Life Collection", "Zigomar Collection", "The Flamenco Trilogy"]],
            "ids": [["collectionid_1_en", "collectionid_2_en", "collectionid_3_en"]],
            "distances": [[0.4, 0.5, 0.6]],
        }


saved = entity.plan_entity_resolutions
try:
    notes2 = []
    res2 = entity.plan_entity_resolutions(
        connection=_Connection(),
        entity_extraction={"question": "Movies in the {{Collection_name1}}",
                           "Collection_name1": "wagonlit collection"},
        chromadb_collections_by_name={"collections": _NoneMatch()},
    )
    for planned in res2.get("entities") or []:
        notes2.extend(getattr(planned, "messages", None) or getattr(planned, "notes", None) or [])
    joined2 = " | ".join(str(n) for n in notes2)
except Exception as exc:                                        # noqa: BLE001
    joined2 = f"raised {exc}"
check("nothing is rescued", "found at rank" in joined2, False)
check("the Wagonlit case of -206 is still refused",
      "rejected best embeddings candidate" in joined2, True)

print()
if failures:
    print(f"VERDICT: {len(failures)} FAILURES")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("VERDICT: all green, and this time the branch really ran")
print()
print("Covered: the branch executes end to end, which is exactly what the NameError of")
print("2026-08-29 slipped through, and a shortlist where nothing passes is still refused.")
print("NOT covered: the -224 rescue itself, unreachable on bare names because the rerank")
print("already selects the right row. Reproducing production needs the documents it indexes.")
