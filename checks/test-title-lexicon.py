#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for the title lexicon (FASTAPI-TEXT2SQL-360).

    uv run checks/test-title-lexicon.py            # exit 0 when every case passes
    uv run checks/test-title-lexicon.py --verbose

No API, no database, no ChromaDB: a hand-written pool shaped like ``T_WC_T2S_MOVIE`` pins
``title_lexicon.TitleLexicon.search`` on the hard cases of the 2026-11-02 bench, then runs the
``lexicon`` strategy of ``entity.plan_entity_resolutions`` against a fake cursor, to check the SQL
substitution (the matched column picks the substituted value, the multi-column OR stays) and the
fallback note when the lexicon misses.
"""
import copy
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import title_lexicon as tl  # noqa: E402

COLS = ["MOVIE_TITLE", "MOVIE_TITLE_FR", "ORIGINAL_TITLE"]
# (id, year, votes, popularity, EN, FR, original), real ids and titles from the 2026-11-02 pool.
POOL = [
    (289, 1943, 663653, 12.9, "Casablanca", "Casablanca", "Casablanca"),
    (603404, 2019, 1637, 1.0, "Casablanca", "Casablanca", "Casablanca"),
    (8974, 1953, 42428, 9.0, "The War of the Worlds", "La Guerre des mondes", "The War of the Worlds"),
    (74, 2005, 516498, 20.0, "War of the Worlds", "La Guerre des mondes", "War of the Worlds"),
    (764837, 2022, 1910, 2.0, "Babysitter", "Babysitter", "Babysitter"),
    (37141, 2017, 120000, 8.0, "The Babysitter", "The Babysitter", "The Babysitter"),
    (935, 1964, 556570, 15.0, "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb",
     "Docteur Folamour", "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb"),
    (1070729, 2020, 12, 0.1, "Dr. Strange Glove", "Dr. Strange Glove", "Dr. Strange Glove"),
    (66556, 1976, 794, 1.0, "Noroît (Une Vengeance)", "Noroît (Une Vengeance)", "Noroît (Une Vengeance)"),
    (45212, 1946, 1668, 2.0, "The Diary of a Chambermaid", "Le Journal d'une femme de chambre", "The Diary of a Chambermaid"),
    (36245, 1964, 10706, 4.0, "Diary of a Chambermaid", "Le Journal d'une femme de chambre", "Le Journal d'une femme de chambre"),
    (146794, 1965, 449, 0.4, "Twenty-Four Hours to Kill", "Cinquante millions pour Johns", "Twenty-Four Hours to Kill"),
    (233795, 2023, 300, 0.5, "Three Hours to Kill", "3 heures pour tuer", "Three Hours to Kill"),
    (63, 1995, 686494, 16.0, "Twelve Monkeys", "L'Armée des 12 singes", "Twelve Monkeys"),
    (155, 2008, 3245703, 30.0, "The Dark Knight", "The Dark Knight : Le Chevalier noir", "The Dark Knight"),
    (62, 1968, 796320, 14.0, "2001: A Space Odyssey", "2001, l'Odyssée de l'espace", "2001: A Space Odyssey"),
    (76180, 2004, 5737, 4.0, "Empire of Dreams: The Story of the Star Wars Trilogy",
     "Star Wars : L'Empire des Rêves", "Empire of Dreams: The Story of the Star Wars Trilogy"),
    (1212809, 2008, 25, 0.1, "The Most Famous Man in the World!", "The Most Famous Man in the World!", "The Most Famous Man in the World!"),
]

# (mention, year, expected stage, expected first id or None, expected matched column or None)
CASES = [
    ("Casablanca", 1942, "exact", 289, "MOVIE_TITLE"),            # year within one of 1943
    ("Casablanca", 2019, "exact", 603404, "MOVIE_TITLE"),         # the year beats the votes
    ("the war of the worlds", None, "exact", 8974, "MOVIE_TITLE"),  # exact beats article-only
    ("Babysitter", None, "exact", 764837, "MOVIE_TITLE"),
    ("Diary of a chambermaid", 1946, "article", 45212, "MOVIE_TITLE"),  # year beats exact
    ("Dr. Strangelove", 1964, "prefix", 935, "MOVIE_TITLE"),      # abbreviation, then prefix
    ("doctor strangelove", None, "prefix", 935, "MOVIE_TITLE"),
    ("noroît", None, "prefix", 66556, "MOVIE_TITLE"),
    ("24 Hours to Kill", 1965, "exact", 146794, "MOVIE_TITLE"),   # spelled-out number
    ("Vingt-quatre heures pour tuer", None, "miss", None, None),  # never '3 heures pour tuer'
    ("12 Monkeys", 1995, "exact", 63, "MOVIE_TITLE"),
    ("L'Armée des douze singes", None, "exact", 63, "MOVIE_TITLE_FR"),
    ("dark knight", None, "article", 155, "MOVIE_TITLE"),
    ("2001, l'Odyssée de l'espace", None, "exact", 62, "MOVIE_TITLE_FR"),
    ("Star Wars : L'Empire des rêves", None, "exact", 76180, "MOVIE_TITLE_FR"),
    ("the big lebovski", None, "miss", None, None),               # absent from this pool
    ("Escape from New Yrok", None, "miss", None, None),
    ("Jaws", None, "miss", None, None),                           # short word, no prefix
]


def test_search(verbose):
    lex = tl.TitleLexicon(POOL, COLS)
    bad = 0
    for mention, year, stage, first, col in CASES:
        r = lex.search(mention, year, 85.85)
        got_id = r["matches"][0][0] if r["matches"] else None
        got_col = r["matches"][0][1] if r["matches"] else None
        ok = r["stage"] == stage and got_id == first and got_col == col
        bad += not ok
        if verbose or not ok:
            print(f"{'ok ' if ok else 'BAD'} {mention!r} y={year}: {r['stage']} {got_id} {got_col}"
                  f" (expected {stage} {first} {col})")
    return bad, lex


class FakeCursor:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = []
        if "FROM T_WC_T2S_MOVIE" in sql and params:
            for r in POOL:
                if str(r[0]) == str(params[0]):
                    self._rows = [dict(zip(["ID_MOVIE", "RELEASE_YEAR", "IMDB_VOTES", "POPULARITY"] + COLS, r))]

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


class Msg:
    def __init__(self, **kw):
        self.text = kw.get("text", "")
        self.__dict__.update(kw)


class FakeConnection:
    def cursor(self, *a, **k):
        return FakeCursor()


def test_entity(lex, verbose):
    import entity
    cfg = copy.deepcopy(entity.ENTITY_RESOLUTION_CONFIG)
    movie = next(e for e in cfg if e["placeholder_prefix"] == "Movie_title")
    lex_cfg = next(s for s in movie["search_list"] if s.get("search_mode") == "lexicon")
    lex_cfg["enabled"] = True
    movie["search_list"] = [lex_cfg]          # no ChromaDB here: the lexicon alone
    entity.ENTITY_RESOLUTION_CONFIG = cfg
    entity.LEXICON_CONNECTION_FACTORY = None  # use the lexicon injected below, never build
    tl._LEXICONS[tl.lexicon_key(lex_cfg)] = lex
    bad = 0
    sql = "SELECT * FROM T_WC_T2S_MOVIE WHERE MOVIE_TITLE = '{{Movie_title1}}'"
    for mention, year, expect_value, expect_fallback in [
        ("2001, l'Odyssée de l'espace", None, "2001, l''Odyssée de l''espace", False),
        ("Casablanca", 1942, "Casablanca", False),
        ("Jaws", None, None, True),
    ]:
        ee = {"Movie_title1": mention}
        if year:
            ee["Release_year1"] = year
        plan = entity.plan_entity_resolutions(connection=FakeConnection(), entity_extraction=ee,
                                              chromadb_collections_by_name={})
        messages = []
        out = entity.apply_entity_resolutions(plan=plan, sql_query=sql, justification="", answer="",
                                              position_counter=0, text_message_cls=Msg,
                                              messages=messages)
        text = str(out.get("sql_query"))
        msgs = " | ".join(m.text for m in messages)
        if expect_value:
            ok = (expect_value in text and "MOVIE_TITLE_FR" in text and "ORIGINAL_TITLE" in text)
        else:
            ok = "lexicon miss" in text or "lexicon miss" in msgs
        ms = plan.get("match_scores") or []
        ok = ok and bool(ms) and ms[0].get("search_mode") == "lexicon"
        bad += not ok
        if verbose or not ok:
            print(f"{'ok ' if ok else 'BAD'} entity {mention!r}: {text[:300]} || {msgs[:300]}")
    return bad


def main():
    verbose = "--verbose" in sys.argv
    bad, lex = test_search(verbose)
    bad += test_entity(lex, verbose)
    print(f"{len(CASES) + 3 - bad}/{len(CASES) + 3} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
