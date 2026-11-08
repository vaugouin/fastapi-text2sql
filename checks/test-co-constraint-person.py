"""Offline check of the co-constrained person rescue (FASTAPI-TEXT2SQL-371).

No API, no database. The films and their credits come from the measured result
``doc/sql/check-371-series-persons-20261108.txt`` (block 4, voie 1, 2026-11-08), plus a few
well-known co-stars added by hand as distractors, served by a fake cursor. Runs the five
bare-surname questions of evaluations 2674 to 2678 through ``entity.plan_co_constrained_rescue``
(the -369 title rescue first, then the -371 person rescue) and ``entity.apply_entity_resolutions``,
with the person resolved the way Blue 1.1.20 resolved it (an unrelated alias, or raw fallback).

    uv run --no-project --with-requirements requirements.txt checks/test-co-constraint-person.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import entity  # noqa: E402

FIXTURE = os.path.join(ROOT, "doc", "sql", "check-371-series-persons-20261108.txt")

# Films: id -> title forms. Credits: (id_movie, id_person, name, credit_type, popularity).
FILMS, CREDITS = {}, []
_block = 0
for line in open(FIXTURE, encoding="utf-8"):
    if line.startswith("| ID_MOVIE"):
        _block = 4
        continue
    if _block != 4 or not line.startswith("|"):
        continue
    idm, _year, t_en, t_fr, idp, name, ctype = [c.strip() for c in line.strip().strip("|").split("|")]
    FILMS[int(idm)] = {"MOVIE_TITLE": t_en, "MOVIE_TITLE_FR": t_fr, "ORIGINAL_TITLE": t_en}
    CREDITS.append((int(idm), int(idp), name, ctype, 10.0))
FILMS[11687]["ORIGINAL_TITLE"] = "Les Visiteurs"
# Distractors (ids invented, above the real range): co-stars, and same-surname persons on
# other films, so the pool is never a single name.
CREDITS += [
    (509, 9000001, "Julia Roberts", "cast", 50.0), (509, 9000002, "Rhys Ifans", "cast", 8.0),
    (103, 9000003, "Robert De Niro", "cast", 60.0), (103, 9000004, "Cybill Shepherd", "cast", 9.0),
    (98, 9000005, "Russell Crowe", "cast", 40.0), (98, 9000006, "Connie Nielsen", "cast", 7.0),
    (11687, 9000007, "Jean Reno", "cast", 30.0), (11687, 9000008, "Valérie Lemercier", "cast", 6.0),
    (680, 9000009, "John Travolta", "cast", 45.0), (680, 9000010, "Uma Thurman", "cast", 35.0),
    (9999999, 9000011, "Cary Grant", "cast", 70.0), (9999999, 9000012, "River Phoenix", "cast", 20.0),
]
# Wrong persons Blue resolved the bare words to (2026-11-08 baseline): credited elsewhere only.
WRONG = {"Giulio Antamoro": 9100001, "Christian Mazzalai": 9100002, "Jackson Wang": 9100003}


class FakeCursor:
    def __init__(self):
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT ID_PERSON, PERSON_NAME"):
            self.rows = [{"ID_PERSON": WRONG[n], "PERSON_NAME": n} for n in params if n in WRONG]
        elif "FROM `T_WC_T2S_PERSON_MOVIE` c JOIN `T_WC_T2S_MOVIE` t" in sql:
            self.rows = []  # the wrong persons' filmographies hold none of these films
        elif sql.startswith("SELECT `ID_MOVIE` AS _ID FROM `T_WC_T2S_MOVIE`"):
            title = params[0]
            self.rows = [{"_ID": i} for i, f in FILMS.items() if title in f.values()]
        elif "UNION ALL" in sql or "AS _W" in sql:
            ids = {int(x) for x in re.search(r"ID_MOVIE` IN \(([^)]*)\)", sql).group(1).split(",")}
            people = {}
            for idm, idp, name, ctype, pop in CREDITS:
                if idm in ids:
                    row = people.setdefault(idp, {"_ID": idp, "PERSON_NAME": name, "_POP": pop, "_CAST": 0})
                    row["_CAST"] = max(row["_CAST"], 1 if ctype == "cast" else 0)
            self.rows = list(people.values())
        else:
            raise AssertionError(f"unexpected SQL: {sql[:120]}")

    def fetchall(self):
        return self.rows


class FakeConnection:
    def cursor(self):
        return FakeCursor()


class Msg:
    def __init__(self, position, text):
        self.position, self.text = position, text


SQL = ("SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE FROM T_WC_T2S_MOVIE "
       "JOIN T_WC_T2S_PERSON_MOVIE ON T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE "
       "JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON "
       "WHERE T_WC_T2S_MOVIE.MOVIE_TITLE = '{{Movie_title1}}' AND T_WC_T2S_PERSON.PERSON_NAME = '{{Person_name1}}' "
       "AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'cast'")
MULTI = ["MOVIE_TITLE", "MOVIE_TITLE_FR", "ORIGINAL_TITLE"]

CASES = [
    # (title as resolved, bare name, how Blue resolved it (None = raw fallback), person ids expected)
    ("Notting Hill", "Grant", "Giulio Antamoro", {3291}),
    ("Coup de foudre à Notting Hill", "Grant", "Giulio Antamoro", {3291}),
    ("Taxi Driver", "Foster", None, {1038}),            # Jodie (cast), not Connie (crew)
    ("Gladiator", "Phoenix", "Christian Mazzalai", {73421}),
    ("The Visitors", "Clavier", None, {28781}),
    ("Les Visiteurs", "Clavier", None, {28781}),
    ("Pulp Fiction", "Jackson", "Jackson Wang", {2231}),
    ("Pulp Fiction", "Samuel Jackson", "Jackson Wang", {2231}),
]


def plan_for(title, name, resolved):
    t = entity._PlannedEntity("Movie_title1", "{{Movie_title1}}")
    t.resolve_with(entity._substitute_entity_row("{{Movie_title1}}", "MOVIE_TITLE", "MOVIE_TITLE", MULTI, title))
    p = entity._PlannedEntity("Person_name1", "{{Person_name1}}")
    if resolved is None:
        p.resolve_with(entity._substitute_plain("{{Person_name1}}", name, name), is_raw_fallback=True)
    else:
        p.resolve_with(entity._substitute_plain("{{Person_name1}}", resolved, resolved))
    return {"entities": [t, p], "match_scores": []}


failures = 0
for title, name, resolved, must in CASES:
    extraction = {"question": "Movie {{Movie_title1}} with {{Person_name1}}", "Movie_title1": title, "Person_name1": name}
    res = entity.plan_co_constrained_rescue(connection=FakeConnection(), entity_extraction=extraction, plan=plan_for(title, name, resolved))
    if res.get("outcome") != "planned" or res.get("kind") != "person":
        print(f"FAIL {title!r} + {name!r}: {res.get('kind')} {res.get('outcome')} ({res.get('detail')})")
        failures += 1
        continue
    ids = {w[0] for w in res["winners"]}
    sql = entity.apply_entity_resolutions(plan=res["plan"], sql_query=SQL, justification="", answer="",
                                          position_counter=0, text_message_cls=Msg, messages=[])["sql_query"]
    ok = ids == must and "{{" not in sql and "T_WC_T2S_PERSON.ID_PERSON IN (" in sql and "MOVIE_TITLE_FR = " in sql
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {title!r} + {name!r}: {res['detail'][:170]}")
    if not ok:
        print("     ", sql)

# The person rescue stays out of the way: a full name that is simply not on the film.
res = entity.plan_co_constrained_rescue(
    connection=FakeConnection(),
    entity_extraction={"question": "x", "Movie_title1": "Gladiator", "Person_name1": "Tom Hanks"},
    plan=plan_for("Gladiator", "Tom Hanks", None))
ok = res.get("outcome") == "no_match"
failures += 0 if ok else 1
print(("PASS" if ok else "FAIL"), "Gladiator + Tom Hanks ->", res.get("kind"), res.get("outcome"), "|", (res.get("detail") or "")[:150])
# Two persons: not applicable for the person rescue.
res = entity.plan_co_constrained_person_rescue(
    connection=FakeConnection(),
    entity_extraction={"question": "x", "Movie_title1": "Heat", "Person_name1": "Pacino", "Person_name2": "De Niro"},
    plan={"entities": []})
ok = res.get("outcome") == "not_applicable"
failures += 0 if ok else 1
print(("PASS" if ok else "FAIL"), "two persons ->", res.get("outcome"))
# Scores.
for sought, name, want in [("Phoenix", "Joaquin Phoenix", 100), ("Joaquin", "Joaquin Phoenix", 90), ("Grant", "Lee Grant", 100), ("Jodie Foster", "Jodie Foster", 100)]:
    got = entity.score_partial_person(sought, name)
    ok = got == want
    failures += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), f"score {sought!r} vs {name!r} = {got:.0f}")

print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
