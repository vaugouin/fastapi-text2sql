#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for FASTAPI-TEXT2SQL-360, second wave: the title lexicon used for plain names
(companies, networks, collections).

    uv run checks/test-name-lexicon.py      # exit 0 when every case passes

No API, no database, no model. Pins what the bench (checks/bench-lexical-360-names.py) chose:
ranking by credits so an obscure exact homonym loses ("paramount" is Paramount Pictures, not
Paramount+), descriptors stripped on both sides ("collection James Bond" meets "James Bond
Collection"), the full form winning when the mention carried a descriptor ("Collection Batman"),
and the SQL that builds the lexicon from the three strategies of data/entity_resolution.json
(credits as a sum, no POPULARITY column for networks). Ids and credits are those of the live
tables on 2026-11-05.
"""
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import title_lexicon as tl  # noqa: E402

with open(os.path.join(RACINE, "data", "entity_resolution.json"), encoding="utf-8") as f:
    CFG = {e["placeholder_prefix"]: e["search_list"] for e in json.load(f)}
LEX = {k: next(s for s in v if s.get("search_mode") == "lexicon")
       for k, v in CFG.items() if k in ("Company_name", "Network_name", "Collection_name")}

FAILED = 0


def check(label, got, want):
    global FAILED
    ok = got == want
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {got!r}" + ("" if ok else f", want {want!r}"))


def build(typ, rows):
    """rows: (id, credits, popularity, name[, name_fr]) -> the lexicon the API would build."""
    cfg = LEX[typ]
    cols = list(dict.fromkeys(cfg["languages"].values()))
    data = [(r[0], None, r[1], r[2]) + tuple(r[3:]) + ("",) * (len(cols) - len(r[3:])) for r in rows]
    return tl.TitleLexicon(data, cols, strip_words=cfg.get("lexicon_strip_words"),
                           strip_mode=cfg.get("lexicon_strip_mode") or "tail"), cfg


def pick(lex, cfg, mention):
    res = lex.lookup(mention, None, float(cfg["min_fuzz_ratio"]))
    return res["matches"][0][0] if res["matches"] else None


# 1. Companies: credits beat an exact homonym, legal tails fold.
comp, ccfg = build("Company_name", [
    (4, 2899, 2.4, "Paramount Pictures"), (314668, 3, 0.2, "Paramount+"),
    (5, 2980, 2.0, "Columbia Pictures"), (102846, 3, 0.8, "Columbia"),
    (33, 2683, 2.8, "Universal Pictures"), (139677, 1, 1.0, "Universal"), (204507, 1, 0.1, "Universal+"),
    (174, 3104, 3.5, "Warner Bros. Pictures"), (261822, 2, 0.1, "Warner Bros. China"),
    (1314, 219, 1.0, "Hammer Film Productions"), (99999, 1, 0.1, "Good Hammer"),
    (9, 665, 1.0, "Gaumont"), (206133, 13, 0.1, "Gaumont"),
    (882, 2079, 1.0, "TOHO"), (49301, 40, 0.1, "Toho Pictures"),
    (260758, 2, 0.1, "Kinflix"),
])
check("company gate is 85", ccfg["min_fuzz_ratio"], 85)
check("paramount -> Paramount Pictures, not Paramount+", pick(comp, ccfg, "Paramount"), 4)
check("columbia -> Columbia Pictures, not the 3-credit Columbia", pick(comp, ccfg, "Columbia"), 5)
check("universal -> Universal Pictures", pick(comp, ccfg, "Universal"), 33)
check("Warner Bros -> Warner Bros. Pictures, not China", pick(comp, ccfg, "Warner Bros"), 174)
check("Warner Bros. (with the dot) too", pick(comp, ccfg, "Warner Bros."), 174)
check("Hammer -> Hammer Film Productions", pick(comp, ccfg, "Hammer"), 1314)
check("Gaumont -> the Gaumont with credits", pick(comp, ccfg, "Gaumont"), 9)
check("Toho -> TOHO (case)", pick(comp, ccfg, "Toho"), 882)
check("Toho Pictures stays itself", pick(comp, ccfg, "Toho Pictures"), 49301)
check("typo Paramout Pictures -> 4", pick(comp, ccfg, "Paramout Pictures"), 4)
check("Wikiflix stays a miss at 85", pick(comp, ccfg, "Wikiflix"), None)

# 2. Networks: same-name entities ranked by series, no popularity column.
net, ncfg = build("Network_name", [(1590, 6, 0, "HBO"), (49, 362, 0, "HBO"), (8102, 5, 0, "HBO"),
                                   (951, 37, 0, "Canal+"), (285, 275, 0, "Canal+")])
check("HBO -> 49 (362 series)", pick(net, ncfg, "HBO"), 49)
check("Canal+ -> 285", pick(net, ncfg, "Canal+"), 285)

# 3. Collections: franchise words on both sides, EN and FR names, full form when asked.
col, kcfg = build("Collection_name", [
    (84, 30, 5.0, "James Bond Collection", "James Bond - Saga"),
    (646, 4, 1.0, "Batman Collection", "Batman - Saga"), (4852, 9, 1.0, "Batman", "Batman"),
    (1831, 50, 1.0, "Tora-san Series", "Tora-san - Saga"),
    (72, 3, 9.0, "Back to the Future Collection", "Retour vers le futur - Saga"),
])
check("collection James Bond -> 84", pick(col, kcfg, "collection James Bond"), 84)
check("Collection Tora San -> 1831", pick(col, kcfg, "Collection Tora San"), 1831)
check("Batman Collection asked in full -> 646", pick(col, kcfg, "Batman Collection"), 646)
check("collection Retour vers le futur (FR name) -> 72", pick(col, kcfg, "collection Retour vers le futur"), 72)
res = col.lookup("collection Retour vers le futur", None, 73.5)
check("the FR hit reports its column", res["matches"][0][1], "COLLECTION_NAME_FR")

# 4. The build SQL of each strategy.
class Cur:
    def __init__(self):
        self.sql = None

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


for typ, want_votes, want_pop in (("Company_name", "COALESCE(m.`MOVIE_COUNT`, 0) + COALESCE(m.`SERIE_COUNT`, 0)", "COALESCE(m.`POPULARITY`, 0)"),
                                  ("Network_name", "COALESCE(m.`SERIE_COUNT`, 0)", None),
                                  ("Collection_name", "COALESCE(m.`MOVIE_COUNT`, 0) + COALESCE(m.`SERIE_COUNT`, 0)", "COALESCE(m.`POPULARITY`, 0)")):
    c = Conn()
    tl.build_from_db(c, LEX[typ])
    check(f"{typ} build sums its credits", want_votes in c.cur.sql, True)
    check(f"{typ} build reads popularity only where it exists", ("POPULARITY" in c.cur.sql), want_pop is not None)

# 5. Titles are untouched: no strip words, lookup is search.
mv = next(s for s in CFG["Movie_title"] if s.get("search_mode") == "lexicon")
check("movie lexicon declares no strip words", mv.get("lexicon_strip_words"), None)

print(f"\n{'OK' if not FAILED else f'{FAILED} FAILED'}")
sys.exit(1 if FAILED else 0)
