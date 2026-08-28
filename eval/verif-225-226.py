# -*- coding: utf-8 -*-
"""Verification des deux garde-fous de resolution non latine, sans base ni API.

    uv run eval/verif-225-226.py

FASTAPI-TEXT2SQL-225 : `fold_for_exactness`, le repliement typographique branche sur le
test d'exactitude et sur lui seul.
FASTAPI-TEXT2SQL-226 : `is_unmatchable_against_canonical`, qui dit si un repli brut peut
encore esperer trouver une ligne.

Le code teste est lu sur le disque et non importe : `entity.py` tire rapidfuzz, chromadb et
une connexion, dont aucune n'est necessaire ici, et qui rendraient cette verification
impossible a lancer sur un poste sans la pile complete.

Le cas qui compte le plus est celui qui doit ECHOUER a fusionner : 黑澤明 (Akira Kurosawa)
et 黑澤清 (Kiyoshi Kurosawa) different d'un caractere, sont tous deux realisateurs et tous
deux en base. C'est la raison pour laquelle -225 replie sans jamais assouplir le score.
"""
import io
import os
import re
import sys
import unicodedata

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(RACINE, "entity.py")

src = io.open(SOURCE, encoding="utf-8").read()
debut = src.index('_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")')
fin = src.index("def _substitute_literal(")
espace = {"re": re, "unicodedata": unicodedata}
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
fold = espace["fold_for_exactness"]
unmatchable = espace["is_unmatchable_against_canonical"]

CAS_FOLD = [
    ("宮崎 駿", "宮崎駿", True, "espace interne dans un nom Han, Miyazaki"),
    ("ＡＫＩＲＡ", "akira", True, "pleine chasse vers demi-chasse"),
    ("Akira Kurosawa", "akira kurosawa", True, "casse et espaces de bord"),
    ("박찬욱", "박찬욱", True, "identite hangul"),
    ("黒澤明", "黑澤明", False, "shinjitai contre traditionnel, hors perimetre, assume"),
    ("张艺谋", "張藝謀", False, "simplifie contre traditionnel, hors perimetre, assume"),
    ("宮﨑駿", "宮崎駿", False, "U+FA11 n'a pas de decomposition NFKC, mesure et non suppose"),
    ("黑澤明", "黑澤清", False, "CONTRE-EXEMPLE Kurosawa Akira contre Kiyoshi, ne doit jamais fusionner"),
    ("akira kurosawa", "akirakurosawa", False, "un nom latin garde ses espaces"),
]

CAS_UNMATCHABLE = [
    ("黒澤明", True, "Han pur"),
    ("박찬욱", True, "hangul pur"),
    ("チャップリン", True, "katakana pur"),
    ("Пон Чжун Хо", True, "cyrillique pur"),
    ("Akira Kurosawa", False, "latin"),
    ("Arnol Swartzeneger", False, "latin fautif, garde son repli brut"),
    ("Se7en", False, "latin et chiffre"),
    ("宮崎 Hayao", False, "mixte, une lettre latine suffit"),
    ("", False, "vide"),
]

def joue(titre, cas, fonction, deux_arguments):
    """Joue une batterie de cas et rend le nombre de succes."""
    print("--- %s" % titre)
    succes = 0
    for entree in cas:
        attendu, pourquoi = entree[-2], entree[-1]
        obtenu = fonction(entree[0]) == fonction(entree[1]) if deux_arguments else fonction(entree[0])
        conforme = obtenu == attendu
        succes += conforme
        print("%s  obtenu=%-5s attendu=%-5s  %s" % ("OK   " if conforme else "ECHEC", obtenu, attendu, pourquoi))
    print()
    return succes

total = len(CAS_FOLD) + len(CAS_UNMATCHABLE)
ok = joue("fold_for_exactness (FASTAPI-TEXT2SQL-225)", CAS_FOLD, fold, True)
ok += joue("is_unmatchable_against_canonical (FASTAPI-TEXT2SQL-226)", CAS_UNMATCHABLE, unmatchable, False)

print("%d/%d" % (ok, total))
sys.exit(0 if ok == total else 1)
