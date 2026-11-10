#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for FASTAPI-TEXT2SQL-374: exact award names before the embeddings.

    uv run --no-project --with-requirements requirements.txt python checks/test-award-lexicon-374.py
    ... --verbose

No API, no database, no ChromaDB. Pins what checks/bench-lexical-374-awards.py chose on the
2026-11-10 pool (18 118 awards):

- an award name written as it stands in AWARD_NAME or AWARD_NAME_FR (case, accents and a leading
  article apart) resolves to that award, in the column that matched: "Oscar de la meilleure
  actrice" is 269, never the Ophir (15014) the embeddings returned;
- the strategy runs the exact stage only ("lexicon_stages": ["exact"]): "Academy Award" must not
  complete into the most rewarded "Academy Award for ..." category, "Golden Globe" must not become
  one of its categories, "prix Oscar" must not reach "prix Oscar-Mathisen"; they fall through to
  the embeddings strategy, as before;
- among awards sharing a name, the one with the most winners comes first;
- entity.py hands "lexicon_stages" to the lexicon, and the SQL takes the matched column.

Ids and counts (PERSON_COUNT + MOVIE_COUNT + SERIE_COUNT) are those of the live table on
2026-11-10.
"""
import copy
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import title_lexicon as tl  # noqa: E402

VERBOSE = "--verbose" in sys.argv

with open(os.path.join(RACINE, "data", "entity_resolution.json"), encoding="utf-8") as f:
    CFG = json.load(f)
AWARD = next(e for e in CFG if e["placeholder_prefix"] == "Award_name")
LEX_CFG = next(s for s in AWARD["search_list"] if s.get("search_mode") == "lexicon")
COLS = list(dict.fromkeys(LEX_CFG["languages"].values()))

# (id, year, winners, popularity, AWARD_NAME, AWARD_NAME_FR)
POOL = [
    (269, None, 179, 3.198, "Academy Award for Best Actress", "Oscar de la meilleure actrice"),
    (15014, None, 22, 0.410, "Ophir Award for Best Actress", "Ophir de la meilleure actrice"),
    (10464, None, 17, 2.927, "Academy Awards", "Oscars du cinéma"),
    (146, None, 226, 1.354, "Academy Award for Best Picture", "Oscar du meilleur film"),
    (28960, None, 236, 0.445, "Academy Award for Best Sound", "Oscar du meilleur son"),
    (9151, None, 55, 2.313, "César Award", "César du cinéma"),
    (25677, None, 50, 1.040, "César Award for Best Film", "César du meilleur film"),
    (71, None, 145, 3.308, "Golden Globes", "Golden Globes"),
    (6455, None, 16, 0.559, "Golden Globes", "Globos de Ouro"),
    (28913, None, 72, 3.371, "Golden Globe Award for Best Supporting Actress – Motion Picture",
     "Golden Globe de la meilleure actrice dans un second rôle"),
    (30680, None, 33, 0.589, "Osgar", "Osgar"),
    (46238, None, 4, 0.187, "Oscar Mathisen Award", "prix Oscar-Mathisen"),
    (52443, None, 1, 0.0, "", ""),                      # a live row with no name: never a key
]

FAILED = 0


def check(label, got, want):
    global FAILED
    ok = got == want
    FAILED += 0 if ok else 1
    if VERBOSE or not ok:
        print(f"{'PASS' if ok else 'FAIL'}  {label}: got {got!r}" + ("" if ok else f", want {want!r}"))


def first(res):
    return (res["stage"],) + (tuple(res["matches"][0][:2]) if res["matches"] else (None, None))


# 1. The configuration: the lexicon first, exact only, the embeddings behind it.
check("Award_name cascade", [s.get("search_mode") for s in AWARD["search_list"]], ["lexicon", "embeddings"])
check("lexicon_stages", LEX_CFG.get("lexicon_stages"), ["exact"])
check("both name columns indexed", COLS, ["AWARD_NAME", "AWARD_NAME_FR"])
check("no fuzzy gate declared (none measured)", "min_fuzz_ratio" in LEX_CFG, False)
check("embeddings gate untouched", AWARD["search_list"][1].get("min_fuzz_ratio"), 74.45)

STAGES = LEX_CFG["lexicon_stages"]
lex = tl.TitleLexicon(POOL, COLS)

# 2. Exact names, both languages, case, accents and article apart.
for mention, want in [
    ("Oscar de la meilleure actrice", ("exact", 269, "AWARD_NAME_FR")),      # the ticket's case
    ("oscar de la meilleure ACTRICE", ("exact", 269, "AWARD_NAME_FR")),
    ("l'Oscar de la meilleure actrice", ("article", 269, "AWARD_NAME_FR")),
    ("Academy Award for Best Actress", ("exact", 269, "AWARD_NAME")),
    ("the Academy Award for Best Actress", ("article", 269, "AWARD_NAME")),
    ("Ophir de la meilleure actrice", ("exact", 15014, "AWARD_NAME_FR")),    # the Ophir stays reachable
    ("Academy Awards", ("exact", 10464, "AWARD_NAME")),
    ("Oscars du cinéma", ("exact", 10464, "AWARD_NAME_FR")),
    ("Cesar du meilleur film", ("exact", 25677, "AWARD_NAME_FR")),           # accent dropped
    ("Golden Globes", ("exact", 71, "AWARD_NAME")),                          # 145 winners before 16
]:
    check(f"exact only: {mention!r}", first(lex.lookup(mention, None, 85.85, STAGES)), want)

# 3. What the exact stage leaves to the embeddings, and what the other stages would have done.
for mention, loose in [
    ("Academy Award", ("prefix", 28960)),      # the category with the most winners
    ("Golden Globe", ("prefix", 28913)),
    ("prix Oscar", ("prefix", 46238)),         # Oscar Mathisen
    ("Academy Awards for Best Actress", None),
    ("Oscar", None),
    ("Oscars", None),
]:
    check(f"exact only: {mention!r} is a miss", first(lex.lookup(mention, None, 85.85, STAGES)), ("miss", None, None))
    if loose:
        check(f"all stages would send {mention!r} to", first(lex.lookup(mention, None, 85.85))[:2], loose)

# 4. The stage list is read loosely, and absent it changes nothing.
check("stages given as a tuple, any case", first(lex.search("Academy Award", None, 85.85, ("Exact ",))), ("miss", None, None))
check("prefix listed, prefix runs", first(lex.search("Academy Award", None, 85.85, ["exact", "prefix"]))[:2], ("prefix", 28960))
check("fuzzy not listed, a typo is a miss", first(lex.search("Academy Awarts", None, 85.85, ["exact", "prefix"])), ("miss", None, None))
check("no list, the typo is found", first(lex.search("Academy Awarts", None, 85.85))[:2], ("fuzzy", 10464))


# 5. The build SQL: winners as a sum of the three counts, POPULARITY read.
class Cur:
    sql = None

    def execute(self, sql, args=None):
        self.sql = sql

    def __iter__(self):
        return iter(())

    def close(self):
        pass


class Conn:
    def __init__(self):
        self.cur = Cur()

    def cursor(self, *_):
        return self.cur


c = Conn()
tl.build_from_db(c, LEX_CFG)
check("build sums the winners",
      "COALESCE(m.`PERSON_COUNT`, 0) + COALESCE(m.`MOVIE_COUNT`, 0) + COALESCE(m.`SERIE_COUNT`, 0)" in c.cur.sql, True)
check("build reads POPULARITY", "COALESCE(m.`POPULARITY`, 0)" in c.cur.sql, True)
check("build reads T_WC_T2S_AWARD, living rows", "FROM `T_WC_T2S_AWARD` m WHERE COALESCE(m.`DELETED`, 0) = 0" in c.cur.sql, True)


# 6. Through entity.py: the strategy receives its stage list, the SQL takes the matched column.
class FakeCursor:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = []
        if "FROM T_WC_T2S_AWARD" in sql and params:
            for r in POOL:
                if str(r[0]) == str(params[0]):
                    self._rows = [{"ID_AWARD": r[0], "AWARD_NAME": r[4], "AWARD_NAME_FR": r[5]}]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def cursor(self, *a, **k):
        return FakeCursor()


class Msg:
    def __init__(self, **kw):
        self.text = kw.get("text", "")
        self.__dict__.update(kw)


import entity  # noqa: E402

cfg = copy.deepcopy(CFG)
award = next(e for e in cfg if e["placeholder_prefix"] == "Award_name")
lex_cfg = next(s for s in award["search_list"] if s.get("search_mode") == "lexicon")
lex_cfg["enabled"] = True                    # ships switched off until the restart on the -374 code
award["search_list"] = [lex_cfg]             # no ChromaDB here: the lexicon alone
entity.ENTITY_RESOLUTION_CONFIG = cfg
entity.LEXICON_CONNECTION_FACTORY = None     # use the lexicon injected below, never build
tl._LEXICONS[tl.lexicon_key(lex_cfg)] = lex

SQL = ("SELECT p.ID_PERSON FROM T_WC_T2S_PERSON_AWARD pa JOIN T_WC_T2S_AWARD a ON a.ID_AWARD = pa.ID_AWARD "
       "WHERE a.AWARD_NAME = '{{Award_name1}}'")
for mention, want_sql, want_stage in [
    ("Oscar de la meilleure actrice", "AWARD_NAME_FR = 'Oscar de la meilleure actrice'", "exact"),
    ("Academy Award for Best Actress", "AWARD_NAME = 'Academy Award for Best Actress'", "exact"),
    ("Academy Award", None, "miss"),         # with the prefix stage this would be 28960
]:
    plan = entity.plan_entity_resolutions(connection=FakeConnection(), entity_extraction={"Award_name1": mention},
                                          chromadb_collections_by_name={})
    messages = []
    out = entity.apply_entity_resolutions(plan=plan, sql_query=SQL, justification="", answer="",
                                          position_counter=0, text_message_cls=Msg, messages=messages)
    text = str(out.get("sql_query"))
    ms = plan.get("match_scores") or []
    check(f"entity {mention!r}: strategy and stage",
          [(m.get("search_mode"), m.get("lexicon_stage")) for m in ms][:1], [("lexicon", want_stage)])
    if want_sql:
        check(f"entity {mention!r}: SQL holds {want_sql}", want_sql in text, True)
        check(f"entity {mention!r}: no Ophir", "Ophir" in text, False)
    else:
        check(f"entity {mention!r}: nothing substituted", "Academy Award for" in text, False)
    if VERBOSE:
        print("      ", text[:260], "||", " | ".join(m.text for m in messages)[:200])

print(f"\n{'OK' if not FAILED else f'{FAILED} FAILED'}")
sys.exit(1 if FAILED else 0)
