#!/usr/bin/env python3
"""Offline check of the map of places (phase 3 lot D, 2026-11-14).

No API, no database, no LLM. The gate (plan), the facts (build) with pins, areas, fiction and a
place with no coordinate, the default rule, apply_places on classified shapes (card grid, fact
card, flag list), and the database read through a fake cursor: parameters only, the statement
cap, and a base without the columns (error 1054) giving no map rather than an error.

    uv run --no-project python checks/test-result-places.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.stdout.reconfigure(encoding="utf-8")

import result_places as rp  # noqa: E402
import result_shape  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))


def place(pid, name, ptype, extra=None):
    row = {"ID_LOCATION": pid, "LOCATION_NAME": name, "LOCATION_TYPE": ptype, "LOCATION_SOURCE": "filming",
           "POSTER_PATH": None, "WIKIPEDIA_IMAGE_PATH": f"/img/{pid}.jpg", "MOVIE_COUNT": 3}
    row.update(extra or {})
    return row


# Lawrence of Arabia (evaluation 2910): Wadi Rum, Almeria, Seville, Jordan, and a fictional place;
# Giverny repeated as in a grouped answer (one row per ancestor).
ROWS = [place(5238, "Wadi Rum", "structure"), place(77, "Almería", "city"), place(78, "Seville", "city"),
        place(5238, "Wadi Rum", "structure"), place(9, "Jordan", "country"), place(900, "Aqaba (film)", "fiction"),
        place(901, "Unknown spot", None)]
COORDS = {
    5238: {"ID_LOCATION": 5238, "LOCATION_NAME": "Wadi Rum", "LOCATION_NAME_FR": "Wadi Rum",
           "LOCATION_TYPE": "structure", "LATITUDE": 29.5765, "LONGITUDE": 35.419928},
    77: {"ID_LOCATION": 77, "LOCATION_NAME": "Almería", "LOCATION_NAME_FR": "Almería", "LOCATION_TYPE": "city",
         "LATITUDE": 36.84, "LONGITUDE": -2.4675},
    78: {"ID_LOCATION": 78, "LOCATION_NAME": "Seville", "LOCATION_NAME_FR": "Séville", "LOCATION_TYPE": "city",
         "LATITUDE": 37.3886, "LONGITUDE": -5.9823},
    9: {"ID_LOCATION": 9, "LOCATION_NAME": "Jordan", "LOCATION_NAME_FR": "Jordanie", "LOCATION_TYPE": "country",
        "LATITUDE": 31.0, "LONGITUDE": 36.0},
    900: {"ID_LOCATION": 900, "LOCATION_NAME": "Aqaba (film)", "LOCATION_TYPE": "fiction",
          "LATITUDE": 29.5, "LONGITUDE": 35.0},
    901: {"ID_LOCATION": 901, "LOCATION_NAME": "Unknown spot", "LOCATION_TYPE": None,
          "LATITUDE": None, "LONGITUDE": None},
}

print("1. plan")
check("place rows, distinct ids in row order", rp.plan(ROWS, "location"), [5238, 77, 78, 9, 900, 901])
check("API row form {data: ...}", rp.plan([{"data": r} for r in ROWS[:2]], "location"), [5238, 77])
check("no ID_LOCATION: no plan", rp.plan([{"ID_MOVIE": 1, "MOVIE_TITLE": "X"}], "movie"), None)
check("films beside a place: no plan", rp.plan([{"ID_MOVIE": 1, "ID_LOCATION": 4}], "movie"), None)
check("no rows: no plan", rp.plan([], "location"), None)
check("bounded", len(rp.plan([place(i, f"P{i}", "city") for i in range(rp.MAX_IDS + 20)], "location")), rp.MAX_IDS)

print("2. build")
facts = rp.build(ROWS, COORDS, "en")
check("count", facts["count"], 6)
check("located", facts["located"], 4)
check("pins", [(p["id"], p["index"], p["label"]) for p in facts["pins"]],
      [(5238, 0, "Wadi Rum"), (77, 1, "Almería"), (78, 2, "Seville")])
check("areas", [(a["id"], a["type"]) for a in facts["areas"]], [(9, "country")])
check("unlocated", [(u["id"], u["reason"]) for u in facts["unlocated"]], [(900, "fiction"), (901, "no-coordinates")])
check("bounds", facts["bounds"], {"lat_min": 29.5765, "lat_max": 37.3886, "lon_min": -5.9823, "lon_max": 36.0})
check("French labels", [p["label"] for p in rp.build(ROWS, COORDS, "fr")["pins"]], ["Wadi Rum", "Almería", "Séville"])
check("out of range dropped", rp.build([place(1, "X", "city")], {1: {"LATITUDE": 95, "LONGITUDE": 10}}), None)
check("no coordinate at all: None", rp.build(ROWS, {}), None)

print("3. default")
check("asked", rp.is_default(facts, "map"), "asked")
check("three pins", rp.is_default(facts, ""), True)
one = rp.build([place(77, "Almería", "city"), place(9, "Jordan", "country")], COORDS)
check("one pin and an area: offered", rp.is_default(one, ""), False)
check("one pin, asked", rp.is_default(one, "map"), "asked")


def shape(rep, options):
    return {"representation": rep, "representation_options": list(options), "summary_facts": {"count": 3}}


print("4. apply_places")
s = result_shape.apply_places(shape("card-grid", ["card-grid", "table"]), facts, default=True)
check("card grid -> map", (s["representation"], s["representation_options"]), ("map", ["map", "card-grid", "table"]))
check("facts attached", s["summary_facts"]["places"]["located"], 4)
s = result_shape.apply_places(shape("card-grid", ["card-grid", "table"]), one, default=False)
check("offered before table", (s["representation"], s["representation_options"]), ("card-grid", ["card-grid", "map", "table"]))
s = result_shape.apply_places(shape("hierarchy", ["hierarchy", "card-grid", "table"]), facts, default=True)
check("hierarchy kept unless asked", s["representation"], "hierarchy")
s = result_shape.apply_places(shape("hierarchy", ["hierarchy", "card-grid", "table"]), facts, default="asked")
check("asked wins over hierarchy", s["representation_options"][:2], ["map", "hierarchy"])
s = result_shape.apply_places(shape("fact-card", ["fact-card", "card-grid", "table"]), facts, default="asked")
check("fact card stays first", s["representation_options"][:2], ["fact-card", "map"])
s = shape("flag-list", ["flag-list", "map", "table"])
s["summary_facts"]["countries"] = {"countries": []}
s = result_shape.apply_places(s, facts, default="asked")
check("countries keep lot B's map", ("places" in s["summary_facts"], s["representation"]), (False, "flag-list"))
check("no facts: unchanged", result_shape.apply_places(shape("card-grid", ["card-grid", "table"]), None)["representation"],
      "card-grid")


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.executed = rows or [], error, []

    def execute(self, sql, params):
        self.executed.append((sql, params))
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows


print("5. DbPlaces")
cur = FakeCursor(rows=list(COORDS.values()))
src = rp.DbPlaces(cur)
got = src.fetch([5238, 77])
sql, params = cur.executed[0]
check("capped", sql.startswith("SET STATEMENT max_statement_time=2 FOR SELECT"), True)
check("parameters only", ("5238" in sql, params), (False, [5238, 77]))
check("keyed by id", sorted(got)[:3], [9, 77, 78])
check("one statement", src.statements, 1)


class BadField(Exception):
    pass


src = rp.DbPlaces(FakeCursor(error=BadField(1054, "Unknown column 'LATITUDE' in 'SELECT'")))
check("missing columns: empty", (src.fetch([1]), src.missing_columns), ({}, True))
try:
    rp.DbPlaces(FakeCursor(error=BadField(1146, "no table"))).fetch([1])
    check("other error raised", False, True)
except BadField:
    check("other error raised", True, True)

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
