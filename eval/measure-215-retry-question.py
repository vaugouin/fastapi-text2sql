#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mesure FASTAPI-TEXT2SQL-215 : la reprise pose-t-elle la question a laquelle le
modele fort a repondu, ou une autre ?

    uv run eval/measure-215-retry-question.py            # ./logs, fichiers en clair
    uv run eval/measure-215-retry-question.py --archives # + les tarballs mensuels
    uv run eval/measure-215-retry-question.py --examples 10

**Ce qui est mesure, et pourquoi c'est la bonne question.** Le modele fort rend deux
choses : ses premisses (`items`, les entites qu'il a reconnues) et sa conclusion
(`question`, la reponse). `f_build_retry_question_from_reasoning` (`text2sql.py`) calcule
la conclusion dans `base_q` a la ligne 655, puis, des qu'il y a deux elements ou plus, rend
une enumeration des premisses sans jamais la consulter. La branche a un seul element, elle,
defere deja a `base_q`. L'asymetrie n'est donc pas un arbitrage, c'est un oubli.

Le cas qui a declenche cette mesure, le 2026-08-28 sur « Who directed both jaws and the
Indiana jones movie? » :

    modele fort : {"question": "Person Steven Spielberg",
                   "items": [{movie, Jaws, 1975}, {collection, Indiana Jones}]}
    reprise     : "Items Jaws (1975), Indiana Jones"      <- une demande de FILMS
    a l'ecran   : une fiche film, sous une justification disant que Spielberg a realise
                  les deux. Se tromper est un defaut ; se contredire a l'ecran en est un
                  autre, et c'est celui-la que le spectateur voit.

**Ce que ce script ne fait pas.** Il ne corrige rien et n'appelle aucun modele. Il rejoue
la fonction de production telle quelle sur des sorties reellement enregistrees, et la
compare a une variante candidate qui defere a `base_q`. Le comptage est donc un
contrefactuel exact, pas une estimation.

**Ou le lancer.** Sur la machine qui detient les journaux. Sur le poste de developpement il
n'y a qu'un echantillon : au 2026-08-28, 3 fichiers sur 504 portaient une sortie du modele
fort, ce qui ne mesure rien. Le VPS a l'historique et les archives mensuelles.
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import tarfile
from collections import Counter

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import text2sql  # noqa: E402  la fonction de production, importee telle quelle

MARQUE = "Complex question resolution output:"
# Les prefixes que la branche a un seul element sait produire : leur presence en tete de
# `question` signale une reponse typee, par opposition a une phrase libre.
PREFIXES_REPONSE = ("movie ", "person ", "serie ", "topic ")
# Ceux que la branche a deux elements ou plus produit.
RE_ENUMERATION = re.compile(r"^(items|movies|persons|topics|companies|networks|locations|series|\w+s) ", re.I)


def charge_payloads(dossier, avec_archives):
    """Rend (nom du fichier, dict) pour chaque sortie du modele fort trouvee."""
    for chemin in sorted(glob.glob(os.path.join(dossier, "*_text2sql_post_*.json"))):
        try:
            with io.open(chemin, encoding="utf-8") as f:
                yield os.path.basename(chemin), json.load(f)
        except Exception:
            continue
    if not avec_archives:
        return
    for arch in sorted(glob.glob(os.path.join(dossier, "archive", "*.tar.gz"))):
        try:
            with tarfile.open(arch, "r:gz") as t:
                for membre in t:
                    if not membre.isfile() or "_text2sql_post_" not in membre.name:
                        continue
                    try:
                        yield "%s:%s" % (os.path.basename(arch), os.path.basename(membre.name)), \
                            json.load(t.extractfile(membre))
                    except Exception:
                        continue
        except Exception:
            continue


def extrait_sortie(document):
    """Retrouve et decode la sortie JSON du modele fort dans la trace."""
    for message in ((document.get("response") or {}).get("messages") or []):
        texte = (message or {}).get("text") or ""
        if MARQUE not in texte:
            continue
        brut = texte.split(MARQUE, 1)[1].strip()
        for tentative in (brut, brut.replace('\\"', '"').replace("\\n", "\n")):
            try:
                valeur = json.loads(tentative)
                if isinstance(valeur, dict):
                    return valeur
            except Exception:
                continue
        return {}
    return None


def variante_candidate(resolved):
    """Ce que la reprise poserait si elle deferait a la conclusion du modele.

    Une seule regle change : quand `question` est non vide, elle gagne. Le reste de la
    fonction de production est inchange, et c'est volontaire : on mesure l'effet d'un
    correctif minimal, pas d'une refonte.
    """
    if not isinstance(resolved, dict):
        return ""
    base = str(resolved.get("question") or "").strip()
    if base:
        return base
    return text2sql.f_build_retry_question_from_reasoning(resolved)


def classe(resolved, production, candidate):
    """Range un cas dans le seau qui dit quoi en faire."""
    if resolved.get("error"):
        return "ERREUR_DU_MODELE"
    base = str(resolved.get("question") or "").strip()
    if not base:
        return "PAS_DE_REPONSE"
    if production == candidate:
        return "IDENTIQUE"
    if RE_ENUMERATION.match(production or "") and base.lower().startswith(PREFIXES_REPONSE):
        meme_type = production.split(" ", 1)[0].rstrip("s").lower() == base.split(" ", 1)[0].rstrip("s").lower()
        return "ENUMERATION_MEME_TYPE" if meme_type else "ENUMERATION_AUTRE_TYPE"
    return "DIVERGENT_AUTRE"


def main():
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--logs", default=os.path.join(RACINE, "logs"))
    parseur.add_argument("--archives", action="store_true")
    parseur.add_argument("--examples", type=int, default=5)
    args = parseur.parse_args()

    seaux = Counter()
    lus = 0
    avec_reprise = 0
    exemples = {}

    for nom, document in charge_payloads(args.logs, args.archives):
        lus += 1
        resolved = extrait_sortie(document)
        if resolved is None:
            continue
        avec_reprise += 1
        try:
            production = text2sql.f_build_retry_question_from_reasoning(resolved)
        except Exception:
            seaux["ILLISIBLE"] += 1
            continue
        candidate = variante_candidate(resolved)
        seau = classe(resolved, production, candidate)
        seaux[seau] += 1
        exemples.setdefault(seau, []).append((nom, resolved, production, candidate))

    print("Fichiers lus                        : %d" % lus)
    print("Avec une sortie du modele fort      : %d" % avec_reprise)
    if avec_reprise == 0:
        print("\nRien a mesurer ici. Relancer la ou vivent les journaux, avec --archives.")
        return 0

    print()
    LEGENDE = [
        ("ENUMERATION_AUTRE_TYPE", "LE DEFAUT. La reprise demande un autre type que la reponse trouvee"),
        ("ENUMERATION_MEME_TYPE", "Enumeration au lieu de la reponse, mais du bon type. Degrade, pas faux"),
        ("DIVERGENT_AUTRE", "Divergent sans etre une enumeration. A lire un par un"),
        ("IDENTIQUE", "Deferer a la conclusion ne changerait rien"),
        ("PAS_DE_REPONSE", "Le modele n'a pas conclu. Rien a preferer"),
        ("ERREUR_DU_MODELE", "Sortie en erreur ou refusee par le garde-fou JSON"),
        ("ILLISIBLE", "Charge non decodable"),
    ]
    for cle, libelle in LEGENDE:
        if seaux.get(cle):
            part = 100.0 * seaux[cle] / avec_reprise
            print("%-24s %5d  %5.1f %%  %s" % (cle, seaux[cle], part, libelle))

    defaut = seaux.get("ENUMERATION_AUTRE_TYPE", 0) + seaux.get("ENUMERATION_MEME_TYPE", 0)
    print()
    print("Ce que le correctif de -215 changerait : %d reprise(s) sur %d (%.1f %%)"
          % (defaut, avec_reprise, 100.0 * defaut / avec_reprise if avec_reprise else 0.0))

    for cle in ("ENUMERATION_AUTRE_TYPE", "ENUMERATION_MEME_TYPE", "DIVERGENT_AUTRE"):
        for nom, resolved, production, candidate in (exemples.get(cle) or [])[:args.examples]:
            print("\n--- %s  %s" % (cle, nom))
            print("    items      : %s" % json.dumps(resolved.get("items"), ensure_ascii=False)[:160])
            print("    production : %s" % production)
            print("    candidate  : %s" % candidate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
