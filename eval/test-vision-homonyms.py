#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline battery for the vision identity check (FASTAPI-TEXT2SQL-307, bench A).

    uv run eval/test-vision-homonyms.py            # exit 0 when every case passes
    uv run eval/test-vision-homonyms.py --verbose  # print scores and matches

No API, no database, no model, no image: it pins the DECISION made by
``vision_identity.pick_vision_identity`` among rows that share a title and a year. The
candidate rows are hand-written fixtures shaped like what the caller will read from
``T_WC_T2S_MOVIE`` / ``T_WC_T2S_SERIE`` and their credit tables. Real title-and-year collisions
for the live bench come from ``eval/harvest-title-year-homonyms.sql`` (bench B).

The case that matters most is the REVERSE one: a still from the obscure film must return the
obscure film. It is what proves the decision is not a popularity rule in disguise.
"""
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import vision_identity as vi  # noqa: E402

# The two 1976 "Taxi Driver" of the 2026-09-30 log (ID_MOVIE 103 and 612176).
SCORSESE = {
    "id": 103, "id_imdb": "tt0075314", "original_title": "Taxi Driver", "original_language": "en",
    "directors": ["Martin Scorsese"],
    "cast": ["Robert De Niro", "Jodie Foster", "Cybill Shepherd", "Harvey Keitel", "Albert Brooks"],
}
GOREN = {
    "id": 612176, "id_imdb": "tt0281258", "original_title": "Taksi Şoförü", "original_language": "tr",
    "directors": ["Şerif Gören"],
    "cast": ["Kadir İnanır", "Banu Alkan", "Bora Ayanoğlu", "Levent İnanır", "İlhan Hemşeri"],
}
TAXI = [SCORSESE, GOREN]

# Synthetic series pair: same title, same first-air year, different creators.
SERIE_A = {"id": 9001, "original_title": "The Pier", "original_language": "en",
           "directors": ["Ann Example"], "cast": ["Paul Sample", "Maria Test"]}
SERIE_B = {"id": 9002, "original_title": "El muelle", "original_language": "es",
           "directors": ["Juan Ejemplo"], "cast": ["Lucia Prueba", "Diego Muestra"]}


# Real groups from eval/harvest-title-year-homonyms-20260930.txt, credits as the database holds
# them (NULL credits become empty lists).
# The Message (1976): English and Arabic versions shot together by the SAME director, and the
# Arabic row has no cast in the database. Only the language can separate them.
MESSAGE_EN = {"id": 26842, "id_imdb": "tt0074896", "original_title": "The Message", "original_language": "en",
              "directors": ["Moustapha Akkad"], "cast": ["Anthony Quinn", "Irene Papas"]}
MESSAGE_AR = {"id": 881210, "id_imdb": "tt0075143", "original_title": "Al-risâlah", "original_language": "ar",
              "directors": ["Moustapha Akkad"], "cast": []}
# Leo (2023): two well-known films (75,128 and 47,395 votes) plus a third with no credits. The
# Tamil original title is in Tamil script, so a model that transliterates it as "Leo" matches
# the WRONG film on the title; the director and the language must outweigh that.
LEO_TA = {"id": 949229, "id_imdb": "tt15654328", "original_title": "லியோ", "original_language": "ta",
          "directors": ["Lokesh Kanagaraj"], "cast": ["Vijay", "Sanjay Dutt"]}
LEO_EN = {"id": 1075794, "id_imdb": "tt5755238", "original_title": "Leo", "original_language": "en",
          "directors": ["David Wachtenheim", "Robert Marianetti", "Robert Smigel"],
          "cast": ["Adam Sandler", "Bill Burr"]}
LEO_X = {"id": 1169632, "id_imdb": "tt43721254", "original_title": "Leo", "original_language": "en",
         "directors": [], "cast": []}
LEO = [LEO_TA, LEO_EN, LEO_X]


def disc(**kw):
    base = {"faces": [], "directors": [], "lead_cast": [], "original_title": "", "original_language": ""}
    base.update(kw)
    return base


CASES = [
    # (name, candidates, discriminators, expected decision, expected kept ids)
    ("origin case: De Niro's face + Scorsese",
     TAXI, disc(faces=["Robert De Niro"], directors=["Martin Scorsese"], original_language="en"),
     "picked", [103]),
    ("origin case, face only (recognition cache entry written before -307)",
     TAXI, disc(faces=["Robert De Niro"]), "picked", [103]),
    ("reverse, anti-popularity: Gören + İnanır pick the 154-vote film",
     TAXI, disc(faces=["Kadir İnanır"], directors=["Şerif Gören"], original_language="tr"),
     "picked", [612176]),
    ("reverse, names written without Turkish letters",
     TAXI, disc(directors=["Serif Goren"], lead_cast=["Kadir Inanir"]), "picked", [612176]),
    ("poster with no face: known credits alone decide",
     TAXI, disc(directors=["Martin Scorsese"], lead_cast=["Robert De Niro", "Jodie Foster"]),
     "picked", [103]),
    ("original title alone decides",
     TAXI, disc(original_title="Taksi Şoförü"), "picked", [612176]),
    ("wrong face, nothing else: both kept",
     TAXI, disc(faces=["Al Pacino"]), "undecided", [103, 612176]),
    ("contradicting evidence ties: both kept",
     TAXI, disc(faces=["Robert De Niro"], directors=["Şerif Gören"]), "undecided", [103, 612176]),
    ("language outweighed by a face and a director",
     TAXI, disc(faces=["Robert De Niro"], directors=["Martin Scorsese"], original_language="tr"),
     "picked", [103]),
    ("empty discriminators: both kept",
     TAXI, disc(), "no_discriminator", [103, 612176]),
    ("single candidate: check not needed",
     [SCORSESE], disc(faces=["Al Pacino"]), "single", [103]),
    ("no candidate at all",
     [], disc(faces=["Robert De Niro"]), "single", []),
    ("series pair decided by the creator",
     [SERIE_A, SERIE_B], disc(directors=["Juan Ejemplo"]), "picked", [9002]),
    ("The Message: shared director alone cannot decide",
     [MESSAGE_EN, MESSAGE_AR], disc(directors=["Moustapha Akkad"]), "undecided", [26842, 881210]),
    ("The Message, Arabic version: language decides, the face is not in the database",
     [MESSAGE_EN, MESSAGE_AR], disc(faces=["Abdullah Gaith"], directors=["Moustapha Akkad"], original_language="ar"),
     "picked", [881210]),
    ("The Message, English version: Anthony Quinn's face",
     [MESSAGE_EN, MESSAGE_AR], disc(faces=["Anthony Quinn"], directors=["Moustapha Akkad"]), "picked", [26842]),
    ("Leo, animated poster: directors decide among three",
     LEO, disc(directors=["Robert Smigel", "David Wachtenheim"], lead_cast=["Adam Sandler"]), "picked", [1075794]),
    ("Leo, Tamil film with a transliterated title that matches the wrong rows",
     LEO, disc(faces=["Vijay"], directors=["Lokesh Kanagaraj"], original_title="Leo", original_language="ta"),
     "picked", [949229]),
    ("Leo, title and language alone tie the two English rows",
     LEO, disc(original_title="Leo", original_language="en"), "undecided", [949229, 1075794, 1169632]),
    ("face counted once when also given as lead cast",
     TAXI, disc(faces=["Robert De Niro"], lead_cast=["Robert De Niro"]), "picked", [103]),
]


def check_applies():
    """Gate: only one dominant work of type movie or serie opens the identity check."""
    work = {"type": "movie", "value": "Taxi Driver", "year": "1976"}
    rows = [
        ("dominant movie", {"dominant": True, "selected": work}, True),
        ("dominant serie", {"dominant": True, "selected": dict(work, type="serie")}, True),
        ("close candidates, not dominant", {"dominant": False, "selected": work}, False),
        ("dominant person (portrait)", {"dominant": True, "selected": dict(work, type="person")}, False),
        ("nothing selected", {"dominant": True, "selected": None}, False),
    ]
    return [(f"gate: {n}", vi.identity_check_applies(s) == want, f"expected {want}") for n, s, want in rows]


def check_payload_reading():
    """The discriminators are read from the vision payload, known_credits optional."""
    selected = {"type": "movie", "value": "Taxi Driver", "year": "1976",
                "known_credits": {"directors": ["Martin Scorsese"], "lead_cast": ["Robert De Niro"],
                                  "original_title": "Taxi Driver", "original_language": "en"}}
    people = [{"type": "person", "value": "Robert De Niro"}]
    d = vi.discriminators_from_vision(selected, people)
    ok1 = d["faces"] == ["Robert De Niro"] and d["directors"] == ["Martin Scorsese"] and d["original_language"] == "en"
    old = vi.discriminators_from_vision({"type": "movie", "value": "Taxi Driver"}, people)
    ok2 = old["faces"] == ["Robert De Niro"] and old["directors"] == [] and old["original_title"] == ""
    return [("payload: known_credits read", ok1, repr(d)),
            ("payload: old cache entry without known_credits", ok2, repr(old))]


def check_phrase():
    """The credit named in the answer and in a substituted relation question."""
    rows = [
        ("phrase: director first", SCORSESE, disc(faces=["Robert De Niro"], directors=["Martin Scorsese"]),
         "movie", {"en": "directed by Martin Scorsese", "fr": "réalisé par Martin Scorsese"}),
        ("phrase: face when no director matched", SCORSESE, disc(faces=["Robert De Niro"]),
         "movie", {"en": "starring Robert De Niro", "fr": "avec Robert De Niro"}),
        ("phrase: model spelling kept (Serif Goren)", GOREN, disc(directors=["Serif Goren"]),
         "movie", {"en": "directed by Serif Goren", "fr": "réalisé par Serif Goren"}),
        ("phrase: series creator", SERIE_B, disc(directors=["Juan Ejemplo"]),
         "serie", {"en": "created by Juan Ejemplo", "fr": "créée par Juan Ejemplo"}),
        ("phrase: language win names no credit", GOREN, disc(original_language="tr"),
         "movie", {"en": "", "fr": ""}),
        ("phrase: two directors joined", LEO_EN, disc(directors=["Robert Smigel", "David Wachtenheim"]),
         "movie", {"en": "directed by Robert Smigel and David Wachtenheim",
                   "fr": "réalisé par Robert Smigel et David Wachtenheim"}),
    ]
    return [(n, vi.discriminator_phrase(c, d, t) == want, f"got {vi.discriminator_phrase(c, d, t)}")
            for n, c, d, t, want in rows]


def check_composition():
    """compose_vision_question appends the credit to the substituted phrase (text2sql.py).

    The vision block of text2sql.py is read from disk and executed, as eval/verif-114.py does,
    so that the check runs without the API's dependencies.
    """
    import io
    import json
    import re
    src = io.open(os.path.join(RACINE, "text2sql.py"), encoding="utf-8").read()
    space = {"re": re, "json": json}
    start = src.index("def f_build_retry_question_from_reasoning(")
    end = src.index("# FASTAPI-TEXT2SQL-263. The entity-card patterns")
    exec(compile(src[start:end], "text2sql.py", "exec"), space)
    exec(compile(src[src.index("# Vision identification, the sixth LLM task"):], "text2sql.py", "exec"), space)
    payload = {"items": [{"type": "movie", "value": "Taxi Driver", "year": "1976", "confidence": 0.98,
                          "known_credits": {"directors": ["Martin Scorsese"], "lead_cast": [],
                                            "original_title": "", "original_language": "en"}}]}
    suffix = {"en": "directed by Martin Scorsese", "fr": "réalisé par Martin Scorsese"}
    compose = space["compose_vision_question"]
    got_en = compose(payload, "who is the composer of this film?", "en", subject_suffix=suffix)
    got_fr = compose(payload, "qui a composé la musique de ce film ?", "fr", subject_suffix=suffix)
    got_none = compose(payload, "who is the composer of this film?", "en")
    items = space["_normalize_vision_items"](payload)
    return [
        ("compose: suffix in English", "the movie Taxi Driver (1976) directed by Martin Scorsese" in got_en, got_en),
        ("compose: suffix in French", "le film Taxi Driver (1976) réalisé par Martin Scorsese" in got_fr, got_fr),
        ("compose: no suffix, unchanged", "directed by" not in got_none, got_none),
        ("normalize: known_credits kept on a movie", items[0].get("known_credits", {}).get("directors") == ["Martin Scorsese"], repr(items[0])),
    ]


def check_normalization():
    pairs = [("Şerif Gören", "serif goren"), ("Kadir İnanır", "kadir inanir"),
             ("  Robert  De Niro ", "robert de niro"), ("O'Brien", "o brien")]
    return [(f"normalize: {a!r}", vi.normalize_person_name(a) == b,
             f"got {vi.normalize_person_name(a)!r}, expected {b!r}") for a, b in pairs]


def main():
    verbose = "--verbose" in sys.argv
    results = []
    for name, cands, d, want_decision, want_kept in CASES:
        got = vi.pick_vision_identity(cands, d)
        ok = got["decision"] == want_decision and got["kept"] == want_kept
        detail = f"got {got['decision']} {got['kept']}, expected {want_decision} {want_kept}"
        if verbose and got["scores"]:
            detail += " | " + "; ".join(f"{k}: {v['score']} {v['matches']}" for k, v in got["scores"].items())
        results.append((name, ok, detail))
        # Invariant of every case: never an empty result when candidates exist.
        if cands and not got["kept"]:
            results.append((f"{name} (never empty)", False, "kept is empty"))
    results += (check_applies() + check_payload_reading() + check_phrase()
                + check_composition() + check_normalization())

    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        if verbose or not ok:
            print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        else:
            print(f"PASS  {name}")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
