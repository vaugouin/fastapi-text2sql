#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for the homonym check of the complex retry (FASTAPI-TEXT2SQL-355).

    uv run checks/test-complex-identity.py            # exit 0 when every case passes
    uv run checks/test-complex-identity.py --verbose  # print scores and matches

No API, no database, no model. The complex retry reuses the decision of the vision path
(``vision_identity.pick_vision_identity``, FASTAPI-TEXT2SQL-307) with one difference: there is
no face, only the credits the complex model KNOWS for the work it named (``known_credits``).
These cases pin that the credits alone choose the right namesake, in both directions, and that
nothing is chosen when they cannot. The candidate rows are the real collisions of
``text2sql-eval/harvest-title-year-homonyms-20260930.txt`` (ids, original titles, languages,
directors, first billed actors), the same rows the evaluations of
``text2sql-eval/new-evaluations-355-homonyms.sql`` assert on.

The last block pins the pattern that decides which rewrites are identity lookups at all, read
from ``text2sql.py`` itself so the test follows the code without importing its dependencies.
"""
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import vision_identity as vi  # noqa: E402


def row(i, imdb, title, lang, directors, cast):
    return {"id": i, "id_imdb": imdb, "original_title": title, "original_language": lang,
            "directors": directors, "cast": cast}


TAXI = [row(103, "tt0075314", "Taxi Driver", "en", ["Martin Scorsese"],
            ["Robert De Niro", "Jodie Foster", "Cybill Shepherd"]),
        row(612176, "tt0281258", "Taksi Şoförü", "tr", ["Şerif Gören"],
            ["Kadir İnanır", "Banu Alkan"])]
LEO = [row(949229, "tt15654328", "லியோ", "ta", ["Lokesh Kanagaraj"], ["Vijay", "Sanjay Dutt"]),
       row(1075794, "tt5755238", "Leo", "en",
           ["David Wachtenheim", "Robert Marianetti", "Robert Smigel"], ["Adam Sandler", "Bill Burr"]),
       row(1169632, "tt43721254", "Leo", "en", [], [])]
MESSAGE = [row(26842, "tt0074896", "The Message", "en", ["Moustapha Akkad"],
               ["Anthony Quinn", "Irene Papas"]),
           row(881210, "tt0075143", "Al-risâlah", "ar", ["Moustapha Akkad"], [])]
ARRIVAL = [row(329865, "tt2543164", "Arrival", "en", ["Denis Villeneuve"], ["Amy Adams", "Jeremy Renner"]),
           row(472349, "tt5433758", "Arrival", "en", [], [])]
CRASH = [row(1640, "tt0375679", "Crash", "en", ["Paul Haggis"], ["Don Cheadle", "Sandra Bullock"]),
         row(468180, "tt0759905", "Çarpışma", "tr", ["Umut Aral"], ["Gürkan Uygun"])]
EMMA = [row(3573, "tt0116191", "Emma", "en", ["Douglas McGrath"], ["Gwyneth Paltrow"]),
        row(12254, "tt0118308", "Emma", "en", ["Diarmuid Lawrence"], ["Kate Beckinsale"])]
DIPLOMAT = [row(203857, "tt17491088", "The Diplomat", "en", ["Debora Cahn"], ["Keri Russell", "Rufus Sewell"]),
            row(203762, "tt17001504", "The Diplomat", "en", ["Ben Richards"], ["Sophie Rundle", "Steven Cree"])]


def credits(directors=(), lead_cast=(), original_title="", original_language=""):
    """What the complex model returns, turned into discriminators exactly as main.py does."""
    return vi.discriminators_from_vision(
        {"known_credits": {"directors": list(directors), "lead_cast": list(lead_cast),
                           "original_title": original_title,
                           "original_language": original_language}}, [])


CASES = [
    ("Taxi Driver tagline: Scorsese, De Niro", TAXI,
     credits(["Martin Scorsese"], ["Robert De Niro", "Jodie Foster"], "Taxi Driver", "en"),
     "picked", [103]),
    ("Taxi Driver reverse: the 154-vote Turkish film wins on its credits", TAXI,
     credits(["Şerif Gören"], ["Kadir İnanır"], "Taksi Şoförü", "tr"), "picked", [612176]),
    ("Taxi Driver, credits written without Turkish letters", TAXI,
     credits(["Serif Goren"], ["Kadir Inanir"], "", "tr"), "picked", [612176]),
    ("Leo Tamil against two English Leo", LEO,
     credits(["Lokesh Kanagaraj"], ["Vijay"], "Leo", "ta"), "picked", [949229]),
    ("Leo Netflix, the less voted of the two known films", LEO,
     credits(["Robert Marianetti", "Robert Smigel", "David Wachtenheim"], ["Adam Sandler"], "Leo", "en"),
     "picked", [1075794]),
    ("The Message, Arabic version: shared director, the language decides", MESSAGE,
     credits(["Moustapha Akkad"], [], "Al-Risalah", "ar"), "picked", [881210]),
    ("The Message, English version: Anthony Quinn decides", MESSAGE,
     credits(["Moustapha Akkad"], ["Anthony Quinn"], "The Message", "en"), "picked", [26842]),
    ("Arrival: a namesake with no credits in base scores 0", ARRIVAL,
     credits(["Denis Villeneuve"], ["Amy Adams"], "Arrival", "en"), "picked", [329865]),
    ("Crash: year written 2004 by the model, candidates read at +/- 1", CRASH,
     credits(["Paul Haggis"], ["Don Cheadle"], "Crash", "en"), "picked", [1640]),
    ("The Diplomat 2023: the creator and Keri Russell", DIPLOMAT,
     credits(["Debora Cahn"], ["Keri Russell"], "The Diplomat", "en"), "picked", [203857]),
    ("Emma 1996, wrong names: only the shared language matches, undecided", EMMA,
     credits(["Jane Austen"], ["Ewan McGregor"], "Emma", "en"), "undecided", [3573, 12254]),
    ("No credits at all: nothing to compare, every namesake kept", TAXI,
     credits(), "no_discriminator", [103, 612176]),
    ("One candidate: nothing to decide", TAXI[:1],
     credits(["Martin Scorsese"]), "single", [103]),
]


def identity_pattern():
    src = open(os.path.join(RACINE, "text2sql.py"), encoding="utf-8").read()
    m = re.search(r'^_COMPLEX_IDENTITY_PATTERN = re\.compile\(r"(.+?)", re\.IGNORECASE\)$', src, re.M)
    assert m, "_COMPLEX_IDENTITY_PATTERN not found in text2sql.py"
    return re.compile(m.group(1), re.IGNORECASE)


PATTERN_CASES = [
    ("Movie Taxi Driver (1976)", ("Movie", "Taxi Driver", "1976")),
    ("Serie The Diplomat (2023)", ("Serie", "The Diplomat", "2023")),
    ("Movie Star Wars: Episode IV (1977)", ("Movie", "Star Wars: Episode IV", "1977")),
    ("Movies Blue (1993), White (1994), Red (1994)", None),
    ("Person Robert De Niro born in 1943", None),
    ("Movie Taxi Driver", None),
    ("In which city does Taxi Driver (1976) take place?", None),
]


def main() -> int:
    verbose = "--verbose" in sys.argv
    failures = 0
    for name, candidates, disc, want_decision, want_kept in CASES:
        got = vi.pick_vision_identity(candidates, disc)
        ok = got["decision"] == want_decision and got["kept"] == want_kept
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if verbose or not ok:
            print(f"      decision {got['decision']} kept {got['kept']} (want {want_decision} {want_kept})")
            for cid, sc in got["scores"].items():
                print(f"      {cid}: {sc['score']} {sc['matches']}")
    pattern = identity_pattern()
    for text, want in PATTERN_CASES:
        m = pattern.match(text.strip())
        got = m.groups() if m else None
        ok = got == want
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  pattern {text!r} -> {got}")
    total = len(CASES) + len(PATTERN_CASES)
    print(f"{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
