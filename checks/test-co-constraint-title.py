"""Offline check of the co-constrained title rescue (FASTAPI-TEXT2SQL-369).

No API, no database: the persons and their film credits come from the measured result
``doc/sql/check-369-partial-title-person-20261108.txt`` (voie 1, 2026-11-08), served by a fake
cursor. Runs the five questions of evaluations 2664 to 2668 through
``entity.plan_co_constrained_title_rescue`` and ``entity.apply_entity_resolutions`` on the
anonymized SQL of the 2026-11-08 trace, and checks the winners and the rewritten predicate.

    uv run --no-project --with-requirements requirements.txt checks/test-co-constraint-title.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import entity  # noqa: E402

FIXTURE = os.path.join(ROOT, "doc", "sql", "check-369-partial-title-person-20261108.txt")


def load_fixture():
    persons, credits = {}, {}
    block = 0
    for line in open(FIXTURE, encoding="utf-8"):
        if line.startswith("| ID_PERSON"):
            block = 1
            continue
        if line.startswith("| PERSON_NAME"):
            block = 2
            continue
        if line.startswith("| ID_MOVIE"):
            block = 3
            continue
        if not line.startswith("|") or block == 0:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if block == 1:
            persons[cells[1]] = int(cells[0])
        elif block == 2:
            name, idm, year, votes, _ctype, t_en, t_fr, t_orig = cells[:8]
            credits.setdefault(persons[name], {})[int(idm)] = {
                "_ID": int(idm), "MOVIE_TITLE": t_en, "MOVIE_TITLE_FR": t_fr, "ORIGINAL_TITLE": t_orig,
                "_YEAR": None if year == "NULL" else int(year),
                "_VOTES": None if votes == "NULL" else int(votes),
            }
    return persons, credits


PERSONS, CREDITS = load_fixture()


class FakeCursor:
    def __init__(self):
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT ID_PERSON, PERSON_NAME"):
            self.rows = [{"ID_PERSON": PERSONS[n], "PERSON_NAME": n} for n in params if n in PERSONS]
            return
        ids = [int(x) for x in re.search(r"ID_PERSON IN \(([^)]*)\)", sql).group(1).split(",")]
        need = int(re.search(r"= (\d+)$", sql).group(1))
        seen = {}
        for pid in ids:
            for mid, row in CREDITS.get(pid, {}).items():
                seen.setdefault(mid, (row, set()))[1].add(pid)
        self.rows = [row for row, who in seen.values() if len(who) >= need]

    def fetchall(self):
        return self.rows


class FakeConnection:
    def cursor(self):
        return FakeCursor()


class Msg:
    def __init__(self, position, text):
        self.position, self.text = position, text


# Anonymized SQL of the 2026-11-08 trace (columns trimmed).
SQL = ("SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE FROM T_WC_T2S_MOVIE "
       "JOIN T_WC_T2S_PERSON_MOVIE ON T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE "
       "JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON "
       "WHERE T_WC_T2S_MOVIE.MOVIE_TITLE = '{{Movie_title1}}' AND T_WC_T2S_PERSON.PERSON_NAME = '{{Person_name1}}' "
       "AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'cast' ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC")

CASES = [
    # (title as extracted, person, ids that must be chosen, ids that must not)
    ("Raid", "Dany Boon", {382597}, {503838, 20375}),
    ("Ch'tis", "Dany Boon", {8265}, set()),
    ("Astérix", "Dany Boon", {99770}, {9564, 2899, 2395}),
    ("Asterix", "Dany Boon", {99770}, {9564, 2899, 2395}),
    ("Rings", "Viggo Mortensen", {120, 121, 122}, {14564, 91908}),
    ("Taxi", "Samy Naceri", {2330}, {11045}),
    ("Visiteurs", "Jean Reno", {11687, 10353, 248705}, set()),
]


def person_plan(name):
    p = entity._PlannedEntity("Person_name1", "{{Person_name1}}")
    p.resolve_with(entity._substitute_plain("{{Person_name1}}", entity._sql_escape_literal(name), name))
    t = entity._PlannedEntity("Movie_title1", "{{Movie_title1}}")
    t.resolve_with(entity._substitute_plain("{{Movie_title1}}", "Wrong homonym", "Wrong homonym"))
    return {"entities": [t, p], "match_scores": []}


failures = 0
for title, person, must, must_not in CASES:
    extraction = {"question": "Film {{Movie_title1}} avec {{Person_name1}}", "Movie_title1": title, "Person_name1": person}
    res = entity.plan_co_constrained_title_rescue(connection=FakeConnection(), entity_extraction=extraction, plan=person_plan(person))
    if res["outcome"] != "planned":
        print(f"FAIL {title!r} + {person}: {res['outcome']} ({res['detail']})")
        failures += 1
        continue
    ids = {w[0] for w in res["winners"]}
    applied = entity.apply_entity_resolutions(plan=res["plan"], sql_query=SQL, justification="Find {{Movie_title1}} with {{Person_name1}}.",
                                              answer="", position_counter=0, text_message_cls=Msg, messages=[])
    sql = applied["sql_query"]
    ok = must <= ids and not (must_not & ids) and "{{" not in sql and "T_WC_T2S_MOVIE.ID_MOVIE IN (" in sql \
        and f"PERSON_NAME = '{entity._sql_escape_literal(person)}'" in sql
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {title!r} + {person}: pool {res['pool_size']}, {len(ids)} winner(s): {res['detail'].split(': ', 1)[1][:200]}")
    if not ok:
        print("     ", sql)

# Not applicable: no person, or two titles.
r = entity.plan_co_constrained_title_rescue(connection=FakeConnection(), entity_extraction={"question": "x", "Movie_title1": "Raid"}, plan={"entities": []})
failures += 0 if r["outcome"] == "not_applicable" else 1
print(("PASS" if r["outcome"] == "not_applicable" else "FAIL"), "no person ->", r["outcome"])
# Person on raw fallback: no rescue.
p = entity._PlannedEntity("Person_name1", "{{Person_name1}}")
p.resolve_with(entity._substitute_plain("{{Person_name1}}", "Dany Bon", "Dany Bon"), is_raw_fallback=True)
r = entity.plan_co_constrained_title_rescue(connection=FakeConnection(), entity_extraction={"question": "x", "Movie_title1": "Raid", "Person_name1": "Dany Bon"}, plan={"entities": [p]})
failures += 0 if r["outcome"] == "no_person" else 1
print(("PASS" if r["outcome"] == "no_person" else "FAIL"), "person on raw fallback ->", r["outcome"])
# A title absent from the filmography stays empty.
r = entity.plan_co_constrained_title_rescue(connection=FakeConnection(), entity_extraction={"question": "x", "Movie_title1": "Godfather", "Person_name1": "Dany Boon"}, plan=person_plan("Dany Boon"))
failures += 0 if r["outcome"] == "no_match" else 1
print(("PASS" if r["outcome"] == "no_match" else "FAIL"), "Godfather + Dany Boon ->", r["outcome"], "|", r["detail"][:160])

print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
