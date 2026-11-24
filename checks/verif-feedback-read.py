#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline check of the read-only feedback routes, GET /feedback and GET /feedback/{id}.

    uv run --no-project --with pydantic --with tzdata checks/verif-feedback-read.py

Needs neither the API nor the database. Four parts:

1. `feedback.f_parse_statuses`: default "new", "all", lists, duplicates, unknown values refused.
2. `feedback.f_build_list_query`: soft delete always excluded, every filter as a bound
   parameter (never pasted into the SQL), oldest first, limit capped, one extra row fetched.
3. `feedback.f_list_feedback` and `f_get_feedback` against a fake connection: pagination
   (`has_more`, `next_after_id`), lowercase keys, dates as "YYYY-MM-DD HH:MM:SS".
4. Source checks on main.py: both GET routes require the API key and the read code holds no
   INSERT, UPDATE or DELETE, so the routes stay read-only.
"""
import datetime
import io
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import feedback  # noqa: E402

succes = 0
total = 0


def verifie(libelle, obtenu, attendu):
    global succes, total
    total += 1
    conforme = obtenu == attendu
    succes += conforme
    print("%s  %-62s -> %r" % ("OK   " if conforme else "FAIL ", libelle, obtenu)
          + ("" if conforme else "  expected %r" % (attendu,)))


def refuse(libelle, fonction, *args):
    global succes, total
    total += 1
    try:
        fonction(*args)
        print("FAIL  %-62s -> accepted, expected ValueError" % libelle)
    except ValueError:
        succes += 1
        print("OK    %-62s -> ValueError" % libelle)


# --- 1. statuses --------------------------------------------------------------------------------
verifie("status None gives new", feedback.f_parse_statuses(None), ["new"])
verifie("status '' gives new", feedback.f_parse_statuses(""), ["new"])
verifie("status all gives the five", feedback.f_parse_statuses("all"), list(feedback.ANALYSIS_STATUSES))
verifie("status list, spaces and case", feedback.f_parse_statuses(" New, analysed ,"), ["new", "analysed"])
verifie("status duplicates kept once", feedback.f_parse_statuses("fixed,fixed"), ["fixed"])
refuse("status typo refused", feedback.f_parse_statuses, "nwe")
refuse("status injection refused", feedback.f_parse_statuses, "new') OR 1=1 --")

# --- 2. query -----------------------------------------------------------------------------------
q, p, n = feedback.f_build_list_query(["new"])
verifie("default: soft delete excluded", "(DELETED IS NULL OR DELETED = 0)" in q, True)
verifie("default: oldest first", q.rstrip().endswith("ORDER BY ID_FEEDBACK ASC LIMIT %s"), True)
verifie("default: params", p, ["new", feedback.LIST_DEFAULT_LIMIT + 1])
verifie("default: no write keyword", re.search(r"\b(INSERT|UPDATE|DELETE)\b", q.replace("DELETED", "")), None)
q, p, n = feedback.f_build_list_query(["new", "analysed"], -1, 12, "2026-11-20", 500)
verifie("filters: placeholders", q.count("%s"), 6)
verifie("filters: params in order", p, ["new", "analysed", -1, 12, "2026-11-20", feedback.LIST_MAX_LIMIT + 1])
verifie("filters: limit capped", n, feedback.LIST_MAX_LIMIT)
verifie("filters: since not pasted in SQL", "2026-11-20" in q, False)


# --- 3. fake connection -------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur


def ligne(lngid):
    return {"ID_FEEDBACK": lngid, "RATING": -1, "ANALYSIS_STATUS": "new", "COMMENT": "not his film",
            "TIM_CREATED": datetime.datetime(2026, 11, 24, 10, 35, 21), "TIM_ANALYSED": None}


page = feedback.f_list_feedback(FakeConnection([ligne(i) for i in (3, 5, 8)]), ["new"], lnglimit=2)
verifie("page: two items of three rows", [d["id_feedback"] for d in page["items"]], [3, 5])
verifie("page: has_more", page["has_more"], True)
verifie("page: next_after_id is the last returned", page["next_after_id"], 5)
verifie("page: date as text", page["items"][0]["tim_created"], "2026-11-24 10:35:21")
verifie("page: null date stays null", page["items"][0]["tim_analysed"], None)
verifie("page: lowercase keys", sorted(page["items"][0]), ["analysis_status", "comment", "id_feedback",
                                                          "rating", "tim_analysed", "tim_created"])
page = feedback.f_list_feedback(FakeConnection([ligne(3)]), ["new"], lnglimit=2)
verifie("last page: no more", (page["has_more"], page["next_after_id"]), (False, None))
page = feedback.f_list_feedback(FakeConnection([]), ["new"])
verifie("empty: no items", (page["items"], page["has_more"]), ([], False))
connexion = FakeConnection([ligne(7)])
verifie("get: found", feedback.f_get_feedback(connexion, "7")["id_feedback"], 7)
verifie("get: id bound as int", connexion.cur.executed[0][1], (7,))
verifie("get: soft delete excluded", "DELETED = 0" in connexion.cur.executed[0][0], True)
verifie("get: missing gives None", feedback.f_get_feedback(FakeConnection([]), 7), None)

# --- 4. source checks on main.py ----------------------------------------------------------------
src = io.open(os.path.join(RACINE, "main.py"), encoding="utf-8").read()
debut = src.index("class FeedbackItem(BaseModel):")
fin = src.index("# Entity detail endpoints", debut)
bloc = src[debut:fin]
verifie("GET /feedback route declared", '@app.get("/feedback",' in bloc, True)
verifie("GET /feedback/{id} route declared", '@app.get("/feedback/{id_feedback}",' in bloc, True)
verifie("both routes require the API key", bloc.count("Depends(get_api_key)"), 2)
verifie("read block calls no write helper", "f_record_feedback" in bloc, False)
verifie("read block holds no write SQL", re.search(r"\b(INSERT|UPDATE|DELETE)\s", bloc), None)
lu = io.open(os.path.join(RACINE, "feedback.py"), encoding="utf-8").read()
lecture = lu[lu.index("# --- Reading the ratings back"):]
verifie("feedback.py read part holds no write SQL",
        re.search(r"\b(INSERT|UPDATE)\b|\bDELETE\s+FROM\b", lecture), None)

print("\n%d / %d checks passed" % (succes, total))
sys.exit(0 if succes == total else 1)
