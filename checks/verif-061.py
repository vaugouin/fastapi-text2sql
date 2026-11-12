#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline check of the user feedback route and its cache bypass, FASTAPI-TEXT2SQL-061.

    uv run --no-project --with pydantic --with tzdata checks/verif-061.py

Needs neither the API nor the database. Five parts:

1. `FeedbackRequest` (read on main.py, the block between the two "feedback models" markers,
   not imported: main.py opens MariaDB and ChromaDB at import): rating 1 / -1 only, comment
   stripped and capped at 2000, client enum, ui_language normalized, length caps.
2. `feedback.f_has_open_negative_feedback` against a fake cursor: the SQL (open statuses,
   negative rating, soft delete, language scoping), the parameters, the connection path, and
   the silent degradation on errors 1146 and 1142 (False, one console line per error code).
3. `feedback.f_record_feedback` against a fake connection: parameters in column order, Paris
   date formats, the returned id.
4. The request id and the bypass flag: ContextVars inherited by an awaited call, as the
   complex retry re-enters the endpoint, and isolated between two concurrent tasks.
5. Source checks on main.py: every Text2SQLResponse construction carries request_id, the two
   cache lookups read `intretrievefromcache`, the two write gates read `intcachebypassfeedback`,
   and the hash normalization feedback.py mirrors is still the one of the search route.
"""
import asyncio
import contextlib
import hashlib
import io
import os
import re
import sys
from typing import List, Optional

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator  # noqa: E402

import feedback  # noqa: E402

SOURCE = os.path.join(RACINE, "main.py")
src = io.open(SOURCE, encoding="utf-8").read()

succes = 0
total = 0


def verifie(libelle, obtenu, attendu):
    global succes, total
    total += 1
    conforme = obtenu == attendu
    succes += conforme
    print("%s  %-62s -> %r" % ("OK   " if conforme else "FAIL ", libelle, obtenu)
          + ("" if conforme else "  expected %r" % (attendu,)))


# --- 1. FeedbackRequest -----------------------------------------------------------------------
espace = {"BaseModel": BaseModel, "Field": Field, "field_validator": field_validator,
          "model_validator": model_validator, "Optional": Optional, "List": List,
          "feedback": feedback}
debut = src.index("DEFAULT_UI_LANGUAGE = ")
fin = src.index("def localize_row(")
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
debut = src.index("# --- feedback models (checks/verif-061.py executes this block) ---")
fin = src.index("# --- end feedback models ---")
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
FeedbackRequest = espace["FeedbackRequest"]
FeedbackResponse = espace["FeedbackResponse"]

BASE = {"rating": -1, "client": "voice-agent", "question": "Movies directed by Tony Scott"}


def valide(**surcharge):
    """Return the validated model, or the string 'refused' on a ValidationError."""
    dct = dict(BASE)
    dct.update(surcharge)
    for cle in [k for k, v in dct.items() if v is _ABSENT]:
        del dct[cle]
    try:
        return FeedbackRequest(**dct)
    except ValidationError:
        return "refused"


_ABSENT = object()

print("-- 1. FeedbackRequest")
verifie("rating -1 accepted", valide(rating=-1).rating, -1)
verifie("rating 1 accepted", valide(rating=1).rating, 1)
for rating in (0, 2, -2, 5, True, False, "1", "up", None):
    verifie("rating %r refused" % (rating,), valide(rating=rating), "refused")
verifie("rating missing refused", valide(rating=_ABSENT), "refused")
verifie("comment stripped", valide(comment="  wrong films \n").comment, "wrong films")
verifie("blank comment becomes None", valide(comment="   ").comment, None)
verifie("comment of 2000 chars accepted", len(valide(comment="x" * 2000).comment), 2000)
verifie("comment of 2001 chars refused", valide(comment="x" * 2001), "refused")
verifie("2000 chars plus spaces accepted (stripped first)",
        len(valide(comment="  " + "x" * 2000 + "  ").comment), 2000)
for client in ("t2s-front", "voice-agent", "other"):
    verifie("client %s accepted" % client, valide(client=client).client, client)
verifie("client upper case normalized", valide(client="Voice-Agent").client, "voice-agent")
for client in ("tmdb-front", "", None, "discord"):
    verifie("client %r refused" % (client,), valide(client=client), "refused")
verifie("client missing refused", valide(client=_ABSENT), "refused")
verifie("ui_language fr-FR -> fr", valide(ui_language="fr-FR").ui_language, "fr")
verifie("ui_language de -> en", valide(ui_language="de").ui_language, "en")
verifie("ui_language null -> en", valide(ui_language=None).ui_language, "en")
verifie("ui_language omitted -> en", valide().ui_language, "en")
verifie("question missing refused", valide(question=_ABSENT), "refused")
verifie("blank question refused", valide(question="   "), "refused")
verifie("question of 4000 chars accepted", len(valide(question="q" * 4000).question), 4000)
verifie("question of 4001 chars refused", valide(question="q" * 4001), "refused")
verifie("request_id of 64 chars accepted", len(valide(request_id="a" * 64).request_id), 64)
verifie("request_id of 65 chars refused", valide(request_id="a" * 65), "refused")
verifie("api_version of 21 chars refused", valide(api_version="1" * 21), "refused")
verifie("result_entity of 51 chars refused", valide(result_entity="m" * 51), "refused")
verifie("blank question_hashed becomes None", valide(question_hashed=" ").question_hashed, None)
verifie("sql_query kept", valide(sql_query="SELECT 1").sql_query, "SELECT 1")
verifie("response model", FeedbackResponse(id_feedback=3, cache_bypassed=True, api_version="1.1.20").model_dump(),
        {"id_feedback": 3, "status": "recorded", "cache_bypassed": True, "api_version": "1.1.20"})

# --- 2. The bypass check ----------------------------------------------------------------------
print("-- 2. f_has_open_negative_feedback")


class FauxCurseur:
    """A cursor that records the statement and answers a fixed row, or raises."""

    def __init__(self, ligne=None, erreur=None):
        self.ligne, self.erreur = ligne, erreur
        self.requetes, self.ferme = [], False

    def execute(self, requete, params=None):
        self.requetes.append((requete, list(params or [])))
        if self.erreur:
            raise self.erreur

    def fetchone(self):
        return self.ligne

    def close(self):
        self.ferme = True


class FausseConnexion:
    """A connection with no execute(): f_has_open_negative_feedback must open its own cursor."""

    def __init__(self, curseur):
        self.curseur = curseur

    def cursor(self):
        return self.curseur


class ErreurMariaDB(Exception):
    """Same shape as pymysql's errors: args[0] is the MariaDB error number."""


H1, H2 = "a" * 64, "b" * 64
c = FauxCurseur(ligne={"1": 1})
verifie("open thumbs down found -> True", feedback.f_has_open_negative_feedback(c, [H1, H2], "fr"), True)
requete, params = c.requetes[0]
sql = " ".join(requete.split())
verifie("SQL reads T_WC_T2S_FEEDBACK", "FROM T_WC_T2S_FEEDBACK" in sql, True)
verifie("SQL filters RATING < 0", "RATING < 0" in sql, True)
verifie("SQL filters the open statuses", "ANALYSIS_STATUS IN ('new', 'analysed')" in sql, True)
verifie("SQL skips soft-deleted rows", "(DELETED IS NULL OR DELETED = 0)" in sql, True)
verifie("SQL scopes the language like the cache", "(UI_LANGUAGE = %s OR UI_LANGUAGE IS NULL)" in sql, True)
verifie("SQL has LIMIT 1", sql.endswith("LIMIT 1"), True)
verifie("two hash placeholders", "QUESTION_HASHED IN (%s, %s)" in sql, True)
verifie("parameters: hashes then language", params, [H1, H2, "fr"])
verifie("no value interpolated in the SQL", H1 in requete, False)
verifie("open statuses constant matches the SQL",
        all("'%s'" % st in feedback.OPEN_NEGATIVE_FEEDBACK_QUERY for st in feedback.OPEN_ANALYSIS_STATUSES), True)
verifie("borrowed cursor not closed", c.ferme, False)

c = FauxCurseur(ligne=None)
verifie("no open thumbs down -> False", feedback.f_has_open_negative_feedback(c, [H1], "en"), False)
c = FauxCurseur(ligne=None)
feedback.f_has_open_negative_feedback(c, [H1, None, "", H1], None)
requete, params = c.requetes[0]
verifie("duplicates and blanks dropped", params, [H1])
verifie("no language -> no language clause", "UI_LANGUAGE" in requete, False)
c = FauxCurseur(ligne={"1": 1})
verifie("no hash -> False without a query", (feedback.f_has_open_negative_feedback(c, [None, ""], "en"), c.requetes),
        (False, []))
verifie("no connection -> False", feedback.f_has_open_negative_feedback(None, [H1], "en"), False)

c = FauxCurseur(ligne={"1": 1})
verifie("connection path -> True", feedback.f_has_open_negative_feedback(FausseConnexion(c), [H1], "en"), True)
verifie("owned cursor closed", c.ferme, True)

for code, texte in ((1146, "Table 'vaugouindb.T_WC_T2S_FEEDBACK' doesn't exist"),
                    (1142, "SELECT command denied to user 'moviematchro'")):
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        r1 = feedback.f_has_open_negative_feedback(FauxCurseur(erreur=ErreurMariaDB(code, texte)), [H1], "en")
        r2 = feedback.f_has_open_negative_feedback(FauxCurseur(erreur=ErreurMariaDB(code, texte)), [H1], "en")
    lignes = [ligne for ligne in sortie.getvalue().splitlines() if ligne.strip()]
    verifie("error %d degrades to False, twice" % code, (r1, r2), (False, False))
    verifie("error %d printed once" % code, len(lignes), 1)
    verifie("error %d message names 1146 and 1142" % code,
            "1146" in lignes[0] and "1142" in lignes[0], True)
c = FauxCurseur(erreur=ErreurMariaDB(1146, "x"))
sortie = io.StringIO()
with contextlib.redirect_stdout(sortie):
    r = feedback.f_has_open_negative_feedback(FausseConnexion(c), [H1], "en")
verifie("error on an owned cursor: False and cursor closed", (r, c.ferme), (False, True))

# --- 3. Recording ----------------------------------------------------------------------------
print("-- 3. f_record_feedback")


class CurseurInsertion(FauxCurseur):
    lastrowid = 17

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class ConnexionInsertion:
    def __init__(self):
        self.curseur = CurseurInsertion()
        self.commits = 0

    def cursor(self):
        return self.curseur

    def commit(self):
        self.commits += 1


cx = ConnexionInsertion()
dct = {"request_id": "r" * 32, "question": "Q", "question_hashed": H1, "ui_language": "fr",
       "api_version": "1.1.20", "client": "t2s-front", "rating": -1, "comment": "C",
       "sql_query": "SELECT 1", "result_entity": "movie"}
verifie("returns the new id", feedback.f_record_feedback(cx, dct), 17)
requete, params = cx.curseur.requetes[0]
verifie("first ten parameters in column order", params[:10],
        ["r" * 32, "Q", H1, "fr", "1.1.20", "t2s-front", -1, "C", "SELECT 1", "movie"])
verifie("DAT_CREAT is a date", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", params[10])), True)
verifie("TIM_CREATED is a naive datetime", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", params[11])), True)
verifie("TIM_UPDATED equals TIM_CREATED", params[12], params[11])
verifie("status starts at 'new'", "'new'" in requete, True)
verifie("placeholders match parameters", requete.count("%s"), len(params))
verifie("commit called", cx.commits, 1)

# --- 4. Request id and bypass flag -----------------------------------------------------------
print("-- 4. ContextVars")


async def passe_interne():
    """The complex retry re-enters the endpoint in the same context: it reads, never resets."""
    return feedback.current_request_id(), feedback.cache_bypass_active()


async def passe_externe(intbypass):
    strid = feedback.f_start_request()
    feedback.set_cache_bypass(intbypass)
    await asyncio.sleep(0)
    return strid, await passe_interne()


async def deux_requetes():
    return await asyncio.gather(passe_externe(True), passe_externe(False))


(id1, (id1_interne, b1)), (id2, (id2_interne, b2)) = asyncio.run(deux_requetes())
verifie("request id is 32 hex", bool(re.fullmatch(r"[0-9a-f]{32}", id1)), True)
verifie("inner pass inherits the id", id1_interne, id1)
verifie("inner pass inherits the bypass", b1, True)
verifie("two concurrent requests: distinct ids", id1 != id2, True)
verifie("two concurrent requests: bypass isolated", b2, False)
verifie("outside a request: empty id", feedback.current_request_id(), "")

async def _remise_a_zero():
    feedback.set_cache_bypass(True)
    feedback.f_start_request()
    return feedback.cache_bypass_active()


verifie("a new outer pass starts with no bypass", asyncio.run(_remise_a_zero()), False)

# --- 5. Source checks on main.py -------------------------------------------------------------
print("-- 5. main.py")
constructions = [m.start() for m in re.finditer(r"Text2SQLResponse\(\n", src)]


def appel_complet(pos):
    """The text of the call opened at pos, up to its matching closing parenthesis."""
    profondeur = 0
    for k in range(src.index("(", pos), len(src)):
        profondeur += {"(": 1, ")": -1}.get(src[k], 0)
        if profondeur == 0:
            return src[pos:k + 1]
    return src[pos:]


for pos in constructions:
    verifie("Text2SQLResponse at line %d carries request_id" % (src.count("\n", 0, pos) + 1),
            "request_id=feedback.current_request_id()" in appel_complet(pos), True)
verifie("four response construction sites", len(constructions), 4)
verifie("outer pass starts the request", "feedback.f_start_request()" in src, True)
verifie("exact lookup reads intretrievefromcache", "elif intretrievefromcache:" in src, True)
verifie("anonymized lookup reads intretrievefromcache",
        "if intretrievefromcache and not requires_complex_resolution and not dctidentityseed:" in src, True)
verifie("no cache tier left on request.retrieve_from_cache",
        [l.strip() for l in src.splitlines() if "if request.retrieve_from_cache" in l or "elif request.retrieve_from_cache" in l],
        ["if request.retrieve_from_cache and not intquestionaboutimage:"])
verifie("main write gate reads the bypass", ") and not intcachebypassfeedback  # FASTAPI-TEXT2SQL-061" in src, True)
verifie("retry write gate reads the bypass", "and not intcachebypassfeedback  # FASTAPI-TEXT2SQL-061\n" in src, True)
verifie("journal carries request_id", '"request_id": feedback.current_request_id(),  # FASTAPI-TEXT2SQL-061' in src, True)
verifie("route logs feedback_post", src.count('"feedback_post"'), 2)
for ligne in ("request.question = request.question.strip()",
              "request.question = request.question.replace('  ', ' ')",
              "request.question = request.question.replace('&#039;', \"'\").replace('’', \"'\")"):
    verifie("search normalization still: %s" % ligne[:40], ligne in src, True)
verifie("f_question_hash = sha256 of the normalized question",
        feedback.f_question_hash("  Tony Scott’s  films &#039;x&#039; "),
        hashlib.sha256("Tony Scott's films 'x'".encode("utf-8")).hexdigest())

print("\n%d / %d checks passed" % (succes, total))
sys.exit(0 if succes == total else 1)
