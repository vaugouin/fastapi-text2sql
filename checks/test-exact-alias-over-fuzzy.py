#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for FASTAPI-TEXT2SQL-365: an exact person alias beats a fuzzy main-name match.

    uv run checks/test-exact-alias-over-fuzzy.py      # exit 0 when every case passes

No API, no database, no model. Pins `entity._exact_match_in_later_strategy`, the probe the
resolver runs when the main-name strategy accepted a FUZZY match: which later strategies it
asks (only those declaring `exact_beats_earlier_fuzzy`, in the language they apply to), what
it sends (the normalized value, through the same exact-match query as `search_first_match`),
and what it refuses (a value normalized to nothing, which would match the punctuation-only
aliases such as "..."). The popularity guard itself is a comparison in `resolve_entities`; its
four real cases are in text2sql-eval/check-exact-alias-over-fuzzy-name-20261105.txt and the
evaluations 565, 849, 2262 and 2629.
"""
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import entity  # noqa: E402

with open(os.path.join(RACINE, "data", "entity_resolution.json"), encoding="utf-8") as f:
    PERSON = next(e for e in json.load(f) if e.get("placeholder_prefix") == "Person_name")["search_list"]

ALIASES = {  # PERSON_NAME_NORM -> rows, most popular first, as the ORDER BY returns them
    "chu kong": [{"ID_ROW": 1, "PERSON_NAME": "Chu Kong", "PERSON_NAME_NORM": "chu kong", "ID_PERSON": 67047, "POPULARITY": 92.5}],
    "john voigt": [{"ID_ROW": 2, "PERSON_NAME": "John Voigt", "PERSON_NAME_NORM": "john voigt", "ID_PERSON": 29124, "POPULARITY": 0.3}],
}


class Cursor:
    def __init__(self):
        self.queries = []
        self.row = None

    def execute(self, sql, args=None):
        self.queries.append((sql, args))
        rows = ALIASES.get(args[0]) if "T_WC_T2S_PERSON_ALSO_KNOWN_AS" in sql else None
        self.row = rows[0] if rows else None

    def fetchone(self):
        return self.row


FAILED = 0


def check(label, got, want):
    global FAILED
    ok = got == want
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {got!r}" + ("" if ok else f", want {want!r}"))


# 1. The configuration declares the probe on the alias strategy, and only there.
check("alias strategy declares exact_beats_earlier_fuzzy",
      [bool(s.get("exact_beats_earlier_fuzzy")) for s in PERSON], [False, True])

# 2. From the main-name strategy (index 0), an exact alias is found and returned with its person.
cur = Cursor()
cfg, row = entity._exact_match_in_later_strategy(cur, PERSON, 0, "Chu Kong", "Latin")
check("Chu Kong found in the alias table", (cfg or {}).get("strtablename"), "T_WC_T2S_PERSON_ALSO_KNOWN_AS")
check("Chu Kong row carries its person", (row or {}).get("ID_PERSON"), 67047)
check("the probe orders by popularity", "ORDER BY" in cur.queries[-1][0] and "POPULARITY" in cur.queries[-1][0], True)
check("the value is sent normalized", cur.queries[-1][1], ("chu kong",))

# 3. The probe returns the alias even when it is obscure: the popularity guard decides later.
cfg, row = entity._exact_match_in_later_strategy(Cursor(), PERSON, 0, "john voigt", "Latin")
check("john voigt alias returned to the guard", (row or {}).get("POPULARITY"), 0.3)

# 4. No exact alias: nothing returned.
cfg, row = entity._exact_match_in_later_strategy(Cursor(), PERSON, 0, "Chu Bong", "Latin")
check("no alias, no preemption", (cfg, row), (None, None))

# 5. From the alias strategy itself there is no later strategy to ask.
cur = Cursor()
check("nothing after the last strategy", entity._exact_match_in_later_strategy(cur, PERSON, 1, "Chu Kong", "Latin"), (None, None))
check("and no query sent", len(cur.queries), 0)

# 6. A value normalized to nothing never reaches the table ("..." aliases).
cur = Cursor()
check("punctuation only is refused", entity._exact_match_in_later_strategy(cur, PERSON, 0, "...", "Latin"), (None, None))
check("and no query sent for it", len(cur.queries), 0)

# 7. A strategy switched off is skipped.
off = [dict(PERSON[0]), dict(PERSON[1], enabled=False)]
check("disabled alias strategy is skipped", entity._exact_match_in_later_strategy(Cursor(), off, 0, "Chu Kong", "Latin"), (None, None))

print(f"\n{'OK' if not FAILED else f'{FAILED} FAILED'}")
sys.exit(1 if FAILED else 0)
