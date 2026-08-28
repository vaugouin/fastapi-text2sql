# -*- coding: utf-8 -*-
"""Verification des deux garde-fous de resolution non latine, sans base ni API.

    uv run eval/verif-225-226.py

FASTAPI-TEXT2SQL-225 : `fold_for_exactness`, le repliement typographique branche sur le
test d'exactitude et sur lui seul.
FASTAPI-TEXT2SQL-226 : `is_unmatchable_against_canonical`, qui dit si un repli brut peut
encore esperer trouver une ligne.
FASTAPI-TEXT2SQL-227 : `resolution_key`, qui neutralise en plus les descripteurs generiques
que la strategie declare, pour que le garde juge les memes chaines que sa propre recherche.

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
sys.path.insert(0, RACINE)  # lance depuis eval/, la racine n'est pas sur le chemin
import rapidfuzz_query

espace = {"re": re, "unicodedata": unicodedata, "rapidfuzz_query": rapidfuzz_query}
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
fold = espace["fold_for_exactness"]
unmatchable = espace["is_unmatchable_against_canonical"]
cle = espace["resolution_key"]

# La strategie reelle de Collection_name, telle que entity_resolution.json la declare.
CFG_COLLECTION = {"score_stopwords": ["collection", "saga", "trilogy", "universe"]}
# Une strategie qui ne declare rien : elle doit garder exactement son comportement.
CFG_NEUTRE = {}

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

CAS_CLE = [
    ("indiana jones", "indiana jones collection", CFG_COLLECTION, True,
     "LE CAS DU 2026-08-28, refuse a 70,27 pour un seuil de 72"),
    ("star wars", "star wars collection", CFG_COLLECTION, True, "meme forme, suffixe generique"),
    ("indiana jones", "the young indiana jones collection", CFG_COLLECTION, False,
     "le candidat que les embeddings avaient prefere, doit rester refuse"),
    ("alien", "predator collection", CFG_COLLECTION, False, "deux franchises distinctes"),
    ("indiana jones", "indiana jones collection", CFG_NEUTRE, False,
     "NON-REGRESSION : une strategie qui ne declare rien ne depouille rien"),
    ("collection", "star wars collection", CFG_COLLECTION, False,
     "garde-fou : depouiller ne doit pas vider la chaine cherchee"),
    ("\u9ed1\u6fa4\u660e", "\u9ed1\u6fa4\u6e05", CFG_COLLECTION, False,
     "CONTRE-EXEMPLE Kurosawa, le depouillement ne le fusionne pas davantage"),
]

def joue_cle():
    """La cle -227, et la monotonie qu'elle doit respecter vis-a-vis de -225."""
    print("--- resolution_key (FASTAPI-TEXT2SQL-227)")
    succes = 0
    for a, b, cfg, attendu, pourquoi in CAS_CLE:
        obtenu = cle(a, cfg) == cle(b, cfg)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  obtenu=%-5s attendu=%-5s  %s" % ("OK   " if conforme else "ECHEC", obtenu, attendu, pourquoi))

    # Monotonie : tout ce que -225 declarait egal doit le rester avec -227, sinon le
    # nouveau garde serait plus severe que l'ancien sur des cas deja acquis.
    manquements = [p for a, b, att, p in CAS_FOLD
                   if fold(a) == fold(b) and cle(a, CFG_COLLECTION) != cle(b, CFG_COLLECTION)]
    conforme = not manquements
    succes += conforme
    print("%s  monotonie vis-a-vis de -225 : %s" % (
        "OK   " if conforme else "ECHEC", "aucun cas perdu" if conforme else manquements))
    print()
    return succes

total = len(CAS_FOLD) + len(CAS_UNMATCHABLE) + len(CAS_CLE) + 1
ok = joue("fold_for_exactness (FASTAPI-TEXT2SQL-225)", CAS_FOLD, fold, True)
ok += joue("is_unmatchable_against_canonical (FASTAPI-TEXT2SQL-226)", CAS_UNMATCHABLE, unmatchable, False)
ok += joue_cle()

print("%d/%d" % (ok, total))
sys.exit(0 if ok == total else 1)
