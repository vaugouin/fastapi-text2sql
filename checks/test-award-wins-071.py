#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline test of main._attach_award_wins (TMDB-MOVIE-PREPROCESS-071, the wins behind an award list).

    uv run --no-project python checks/test-award-wins-071.py

No API, no database. The function and its table map are read out of main.py by their names and
run alone against a fake cursor, so importing main (and its connections) is not needed. Pins:

- every row of an award list gets WIN_COUNT and AWARD_YEARS (distinct known years, ascending);
- WIN_COUNT counts rows for a person, and distinct known years plus the rows without a year
  for a movie or a series (one win stated twice in Wikidata is one win);
- on the person table only, `wins` holds one object per win with the work it was won for;
- the two directions: the awards of an entity (rows keyed by ID_AWARD) and the winners of an
  award (rows keyed by the entity id);
- one query for the page, none for an empty or absent list, and a row with no win row is not
  an error (WIN_COUNT 0).
"""
import ast
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RACINE, "main.py"), encoding="utf-8") as f:
    TREE = ast.parse(f.read())
WANTED = []
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_attach_award_wins":
        WANTED.append(node)
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_AWARD_WIN_TABLES" for t in node.targets):
        WANTED.append(node)
assert len(WANTED) == 2, "main.py no longer defines _AWARD_WIN_TABLES and _attach_award_wins at top level"
NS = {}
exec(compile(ast.Module(body=WANTED, type_ignores=[]), "main.py", "exec"), NS)
attach = NS["_attach_award_wins"]

FAILED = 0


def check(label, got, want):
    global FAILED
    ok = got == want
    FAILED += 0 if ok else 1
    if "--verbose" in sys.argv or not ok:
        print(f"{'PASS' if ok else 'FAIL'}  {label}: got {got!r}" + ("" if ok else f", want {want!r}"))


class Cur:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return [dict(r) for r in self.rows]


# 1. The awards of a person: Hepburn's four wins of one award, and an award with no year.
cur = Cur([
    {"_WIN_KEY": 269, "AWARD_YEAR": 1934, "ID_MOVIE_FOR": 31777, "MOVIE_TITLE": "Morning Glory", "MOVIE_TITLE_FR": None, "ID_SERIE_FOR": None, "SERIE_TITLE": None, "SERIE_TITLE_FR": None},
    {"_WIN_KEY": 269, "AWARD_YEAR": 1968, "ID_MOVIE_FOR": 1879, "MOVIE_TITLE": "Guess Who's Coming to Dinner", "MOVIE_TITLE_FR": "Devine qui vient diner ?", "ID_SERIE_FOR": None, "SERIE_TITLE": None, "SERIE_TITLE_FR": None},
    {"_WIN_KEY": 269, "AWARD_YEAR": 1968, "ID_MOVIE_FOR": None, "MOVIE_TITLE": None, "MOVIE_TITLE_FR": None, "ID_SERIE_FOR": None, "SERIE_TITLE": None, "SERIE_TITLE_FR": None},
    {"_WIN_KEY": 500, "AWARD_YEAR": None, "ID_MOVIE_FOR": None, "MOVIE_TITLE": None, "MOVIE_TITLE_FR": None, "ID_SERIE_FOR": None, "SERIE_TITLE": None, "SERIE_TITLE_FR": None},
])
rows = [{"ID_AWARD": 269, "AWARD_NAME": "Academy Award for Best Actress"}, {"ID_AWARD": 500, "AWARD_NAME": "Kennedy Center Honors"}, {"ID_AWARD": 777, "AWARD_NAME": "no win row"}]
attach(cur, rows, "ID_PERSON", entity_id=6598)
check("person awards: one query", len(cur.calls), 1)
sql, params = cur.calls[0]
check("person awards: table", "FROM T_WC_T2S_PERSON_AWARD w" in sql, True)
check("person awards: filter on the person, keys are awards", "WHERE w.ID_PERSON = %s AND w.ID_AWARD IN (%s, %s, %s)" in sql, True)
check("person awards: params", params, (6598, 269, 500, 777))
check("person awards: the work is joined", "LEFT JOIN T_WC_T2S_MOVIE m ON m.ID_MOVIE = w.ID_MOVIE_FOR" in sql and "LEFT JOIN T_WC_T2S_SERIE s ON s.ID_SERIE = w.ID_SERIE_FOR" in sql, True)
check("person awards: known years first, then the row id", "ORDER BY w.AWARD_YEAR IS NULL, w.AWARD_YEAR ASC, w.ID_ROW ASC" in sql, True)
check("WIN_COUNT counts rows", [r["WIN_COUNT"] for r in rows], [3, 1, 0])
check("AWARD_YEARS distinct ascending, empty when unknown", [r["AWARD_YEARS"] for r in rows], [[1934, 1968], [], []])
check("wins keep the work", [(w["AWARD_YEAR"], w["ID_MOVIE_FOR"], w["MOVIE_TITLE"]) for w in rows[0]["wins"]],
      [(1934, 31777, "Morning Glory"), (1968, 1879, "Guess Who's Coming to Dinner"), (1968, None, None)])
check("the grouping key does not leak", any("_WIN_KEY" in w for r in rows for w in r["wins"]), False)
check("a row with no win row", rows[2]["wins"], [])
check("the list columns are kept", rows[0]["AWARD_NAME"], "Academy Award for Best Actress")

# 2. The movies of an award: keyed by the movie, no work columns, no `wins`.
cur = Cur([{"_WIN_KEY": 21575, "AWARD_YEAR": 2010}, {"_WIN_KEY": 9, "AWARD_YEAR": 1990}, {"_WIN_KEY": 9, "AWARD_YEAR": 1985}])
rows = [{"ID_MOVIE": 21575}, {"ID_MOVIE": 9}]
attach(cur, rows, "ID_MOVIE", award_id=25677)
sql, params = cur.calls[0]
check("award movies: filter on the award, keys are movies", "FROM T_WC_T2S_MOVIE_AWARD w WHERE w.ID_AWARD = %s AND w.ID_MOVIE IN (%s, %s)" in sql, True)
check("award movies: params", params, (25677, 21575, 9))
check("award movies: no work join", "ID_MOVIE_FOR" in sql or "LEFT JOIN" in sql, False)
check("award movies: years", [r["AWARD_YEARS"] for r in rows], [[2010], [1985, 1990]])
check("award movies: no wins list outside persons", any("wins" in r for r in rows), False)
check("award movies: one win per year", [r["WIN_COUNT"] for r in rows], [1, 2])

# 2b. A series whose wins are stated twice for the same year, and a win without a year.
cur = Cur([{"_WIN_KEY": 14174, "AWARD_YEAR": 2001}, {"_WIN_KEY": 14174, "AWARD_YEAR": 2001}, {"_WIN_KEY": 14174, "AWARD_YEAR": 2002},
           {"_WIN_KEY": 14174, "AWARD_YEAR": 2002}, {"_WIN_KEY": 5, "AWARD_YEAR": 1999}, {"_WIN_KEY": 5, "AWARD_YEAR": None}, {"_WIN_KEY": 5, "AWARD_YEAR": None}])
rows = [{"ID_AWARD": 14174}, {"ID_AWARD": 5}]
attach(cur, rows, "ID_SERIE", entity_id=688)
check("series awards: a year stated twice is one win", rows[0]["WIN_COUNT"], 2)
check("series awards: rows without a year each count", rows[1]["WIN_COUNT"], 3)

# 3. The series table, and the persons of an award.
cur = Cur([])
attach(cur, [{"ID_AWARD": 1}], "ID_SERIE", entity_id=688)
check("series awards: table and filter", "FROM T_WC_T2S_SERIE_AWARD w WHERE w.ID_SERIE = %s AND w.ID_AWARD IN (%s)" in cur.calls[0][0], True)
cur = Cur([{"_WIN_KEY": 6598, "AWARD_YEAR": 1982, "ID_MOVIE_FOR": 11816, "MOVIE_TITLE": "On Golden Pond", "MOVIE_TITLE_FR": None, "ID_SERIE_FOR": None, "SERIE_TITLE": None, "SERIE_TITLE_FR": None}])
rows = [{"ID_PERSON": 6598}]
attach(cur, rows, "ID_PERSON", award_id=269)
check("award persons: filter on the award, keys are persons", "WHERE w.ID_AWARD = %s AND w.ID_PERSON IN (%s)" in cur.calls[0][0], True)
check("award persons: wins", rows[0]["wins"][0]["ID_MOVIE_FOR"], 11816)

# 4. Nothing to do: no query.
for label, value in (("empty list", []), ("absent list (another collection was targeted)", None)):
    cur = Cur([])
    attach(cur, value, "ID_MOVIE", entity_id=153)
    check(f"{label}: no query", cur.calls, [])

print(f"\n{'OK' if not FAILED else f'{FAILED} FAILED'}")
sys.exit(1 if FAILED else 0)
