#!/usr/bin/env python3
"""Offline check of the lineage walk behind `chain` (phase 3 lot E, 2026-11-12).

No API, no database, no LLM. Three parts:
1. a small fake graph with a fork (one source, three works made from it) and a cycle (two films
   citing each other, as Dog Day Afternoon and The Dog do in the base): the walk's direction,
   generations, cycle guard, and the three bounds (depth, works, time);
2. the real graph around the anchors of evaluations 2930 to 2939 and four probes, as the live
   base returned it on 2026-11-12 (checks/data/p3e-lineage-graph-20261112.json, from
   text2sql-eval/check-phase3-lot-e-lineage-20261112.txt, voie 1);
3. the gate (plan), the default rule, apply_chain on a classified shape, the SQL builders
   (parameters only, never an id in the text), and the trailing-LIMIT paging of sql_shapes.

    uv run --no-project python checks/test-result-chain.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import result_chain as rc  # noqa: E402
import result_shape  # noqa: E402
import sql_shapes  # noqa: E402
from lineage_fake import FakeLineage  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))


def link(child_type, child_id, sw, sw_type="screen", movie=None, serie=None, name="", year=None):
    return {"CHILD_TYPE": child_type, "CHILD_ID": child_id, "DISPLAY_ORDER": None, "ID_SOURCE_WORK": sw,
            "SOURCE_WORK_TYPE": sw_type, "SOURCE_WORK_FORM": None, "ID_MOVIE": movie, "ID_SERIE": serie,
            "SOURCE_WORK_NAME": name, "SOURCE_WORK_NAME_FR": name, "SOURCE_WORK_YEAR": year,
            "POSTER_PATH": None, "WIKIPEDIA_IMAGE_PATH": None}


def titles(chain):
    return [(n["title"], n["layer"]) for n in chain["nodes"]]


# 1. The fake graph. A novel (work 900, 1900) -> film 1 (1930); film 1 -> films 2 (1950), 3
# (1960) and the series 7 (1990); film 3 -> film 4 (1980); films 5 (1970) and 6 (1975) cite each
# other (a cycle) and 6 cites film 4.
MOVIES = [{"ID_MOVIE": i, "MOVIE_TITLE": f"Film {i}", "MOVIE_TITLE_FR": f"Film {i} FR" if i == 1 else None,
           "RELEASE_YEAR": y, "POSTER_PATH": f"/p{i}.jpg"} for i, y in
          ((1, 1930), (2, 1950), (3, 1960), (4, 1980), (5, 1970), (6, 1975))]
SERIES = [{"ID_SERIE": 7, "SERIE_TITLE": "Series 7", "SERIE_TITLE_FR": None, "FIRST_AIR_YEAR": 1990, "POSTER_PATH": None}]
LINKS = [
    link("movie", 1, 900, "literary", name="The Novel", year=1900),
    link("movie", 2, 901, movie=1), link("movie", 3, 901, movie=1), link("serie", 7, 901, movie=1),
    link("movie", 4, 903, movie=3),
    link("movie", 5, 906, movie=6), link("movie", 6, 905, movie=5), link("movie", 6, 904, movie=4),
    link("movie", 9, 908, movie=8),
]
MOVIES += [{"ID_MOVIE": 8, "MOVIE_TITLE": "Film 8", "MOVIE_TITLE_FR": None, "RELEASE_YEAR": 2000, "POSTER_PATH": None},
           {"ID_MOVIE": 9, "MOVIE_TITLE": "Film 9", "MOVIE_TITLE_FR": None, "RELEASE_YEAR": 2010, "POSTER_PATH": None}]
fake = FakeLineage(LINKS, MOVIES, SERIES)

c = rc.walk(fake, [("movie", 4)], "up")
check("up from film 4: the novel, then films 1, 3, 4 by generation", titles(c),
      [("The Novel", 0), ("Film 1", 1), ("Film 3", 2), ("Film 4", 3)])
check("up: kinds (adaptation from the novel, remakes after)", [(e["from"], e["to"], e["kind"]) for e in c["edges"]],
      [(0, 1, "adaptation"), (1, 2, "remake"), (2, 3, "remake")])
check("up: anchor, direction, generations, depth", (c["anchor"], c["direction"], c["generations"], c["depth"]),
      ([3], "up", 4, {"up": 3, "down": 0}))
check("up: no sibling of the lineage (films 2 and 7 left out)", c["count"], 4)

c = rc.walk(fake, [("movie", 1)], "down")
check("down from film 1: a fork of three, then film 4 and its cycle", titles(c),
      [("Film 1", 0), ("Film 2", 1), ("Film 3", 1), ("Series 7", 1), ("Film 4", 2), ("Film 6", 3), ("Film 5", 4)])
check("down: the series from a film is an adaptation", [e["kind"] for e in c["edges"] if c["nodes"][e["to"]]["type"] == "serie"],
      ["adaptation"])
check("down: one cycle edge, the one pointing back in time", [(c["nodes"][e["from"]]["title"], c["nodes"][e["to"]]["title"])
                                                              for e in c["edges"] if e["cycle"]], [("Film 5", "Film 6")])
check("down: cycles counted, not truncated", (c["cycles"], c["truncated"]), (1, False))
check("down: earliest and latest by year", (c["nodes"][c["earliest"]]["title"], c["nodes"][c["latest"]]["title"]),
      ("Film 1", "Series 7"))

c = rc.walk(fake, [("movie", 3)], "both")
check("both from film 3: sources up, works down, no siblings", titles(c),
      [("The Novel", 0), ("Film 1", 1), ("Film 3", 2), ("Film 4", 3), ("Film 6", 4), ("Film 5", 5)])

c = rc.walk(fake, [("source_work", 900)], "down", max_depth=1)
check("depth bound 1 from the novel: cut, and the probe says the lineage goes on", (c["count"], c["truncated_by"]), (2, "depth"))
c = rc.walk(fake, [("movie", 4)], "up", max_depth=3)
check("depth bound 3 up from film 4: the lineage ends there, not truncated", (c["count"], c["truncated"]), (4, False))
c = rc.walk(fake, [("movie", 1)], "down", max_nodes=3)
check("works bound 3: three works, truncated by nodes", (c["count"], c["truncated_by"]), (3, "nodes"))
ticks = iter([0.0, 0.0, 10.0, 10.0, 10.0, 10.0])
c = rc.walk(fake, [("movie", 1)], "down", budget_seconds=1.0, clock=lambda: next(ticks, 10.0))
check("time budget: the walk stops after the first generation", (c["count"], c["truncated_by"]), (4, "time"))
c = rc.walk(fake, [("movie", 1)], "down", language="fr")
check("French titles where the base has one", c["nodes"][0]["title"], "Film 1 FR")
check("a lone work with no link: no chain", rc.walk(fake, [("movie", 2)], "down"), None)

# 2. The real graph (live base, 2026-11-12).
real = FakeLineage.from_json(os.path.join(HERE, "data", "p3e-lineage-graph-20261112.json"))


def walk_real(anchors, direction, lang="en"):
    return rc.walk(real, anchors, direction, language=lang)


def years(chain):
    return [(n["title"], n["year"]) for n in chain["nodes"]]


c = walk_real([("movie", 332562)], "up")
check("2930 A Star Is Born 2018 up: 1937 once, 1954 and 1976, then 2018", years(c),
      [("A Star Is Born", 1937), ("A Star Is Born", 1954), ("A Star Is Born", 1976), ("A Star Is Born", 2018)])
check("2930 layers: 1937 alone, 1954 and 1976 side by side, 2018", c["layers"], [[0], [1, 2], [3]])
check("2930 five remake links (a DAG, not a path)", len(c["edges"]), 5)
c = walk_real([("movie", 391)], "up")
check("2931 A Fistful of Dollars up: Red Harvest, Yojimbo", years(c),
      [("Red Harvest", 1927), ("Yojimbo", 1961), ("A Fistful of Dollars", 1964)])
check("2931 kinds", sorted((e["from"], e["to"], e["kind"]) for e in c["edges"]),
      [(0, 1, "adaptation"), (0, 2, "adaptation"), (1, 2, "remake")])
c = walk_real([("movie", 111)], "up")
check("2932 Scarface 1983 up: the novel, 1932, 1983", years(c), [("Scarface", 1930), ("Scarface", 1932), ("Scarface", 1983)])
c = walk_real([("movie", 1422)], "both")
check("2933 The Departed both ways: Infernal Affairs upstream (the 1.1.20 defect walked down only)",
      [n["title"] for n in c["nodes"] if n["layer"] == 0], ["Infernal Affairs"])
c = walk_real([("movie", 333484)], "up")
check("2934 Magnificent Seven 2016 up", years(c),
      [("Seven Samurai", 1954), ("The Magnificent Seven", 1960), ("The Magnificent Seven", 2016)])
c = walk_real([("movie", 426063)], "up")
check("2935 Nosferatu 2024 up: Dracula once", years(c), [("Dracula", 1897), ("Nosferatu", 1922), ("Nosferatu", 2024)])
c = walk_real([("movie", 9333)], "up")
check("2936 Last Man Standing up: Yojimbo kept (the 1.1.20 defect dropped it)", years(c),
      [("Red Harvest", 1927), ("Yojimbo", 1961), ("Last Man Standing", 1996)])
c = walk_real([("source_work", 6848)], "down")
check("2937 Red Harvest down: nine works over four generations", (c["count"], c["generations"], c["truncated"]), (9, 4, False))
c = walk_real([("movie", 346)], "down")
check("2938 Seven Samurai down: both Magnificent Sevens, 2016 under 1960", [(n["title"], n["year"], n["layer"]) for n in c["nodes"]
                                                                           if n["title"] == "The Magnificent Seven" and n["type"] == "movie"],
      [("The Magnificent Seven", 1960, 1), ("The Magnificent Seven", 2016, 2)])
c = walk_real([("movie", 966)], "both")
check("2939 Magnificent Seven 1960 both ways", [n["title"] for n in c["nodes"]][:2] + [c["nodes"][c["latest"]]["year"]],
      ["Seven Samurai", "The Magnificent Seven", 2016])
c = walk_real([("movie", 391)], "up", "fr")
check("French titles from the base", [n["title"] for n in c["nodes"]], ["La Moisson rouge", "Le Garde du corps", "Pour une poignée de dollars"])
for name, anchors in (("Yojimbo", [("movie", 11878)]), ("A Star Is Born 1937", [("movie", 22692)]),
                      ("Scarface 1932", [("movie", 877)]), ("Nosferatu 1922", [("movie", 653)])):
    c = walk_real(anchors, "both")
    check(f"probe {name} both ways: a chain within the bounds", bool(c) and not c["truncated"] and len(c["edges"]) >= 2, True)

# 3. The gate, the default, the shape.
ems = [{"placeholder": "{{Movie_title1}}", "table": "T_WC_T2S_MOVIE", "candidate_id": "9333_MOVIE_TITLE", "rejected": False}]
rows = [{"index": 0, "data": {"ID_SOURCE_WORK": 6848, "SOURCE_WORK_NAME": "Red Harvest", "ID_MOVIE": None, "ID_SERIE": None}}]
p = rc.plan("Trace Last Man Standing (1996) back to the novel it ultimately comes from", {"task": "list"}, ems, rows, "source_work")
check("plan 2936: up from the named film, not from the rows", p,
      {"anchors": [("movie", 9333)], "direction": "up", "strength": "strong", "rows_must_join": False})
check("plan: a chroma id for a named source work", rc.plan(
    "How did Red Harvest reach the screen, remakes included?", {"task": "list"},
    [{"table": "T_WC_T2S_SOURCE_WORK", "candidate_id": "t2ssourceworkid_6848_en"}], rows, "movie_serie")["anchors"],
      [("source_work", 6848)])
check("plan: a rejected match is no anchor, rows of a strong question are",
      rc.plan("Trace the chain of remakes behind it", None, [dict(ems[0], rejected=True)], rows, "source_work")["anchors"],
      [("source_work", 6848)])
check("plan: weak words need a named work", rc.plan("Movies based on Stephen King novels", {"task": "list"},
      [{"table": "T_WC_T2S_PERSON", "candidate_id": "1_PERSON_NAME"}], rows, "movie"), None)
check("plan: no lineage words, no relate: nothing", rc.plan("Which films did Kurosawa direct?", {"task": "list"}, ems, rows, "movie"), None)
check("plan: relate on a named work walks both ways", rc.plan("How are these two films related?", {"task": "relate"}, ems, rows, "movie")["direction"],
      "both")
check("plan: person rows, no walk", rc.plan("Who directed the remakes of Scarface (1932)?", {"task": "list"}, ems, rows, "person"), None)
check("plan: no rows, no walk", rc.plan("Trace Last Man Standing back to its source", None, ems, [], "movie"), None)

asib = walk_real([("movie", 332562)], "up")
check("default for strong words", rc.is_default({"strength": "strong"}, asib), True)
check("default for weak words with three generations (2931)", rc.is_default({"strength": "weak"}, walk_real([("movie", 391)], "up")), True)
fan = rc.walk(FakeLineage(LINKS, MOVIES, SERIES), [("movie", 1)], "down", max_depth=1)
check("weak words over a fan one generation deep: offered only", rc.is_default({"strength": "weak"}, fan), False)

disjoint = rc.walk(fake, [("movie", 2), ("movie", 9)], "both")
check("rows that are not one lineage do not join", rc.joins_rows(disjoint, [("movie", 2), ("movie", 9)]), False)
check("rows of one lineage join", rc.joins_rows(rc.walk(fake, [("movie", 2), ("movie", 4)], "both"),
                                                [("movie", 2), ("movie", 4)]), True)
check("build drops a chain of one link", rc.build(FakeLineage(LINKS[:1], MOVIES), {"anchors": [("movie", 1)], "direction": "up",
                                                                                 "strength": "strong"}), None)

sql = ("SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE, T_WC_T2S_MOVIE.DAT_RELEASE, T_WC_T2S_MOVIE.POSTER_PATH "
       "FROM T_WC_T2S_MOVIE ORDER BY T_WC_T2S_MOVIE.DAT_RELEASE")
shape_rows = [{"index": i, "data": {"ID_MOVIE": m, "MOVIE_TITLE": "A Star Is Born", "DAT_RELEASE": d, "POSTER_PATH": None}}
              for i, (m, d) in enumerate(((22692, "1937-04-20"), (3111, "1954-10-01"), (19610, "1976-12-17")))]
shape = result_shape.classify_result(sql, shape_rows, "movie", intent={"task": "sequence", "focus": [], "requested_view": "chain", "source": "rules"})
check("without a chain the requested view changes nothing (the census case)", shape["representation"] != "chain"
      and "chain" not in shape["representation_options"], True)
before = list(shape["representation_options"])
result_shape.apply_chain(shape, asib, default=False)
check("offered: before table, default kept", (shape["representation"], shape["representation_options"]),
      (before[0], before[:-1] + ["chain", "table"]))
result_shape.apply_chain(shape, asib, default=True)
check("default: first", shape["representation_options"][0], "chain")
check("the chain travels in summary_facts", shape["summary_facts"]["chain"]["count"], 4)
verdict = {"representation": "verdict", "representation_options": ["verdict", "card-grid", "table"], "summary_facts": {"count": 1}}
result_shape.apply_chain(verdict, asib, default=True)
check("a verdict stays first, the chain right after", verdict["representation_options"], ["verdict", "chain", "card-grid", "table"])
none = {"representation": "card-grid", "representation_options": ["card-grid", "table"], "summary_facts": {"count": 2}}
result_shape.apply_chain(none, None, default=True)
check("no chain: shape untouched", none["representation_options"], ["card-grid", "table"])

text, params = rc.parents_sql([1, 2], [3])
check("parents SQL: ids bound, never in the text", ("1" not in text.replace("T_WC_T2S", ""), params), (True, [1, 2, 3]))
text, params = rc.children_sql([1], [], [9])
check("children SQL: both junctions, ids bound twice", (text.count("UNION ALL"), params), (1, [1, 9, 1, 9]))
check("children SQL with nothing to look for", rc.children_sql([], [], []), ("", []))
check("read-only statements", all(s.lstrip().upper().startswith("SELECT") for s in (
    rc.parents_sql([1], [])[0], rc.children_sql([1], [], [])[0], rc.movies_sql([1])[0], rc.series_sql([1])[0], rc.works_sql([1])[0])), True)


class Cursor:
    def __init__(self):
        self.sent = []

    def execute(self, sql, params):
        self.sent.append((sql, params))

    def fetchall(self):
        return []


cur = Cursor()
rc.DbLineage(cur).parents([5], [])
check("each statement capped server side", cur.sent[0][0].startswith("SET STATEMENT max_statement_time=2 FOR SELECT"), True)

# Paging (sql_shapes.split_trailing_limit): only the statement's own trailing LIMIT.
cte = ("WITH RECURSIVE c AS (SELECT ID_MOVIE FROM T LIMIT 5 UNION ALL SELECT ID_MOVIE FROM c) "
       "SELECT * FROM c ORDER BY 1 LIMIT 20 OFFSET 40")
check("paging: trailing LIMIT n OFFSET m read, the CTE's LIMIT kept", sql_shapes.split_trailing_limit(cte),
      ("WITH RECURSIVE c AS (SELECT ID_MOVIE FROM T LIMIT 5 UNION ALL SELECT ID_MOVIE FROM c) SELECT * FROM c ORDER BY 1", 20, 40))
check("paging: MariaDB LIMIT offset, count", sql_shapes.split_trailing_limit("SELECT 1 FROM T LIMIT 10, 5;"),
      ("SELECT 1 FROM T", 5, 10))
check("paging: LIMIT alone", sql_shapes.split_trailing_limit("SELECT 1 FROM T limit 7"), ("SELECT 1 FROM T", 7, 0))
check("paging: an inner LIMIT only is not the page", sql_shapes.split_trailing_limit(
    "SELECT * FROM (SELECT ID FROM T ORDER BY X LIMIT 3) d ORDER BY ID"),
      ("SELECT * FROM (SELECT ID FROM T ORDER BY X LIMIT 3) d ORDER BY ID", None, None))
check("paging: a parenthesised UNION branch keeps its LIMIT", sql_shapes.split_trailing_limit(
    "(SELECT 1 FROM A LIMIT 2) UNION (SELECT 2 FROM B LIMIT 2)")[1], None)

print(f"\n{'FAILED' if failures else 'all ok'}: {failures} failure(s)")
sys.exit(1 if failures else 0)
