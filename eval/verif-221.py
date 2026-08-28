#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification du garde-fou de FASTAPI-TEXT2SQL-221, sans base ni API.

    uv run eval/verif-221.py

Le prompt demandait au modele de dire quelque chose en se taisant : une "question" vide,
des "items" vides et une "error" vide signifiaient « la base a repondu, son resultat vide
fait autorite ». Or `any_of_required` refuse cette forme par construction, si bien que
chaque application correcte de la regle etait enregistree comme sortie malformee.

Mesure du 2026-08-28 sur 18 097 appels : 13 des 17 reprises complexes de la version en
service, 1.1.18, mouraient la, et cette version n'a produit aucune conclusion utilisable.
Aucune occurrence en 1.1.15 ni en 1.1.16, ce qui date le defaut de la regle de prompt
ajoutee le 2026-07-12.

Le correctif donne un champ a cette reponse, `authoritative_empty`, plutot que d'assouplir
le garde-fou. Assouplir aurait admis une sortie reellement vide, indiscernable d'une panne
du modele, ce que le garde-fou de -038 existe precisement pour attraper.
"""
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import json_guardrails  # noqa: E402

CAS = [
    # (charge, doit passer ?, pourquoi)
    ({"question": "", "items": [], "justification": "The database result is authoritative.",
      "error": "", "authoritative_empty": True},
     True, "LE CAS DE -221 : le vide autoritaire, desormais accepte"),

    ({"question": "", "items": [], "justification": "The database result is authoritative.",
      "error": ""},
     False, "l'ancienne forme, trois champs vides, reste refusee"),

    ({"question": "", "items": [], "justification": "", "error": "", "authoritative_empty": False},
     False, "GARDE-FOU : un booleen faux ne doit pas satisfaire any_of_required"),

    ({"question": "Person Steven Spielberg", "items": [], "justification": "", "error": ""},
     True, "une conclusion normale passe, comme avant"),

    ({"question": "", "items": [], "justification": "", "error": "Please clarify the request."},
     True, "une erreur declaree passe, comme avant"),

    ({"question": "", "items": [], "justification": "", "error": ""},
     False, "NON-REGRESSION : une sortie reellement vide reste refusee, c'est tout -038"),

    ({"question": "Movies", "items": [], "error": "", "authoritative_empty": "oui"},
     False, "le champ doit etre un booleen, pas une chaine"),

    ({"question": "", "error": "", "authoritative_empty": True, "justification": 42},
     False, "les autres types restent controles"),
]


def main():
    """Joue la batterie et rend 0 si tout est conforme."""
    succes = 0
    for charge, attendu, pourquoi in CAS:
        obtenu, message = json_guardrails.validate_llm_json(charge, "complex_question")
        conforme = obtenu == attendu
        succes += conforme
        detail = "" if obtenu else "  (%s)" % message[:70]
        print("%s  passe=%-5s attendu=%-5s  %s%s"
              % ("OK   " if conforme else "ECHEC", obtenu, attendu, pourquoi, detail))
    print()
    print("%d/%d" % (succes, len(CAS)))
    return 0 if succes == len(CAS) else 1


if __name__ == "__main__":
    sys.exit(main())
