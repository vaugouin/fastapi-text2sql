#!/usr/bin/env python3
"""FASTAPI-TEXT2SQL-309: the typographic rescue of the embeddings gate, run on the real branch.

Why this exists. Eval 475, "Movie Bell' Antonio": the vector search put the right film, "Il
bell'Antonio" (TMDb 76157), at rank 1 of the shortlist (distance 0.361), and the gate refused it at
fuzz.ratio 85.7 for a movie threshold of 85.85. One of the four characters counted against it is
the space typed after the elision apostrophe. The fix is a second pass over the same shortlist,
normalised strings, same threshold, reached only when the first pass refused every candidate.

Like eval/check-shortlist-gate-branch.py, this drives `plan_entity_resolutions` itself with the
shortlist production printed on 2026-10-04, rather than reimplementing the arithmetic: an
unexercised branch is what the 2026-08-29 outage cost. No database, no ChromaDB, no LLM.

    uv run eval/check-rescue-309.py
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import entity  # noqa: E402
import rapidfuzz_query  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, wanted {want!r}")


# The rows the movie table holds for the ids of the shortlist, so an accepted candidate reaches
# the real substitution, as in production. Any other query (the rapidfuzz strategies) finds nothing.
_MOVIE_ROWS = {
    "76157": {"ID_MOVIE": 76157, "MOVIE_TITLE": "Il bell'Antonio", "MOVIE_TITLE_FR": "Le Bel Antonio",
              "ORIGINAL_TITLE": "Il bell'Antonio"},
    "284204": {"ID_MOVIE": 284204, "MOVIE_TITLE": "Mister Antonio", "MOVIE_TITLE_FR": "Mister Antonio",
               "ORIGINAL_TITLE": "Mister Antonio"},
    "204765": {"ID_MOVIE": 204765, "MOVIE_TITLE": "Prêt à tout", "MOVIE_TITLE_FR": "Prêt à tout",
               "ORIGINAL_TITLE": "Prêt à tout"},
    "577": {"ID_MOVIE": 577, "MOVIE_TITLE": "To Die For", "MOVIE_TITLE_FR": "Prête à tout",
            "ORIGINAL_TITLE": "To Die For"},
    "1088829": {"ID_MOVIE": 1088829, "MOVIE_TITLE": "Antonio", "MOVIE_TITLE_FR": "Antonio",
                "ORIGINAL_TITLE": "Antonio"},
}


class _Cursor:
    """A database that knows the shortlist's movie rows and nothing else."""
    def __init__(self):
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None, *a, **k):
        self._rows = []
        if "FROM T_WC_T2S_MOVIE WHERE ID_MOVIE" in str(sql) and params:
            row = _MOVIE_ROWS.get(str(params[0]))
            self._rows = [row] if row else []
        return None

    def fetchone(self, *a, **k):
        return self._rows[0] if self._rows else None

    def fetchall(self, *a, **k):
        return list(self._rows)

    def close(self):
        return None


class _Connection:
    def cursor(self):
        return _Cursor()


class _Movies:
    """The shortlist of eval 475 as the production trace printed it on 2026-10-04."""
    def query(self, query_texts=None, n_results=10, where=None):
        return {
            "documents": [["Il bell'Antonio", "Il bell'Antonio", "Le Bel Antonio",
                           "Mister Antonio", "Antonio"]],
            "ids": [["movieid_76157_it", "movieid_76157_en", "movieid_76157_fr",
                     "movieid_284204_en", "movieid_1088829_en"]],
            "distances": [[0.361, 0.361, 0.519, 0.622, 0.622]],
        }


class _Strangers(_Movies):
    def query(self, query_texts=None, n_results=10, where=None):
        return {
            "documents": [["L'Avventura", "Mister Antonio", "Antonio"]],
            "ids": [["movieid_1_en", "movieid_284204_en", "movieid_1088829_en"]],
            "distances": [[0.70, 0.75, 0.80]],
        }


class _NearHomonyms(_Movies):
    """eval-309, 2026-10-04: "Prête à tout" typed without accents. Two French titles one letter
    apart once accents are folded, the wrong one ranked first by the vector search."""
    def query(self, query_texts=None, n_results=10, where=None):
        return {
            "documents": [["Prêt à tout", "Prête à tout", "Antonio"]],
            "ids": [["movieid_204765_fr", "movieid_577_fr", "movieid_1088829_en"]],
            "distances": [[0.358, 0.402, 0.80]],
        }


def run(value, collection=None):
    result = entity.plan_entity_resolutions(
        connection=_Connection(),
        entity_extraction={"question": "Movie {{Movie_title1}}", "Movie_title1": value},
        chromadb_collections_by_name={"movies": collection or _Movies()},
    )
    notes = []
    for planned in result.get("entities") or []:
        notes.extend(getattr(planned, "messages", None) or getattr(planned, "notes", None) or [])
        # The raw fallback is a flag on the plan, not a note: its message is only emitted at
        # substitution time. Surfaced here so the checks below can read it in one place.
        if getattr(planned, "is_raw_fallback", False):
            notes.append("raw fallback")
        if getattr(planned, "final_message", None):
            notes.append(str(planned.final_message))
    scores = [s for s in (result.get("match_scores") or []) if s.get("search_mode") == "embeddings"]
    return " | ".join(str(n) for n in notes), (scores[-1] if scores else {})


print("1. The normaliser")
n = rapidfuzz_query.normalize_apostrophes
check("space after an elision removed", n("bell' antonio"), "bell'antonio")
check("curly apostrophe made straight", n("bell’antonio"), "bell'antonio")
check("spaces on both sides removed", n("rock 'n' roll"), "rock'n'roll")
check("possessive unchanged", n("schindler's list"), "schindler's list")
check("no apostrophe, unchanged", n("la haine"), "la haine")
check("idempotent", n(n("l’ avventura")), n("l’ avventura"))

a = rapidfuzz_query.apply_rescue_normalizers
check("accents folded", a("amélie", ["accents"]), "amelie")
check("dashes become a space", a("spider-man", ["dashes"]), "spider man")
check("punctuation dropped", a("mission: impossible!", ["punctuation"]), "mission impossible")
check("canonical order: the acute accent is an apostrophe, not a diacritic",
      a("bell´ antonio", ["accents", "apostrophes"]), "bell'antonio")
check("full stage, the whole list", rapidfuzz_query.RESCUE_STAGES["full"],
      ["apostrophes", "accents", "dashes", "punctuation"])
try:
    a("x", ["accent"])
    raised = False
except KeyError:
    raised = True
check("unknown normaliser raises", raised, True)

print("\n2. Eval 475, English spelling: the first pass refuses, the rescue accepts rank 1")
joined, score = run("Bell' Antonio")
check("typographic rescue fired", "typographic rescue (" in joined and "accepted rank 1" in joined, True)
check("resolves to Il bell'Antonio", "-> Il bell'Antonio (lang=" in joined, True)
check("no raw fallback", "raw fallback" in joined, False)
check("first-pass score recorded, below the threshold", score.get("fuzz_ratio_first_pass"), 85.7)
check("rescued score recorded", score.get("fuzz_ratio"), 88.9)
check("rescue recorded in match_scores", "apostrophes" in (score.get("rescue_normalizations") or []), True)
check("not counted as rejected", score.get("rejected"), False)
check("candidate id recorded", score.get("candidate_id"), "movieid_76157_it")

print("\n3. The French spelling, no space: the first pass decides, the rescue never runs")
joined, score = run("Bell'Antonio")
check("first pass accepts", "gate accepted rank 1" in joined, True)
check("rescue did not fire", "typographic rescue" in joined, False)
check("rescue field empty", score.get("rescue_normalizations"), [])

print("\n4. A curly apostrophe and a space, both")
joined, score = run("Bell’ Antonio")
check("resolves to Il bell'Antonio", "-> Il bell'Antonio (lang=" in joined, True)
check("no raw fallback", "raw fallback" in joined, False)

print("\n5. Rescue switched off in the configuration: the behaviour before -309, to the letter")
saved = entity.ENTITY_RESOLUTION_CONFIG
try:
    stripped = copy.deepcopy(saved)
    for entry in stripped:
        for strategy in entry.get("search_list") or []:
            strategy.pop("rescue_normalizations", None)
    entity.ENTITY_RESOLUTION_CONFIG = stripped
    joined, score = run("Bell' Antonio")
    check("refused as before", "rejected best embeddings candidate" in joined, True)
    check("raw fallback as before", "raw fallback" in joined, True)
finally:
    entity.ENTITY_RESOLUTION_CONFIG = saved

print("\n6. A stranger stays a stranger: normalising apostrophes does not loosen anything else")
joined, score = run("Zorglub l' Ancien", _Strangers())
check("rescue did not fire", "typographic rescue" in joined, False)
check("raw fallback", "raw fallback" in joined, True)

print("\n7. The rescue takes the BEST normalised score, not the first passing candidate")
joined, score = run("Prete a tout", _NearHomonyms())
check("resolves to Prête à tout (577), not Prêt à tout (204765)", score.get("candidate_id"), "movieid_577_fr")
check("its normalised score is 100", score.get("fuzz_ratio"), 100.0)

print("\n8. The configuration of 2026-10-04, type by type")
cfg = {e["placeholder_prefix"]: [st.get("rescue_normalizations") for st in e["search_list"]
                                 if st.get("search_mode") == "embeddings"]
       for e in entity.ENTITY_RESOLUTION_CONFIG}
full = ["apostrophes", "accents", "dashes", "punctuation"]
for t in ("Movie_title", "Serie_title", "Network_name", "Group_name", "Location_name", "Topic_name"):
    check(f"{t}: all four", cfg.get(t), [full])
check("Company_name: no punctuation (Warner Bros. China)", cfg.get("Company_name"),
      [["apostrophes", "accents", "dashes"]])
check("Collection_name: no dashes (Dracula 2000 - Saga)", cfg.get("Collection_name"),
      [["apostrophes", "accents", "punctuation"]])
for t in ("Award_name", "Death_name", "List_name", "Movement_name", "Nomination_name"):
    check(f"{t}: no rescue, nothing measured", cfg.get(t), [None])

print("\n9. A misspelt normaliser is refused at load, never at request time")
bad = copy.deepcopy(saved)
bad[0]["search_list"][0]["rescue_normalizations"] = ["apostrophe"]
try:
    entity._validate_entity_resolution_config(bad)
    refused = False
except ValueError:
    refused = True
check("unknown normaliser refused", refused, True)

print("")
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
