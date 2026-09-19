#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification du branchement de la famille GPT-6, FASTAPI-TEXT2SQL-274, sans API ni base.

    uv run eval/verif-274.py

Le dispatcher de `_call_chat_llm` est permissif et sans liste blanche : tout ce qui commence
par `gpt-` part chez OpenAI, et les cinq champs `llm_model_*` de `Text2SQLRequest` sont des
`Optional[str]` sans validateur. Passer `gpt-6-astra` partait donc deja tout seul avant ce
ticket, et c'est precisement le defaut : ca partait mal. `_REASONING_MODEL_PREFIXES` ne
connaissait pas la famille, donc Astra recevait `temperature`, que la famille de raisonnement
refuse en 400, et aucun `reasoning_effort`, donc aucun cran reglable ni lisible sur les six
taches.

Les cas ci-dessous verifient les quatre points du correctif, plus les non-regressions des deux
familles deja branchees. Le cas qui compte le plus est celui du plancher : GPT-6 n'a pas de
cran `none`, contrairement a GPT-5.6. Recopier la ligne de GPT-5 aurait rendu un 400 sur les
trois taches du chemin a 100 %, et la corriger en `medium` aurait achete un budget de
raisonnement sur ces memes trois taches sans que personne le demande.

Le code teste est lu sur le disque et non importe : `text2sql.py` tire pandas, psutil, openai,
dotenv et `data_watcher`, dont aucun n'est necessaire ici, et qui rendraient cette verification
impossible a lancer sur un poste sans la pile complete. Meme geste que `verif-225-226-227.py`.
"""
import io
import os
import sys
from typing import Optional

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(RACINE, "text2sql.py")

src = io.open(SOURCE, encoding="utf-8").read()
debut = src.index("# --- OpenAI reasoning-model sampling rules")
fin = src.index("def _call_chat_llm(")

espace = {"Optional": Optional}
exec(compile(src[debut:fin], SOURCE, "exec"), espace)

est_raisonnement = espace["_is_openai_reasoning_model"]
resout_cran = espace["_resolve_reasoning_effort"]
kwargs_openai = espace["_openai_sampling_kwargs"]
kwargs_responses = espace["_as_responses_api_kwargs"]
passe_par_responses = espace["_uses_openai_responses_api"]
CRANS_PAR_FAMILLE = espace["_EFFORT_BY_FAMILY"]
CRAN_PAR_TACHE = espace["_DEFAULT_EFFORT_TIER"]

# Les cinq crans documentes de la famille GPT-6, le moins cher etant `low`. Pas de `none`.
CRANS_GPT6 = ("low", "medium", "high", "xhigh", "max")

# Les six taches du pipeline, la sixieme etant celle de -114, declaree d'avance.
TACHES = ("entity_extraction", "text2sql", "result_entity",
          "complex_question", "answer_single_value", "vision_identification")


def cas_sampling():
    """Ce que chaque modele recoit comme moitie d'echantillonnage, par famille."""
    return [
        # (modele, tache, kwargs attendus, pourquoi)
        ("gpt-6-astra", "text2sql", {"reasoning_effort": "low"},
         "LE CAS DE -274 : Astra part avec un cran explicite et SANS temperature"),
        ("gpt-6-astra", "complex_question", {"reasoning_effort": "medium"},
         "la reprise complexe, qui tire sur ~1 % des requetes, a le droit de depenser"),
        ("gpt-6-astra", "vision_identification", {"reasoning_effort": "low"},
         "la sixieme tache de -114 demarre au plancher, on ne monte que sur le banc"),
        ("gpt-4o", "text2sql", {"temperature": 0},
         "NON-REGRESSION : la ligne 4.x garde temperature, comportement octet pour octet"),
        ("gpt-5.6-terra", "text2sql", {"reasoning_effort": "none"},
         "NON-REGRESSION : GPT-5.6 garde son `none`, qui ne depense aucun jeton"),
        ("o3-mini", "text2sql", {"reasoning_effort": "low"},
         "NON-REGRESSION : la serie o n'a pas de `none`, son plancher reste `low`"),
    ]


def cas_route():
    """Quel endpoint sert quel modele. Tranche par -274, plus par heritage."""
    return [
        # (modele, passe par responses.create ?, pourquoi)
        ("gpt-6-astra", False,
         "LA DECISION DE -274 : Astra accepte les deux, on prend chat.completions"),
        ("gpt-5.6-terra", False, "GPT-5.x, la ou la comptabilite de cache a ete mesuree"),
        ("GPT-5.6-TERRA", False,
         "GARDE-FOU : la casse ne doit plus decider de la route (defaut d'avant -274)"),
        ("o3-mini", True, "la serie o garde l'API Responses, seul endroit ou elle a tourne"),
        ("gpt-4o", False, "un modele sans raisonnement ne prend jamais cette branche"),
    ]


def main():
    """Joue la batterie et rend 0 si tout est conforme."""
    succes = 0
    total = 0

    print("-- Le modele est-il reconnu comme modele de raisonnement ?")
    for modele, attendu in [("gpt-6-astra", True), ("gpt-6", True), ("gpt-5.6-luna", True),
                            ("o4-mini", True), ("gpt-4o", False), ("claude-sonnet-4", False)]:
        total += 1
        obtenu = est_raisonnement(modele)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-16s raisonnement=%-5s attendu=%-5s"
              % ("OK   " if conforme else "ECHEC", modele, obtenu, attendu))

    print()
    print("-- Moitie d'echantillonnage de l'appel OpenAI")
    for modele, tache, attendu, pourquoi in cas_sampling():
        total += 1
        obtenu = kwargs_openai(modele, 0, tache)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-14s %-22s %-32s %s"
              % ("OK   " if conforme else "ECHEC", modele, tache, obtenu, pourquoi))

    print()
    print("-- Les six taches ont un cran declare, et il est dans le vocabulaire de GPT-6")
    for tache in TACHES:
        total += 1
        declaree = tache in CRAN_PAR_TACHE
        cran = resout_cran("gpt-6-astra", tache)
        conforme = declaree and cran in CRANS_GPT6
        succes += conforme
        print("%s  %-22s cran=%-8s declaree=%s"
              % ("OK   " if conforme else "ECHEC", tache, cran, declaree))

    print()
    print("-- Le plancher de GPT-6 : pas de `none`, sinon 400 sur le chemin a 100 %")
    total += 1
    crans_gpt6 = set(CRANS_PAR_FAMILLE["gpt-6"].values())
    conforme = "none" not in crans_gpt6 and crans_gpt6 <= set(CRANS_GPT6)
    succes += conforme
    print("%s  crans servis=%s, aucun hors vocabulaire, aucun `none`"
          % ("OK   " if conforme else "ECHEC", sorted(crans_gpt6)))

    total += 1
    conforme = CRANS_PAR_FAMILLE["gpt-6"]["cheapest"] == "low"
    succes += conforme
    print("%s  le moins cher de GPT-6 est `low` (et non `none`, recopie de GPT-5.6)"
          % ("OK   " if conforme else "ECHEC"))

    print()
    print("-- Quel endpoint sert le modele")
    for modele, attendu, pourquoi in cas_route():
        total += 1
        obtenu = passe_par_responses(modele)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-14s responses=%-5s attendu=%-5s  %s"
              % ("OK   " if conforme else "ECHEC", modele, obtenu, attendu, pourquoi))

    print()
    print("-- Traduction des kwargs pour l'API Responses (le cran y a un autre nom)")
    for entree, attendu, pourquoi in [
        ({"reasoning_effort": "low"}, {"reasoning": {"effort": "low"}},
         "`reasoning_effort` a plat est refuse par responses.create"),
        ({"temperature": 0}, {"temperature": 0}, "ce qui n'est pas un cran ne bouge pas"),
        ({}, {}, "l'absence de cran reste une absence"),
    ]:
        total += 1
        obtenu = kwargs_responses(entree)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-28s -> %-30s %s"
              % ("OK   " if conforme else "ECHEC", entree, obtenu, pourquoi))

    print()
    print("-- Une tache inconnue degrade au moins cher, elle ne leve pas en pleine requete")
    for modele, attendu in [("gpt-6-astra", "low"), ("gpt-5.6-terra", "none"), ("o3", "low")]:
        total += 1
        try:
            obtenu = resout_cran(modele, "tache_qui_n_existe_pas")
        except Exception as erreur:
            obtenu = "LEVE %s" % type(erreur).__name__
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-14s cran=%-8s attendu=%s"
              % ("OK   " if conforme else "ECHEC", modele, obtenu, attendu))

    print()
    print("%d/%d" % (succes, total))
    return 0 if succes == total else 1


if __name__ == "__main__":
    sys.exit(main())
