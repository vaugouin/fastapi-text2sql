#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification du parcours vision, FASTAPI-TEXT2SQL-114, sans API, sans base et sans image.

    uv run eval/verif-114.py

Ce que ce fichier couvre : tout ce qui, dans le chemin image, est DETERMINISTE. C'est-a-dire
l'essentiel de ce qui peut casser en silence, puisque l'appel au modele, lui, echoue bruyamment.

Quatre pieces, et chacune a une raison d'etre verifiee ici plutot que sur le banc de vingt
images (qui, lui, mesure la reconnaissance, ce qu'aucun test hors ligne ne saurait faire).

1. **La composition de la question.** C'est elle qui decide si une photo accompagnee de
   "qui a realise ca ?" repond a la question ou rend la fiche nue du film, defaut
   FASTAPI-TEXT2SQL-263 deja paye une fois sur le chemin du complex mode. C'est elle aussi
   qui rend la pagination gratuite : le hachage porte sur la question composee, donc la page 2
   d'une recherche nee d'une image n'est une requete ordinaire QUE SI l'identification rangee
   en cache compose la MEME question que celle qui sort du modele. Un test le verifie en
   faisant passer la charge utile par la mise en cache avant de composer.
2. **L'aiguillage de confiance.** Le seuil est provisoire et sera mesure, mais la REGLE qui
   l'utilise ne doit pas bouger : un candidat qui domine ouvre sa fiche, des candidats proches
   sont tous presentes (regle VOICE-AGENT-093).
3. **Le contrat de cache.** Ce qui est stocke doit etre independant de la question, sans quoi
   la meme photo servirait demain la reponse d'aujourd'hui a une autre question.
4. **Le contrat d'entree et de sortie**, lu sur les modeles Pydantic eux-memes : une image
   seule ne doit pas partir en 422, et les cinq champs de reponse doivent etre neutres pour un
   client qui ne sait rien de l'image. C'est ce dont dependent les deux moities front.

Le code teste est lu sur le disque et non importe, meme geste que verif-274.py : text2sql.py
tire pandas, psutil, openai, dotenv et data_watcher, dont aucun n'est necessaire ici et qui
rendraient cette verification impossible a lancer sur un poste sans la pile complete. Les trois
autres modules touches (json_guardrails, vision_cache, uploads) n'ont pas ce probleme et sont
importes normalement.
"""
import hashlib
import io
import json
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(RACINE, "text2sql.py")
sys.path.insert(0, RACINE)

import json_guardrails  # noqa: E402
import uploads  # noqa: E402
import vision_cache  # noqa: E402

src = io.open(SOURCE, encoding="utf-8").read()

espace = {"re": re, "json": json}
# Le composeur de question canonique, partage avec le chemin de rattrapage.
debut = src.index("def f_build_retry_question_from_reasoning(")
fin = src.index("# FASTAPI-TEXT2SQL-263. The entity-card patterns")
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
# Puis tout le bloc vision, qui va de son titre a la fin du fichier.
debut = src.index("# Vision identification, the sixth LLM task")
exec(compile(src[debut:], SOURCE, "exec"), espace)

question_sur_image = espace["question_targets_the_image"]
choisit = espace["select_vision_candidates"]
compose = espace["compose_vision_question"]
phrase_entite = espace["vision_entity_phrase"]
SEUIL = espace["VISION_CONFIDENCE_DOMINANT"]
MARGE = espace["VISION_CONFIDENCE_MARGIN"]
MAX_CANDIDATS = espace["VISION_MAX_CANDIDATES"]


def item(valeur, type_="movie", annee="", confiance=0.9):
    return {"type": type_, "value": valeur, "year": annee,
            "confidence": confiance, "note": "", "evidence": []}


def payload(*items, **reste):
    p = {"hints": {"kind": "poster"}, "items": list(items),
         "about_image": False, "image_answer": "",
         "authoritative_empty": False, "justification": "", "error": ""}
    p.update(reste)
    return p


BLADE = item("Blade Runner", "movie", "1982", 0.94)


def cas_aiguillage_image():
    """Une question qui porte sur les pixels contre une question qui porte sur l'oeuvre.

    Se tromper ici ne rend jamais une mauvaise reponse : la liste est une porte "peut-etre",
    et le modele tranche ensuite par `about_image`. Se tromper coute un tour de cache.
    """
    return [
        ("", False, "pas de question, la photo est seule"),
        ("who directed this film?", False, "porte sur l'oeuvre, le catalogue repond"),
        ("what else is she in?", False, "porte sur la filmographie"),
        ("qui a realise ce film ?", False, "idem en francais"),
        ("cast", False, "un mot, sur l'oeuvre"),
        ("what is written on this poster?", True, "porte sur les pixels"),
        ("qu'est-ce qui est ecrit sur cette affiche ?", True, "idem en francais"),
        ("which edition of this blu-ray is it?", True, "l'edition n'est pas au catalogue"),
        ("quelle est la couleur de sa robe ?", True, "la couleur n'est pas au catalogue"),
        ("de quelle annee est ce film ?", False,
         "porte sur les pixels en apparence, sur l'oeuvre en verite : le catalogue repond"),
    ]


def cas_confiance():
    """Un candidat domine, ou les candidats sont proches. La regle, pas le seuil."""
    return [
        ([], False, None, "aucun candidat, rien a selectionner"),
        ([item("A", confiance=0.4)], True, "A",
         "un seul candidat domine par construction, si bas soit-il"),
        ([item("A", confiance=0.94), item("B", confiance=0.20)], True, "A",
         "ecart net, la fiche s'ouvre et l'alternative est signalee"),
        ([item("A", confiance=0.55), item("B", confiance=0.45)], False, "A",
         "candidats proches, ils sont tous presentes"),
        ([item("A", confiance=0.90), item("B", confiance=0.75)], False, "A",
         "au-dessus du seuil mais sous la marge, donc proches"),
        ([item("B", confiance=0.30), item("A", confiance=0.90)], True, "A",
         "le classement suit la confiance, pas l'ordre d'arrivee"),
    ]


def charge_modeles_pydantic():
    """Rendre (Text2SQLRequest, Text2SQLResponse), lus sur main.py, ou None.

    Meme geste que pour text2sql.py, pour une raison plus forte encore : main.py ouvre
    ChromaDB et la base des son import. Seul le bloc des modeles est execute.
    """
    try:
        from pydantic import BaseModel, field_validator, model_validator
    except Exception:
        return None
    from typing import List, Optional
    source = os.path.join(RACINE, "main.py")
    texte = io.open(source, encoding="utf-8").read()
    debut = texte.index("class TextExpr(BaseModel):")
    fin = texte.index("class ResultItem(BaseModel):")

    def normalise_langue(v):
        code = str(v or "en").strip().lower().split("-")[0]
        return code if code in ("en", "fr") else "en"

    espace_modeles = {"BaseModel": BaseModel, "field_validator": field_validator,
                      "model_validator": model_validator, "Optional": Optional,
                      "List": List, "normalize_ui_language": normalise_langue}
    exec(compile(texte[debut:fin], source, "exec"), espace_modeles)
    return espace_modeles["Text2SQLRequest"], espace_modeles["Text2SQLResponse"]


def main():
    succes = 0
    total = 0

    print("== FASTAPI-TEXT2SQL-114, le parcours vision hors ligne ==")
    print()
    print("-- La question porte-t-elle sur l'image elle-meme ?")
    for question, attendu, pourquoi in cas_aiguillage_image():
        total += 1
        obtenu = question_sur_image(question)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-45s %-5s  %s" % ("OK   " if conforme else "ECHEC",
                                      (question or "(vide)")[:45], obtenu, pourquoi))

    print()
    print("-- Departager deux candidats (seuil %.2f, marge %.2f, tous deux PROVISOIRES)"
          % (SEUIL, MARGE))
    for items, domine_attendu, valeur_attendue, pourquoi in cas_confiance():
        total += 1
        choix = choisit(payload(*items))
        valeur = choix["selected"]["value"] if choix["selected"] else None
        conforme = choix["dominant"] == domine_attendu and valeur == valeur_attendue
        succes += conforme
        print("%s  domine=%-5s selection=%-5s  %s" % ("OK   " if conforme else "ECHEC",
                                                      choix["dominant"], valeur, pourquoi))

    total += 1
    trop = [item("C%d" % i, confiance=0.5) for i in range(9)]
    obtenu = len(choisit(payload(*trop))["ranked"])
    conforme = obtenu == MAX_CANDIDATS
    succes += conforme
    print("%s  %d candidats rendus sur 9 proposes, plafond %d"
          % ("OK   " if conforme else "ECHEC", obtenu, MAX_CANDIDATS))

    total += 1
    sale = [{"type": "film", "value": "  A  ", "year": "82", "confidence": "haute"},
            {"type": "movie", "value": ""}, "pas un dict"]
    propre = choisit(payload(*sale))["ranked"]
    conforme = (len(propre) == 1 and propre[0]["value"] == "A" and propre[0]["year"] == ""
                and propre[0]["type"] == "other" and propre[0]["confidence"] == 0.0)
    succes += conforme
    print("%s  une charge utile sale est nettoyee sans lever (type inconnu, annee a 2 chiffres,"
          " confiance en toutes lettres)" % ("OK   " if conforme else "ECHEC"))

    print()
    print("-- Composer la question, photo seule")
    for items, attendu, pourquoi in [
        ([BLADE], "Movie Blade Runner released in 1982",
         "la question canonique, composee par le meme code que le rattrapage"),
        ([item("Harrison Ford", "person", "", 0.9)], "Person Harrison Ford",
         "une personne, sans annee"),
        ([item("Star Wars", "collection", "", 0.9)], "Star Wars",
         "une collection, jamais enumeree en titres"),
        ([item("A", "movie", "1931", 0.55), item("B", "movie", "1992", 0.45)],
         "Movies A (1931), B (1992)",
         "candidats proches : tous cherches, le client demandera lequel"),
        ([], "", "rien d'identifie, la composition rend le vide et rien n'est cherche"),
    ]:
        total += 1
        obtenu = compose(payload(*items), "")
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-40s %s" % ("OK   " if conforme else "ECHEC", obtenu[:40], pourquoi))

    print()
    print("-- Composer la question, photo accompagnee d'une question (defaut -263)")
    for question, langue, attendu, pourquoi in [
        ("who directed this film?", "en", "who directed the movie Blade Runner (1982)?",
         "la question GARDE sa forme, l'entite y est substituee"),
        ("who directed this?", "en", "who directed the movie Blade Runner (1982)?",
         "le pronom seul en fin de phrase compte comme une designation"),
        ("what else is in this movie?", "en",
         "what else is in the movie Blade Runner (1982)?", "autre demonstratif"),
        ("qui a realise ce film ?", "fr", "qui a realise le film Blade Runner (1982) ?",
         "en francais, la phrase injectee est francaise"),
        ("cast", "en", "cast (the image shows the movie Blade Runner (1982))",
         "aucun demonstratif a remplacer : le sujet est nomme a cote, rien n'est retire"),
        ("casting", "fr", "casting (l'image montre le film Blade Runner (1982))",
         "idem en francais"),
    ]:
        total += 1
        obtenu = compose(payload(BLADE), question, langue)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-58s %s" % ("OK   " if conforme else "ECHEC", obtenu[:58], pourquoi))

    total += 1
    obtenu = compose(payload(BLADE), "who directed this film?")
    conforme = "Movie Blade Runner" not in obtenu and obtenu.endswith("?")
    succes += conforme
    print("%s  une question de relation n'est JAMAIS aplatie en fiche nue"
          % ("OK   " if conforme else "ECHEC"))

    print()
    print("-- La composition survit au cache, et c'est ce qui rend la page 2 ordinaire")
    # L'invariant qui compte n'est pas "deux identifications differentes donnent la meme
    # question", il est "l'identification RANGEE EN CACHE donne la meme question que celle qui
    # sort du modele". Sans lui, la page 2 d'une recherche nee d'une image, servie depuis le
    # cache de reconnaissance, composerait une autre question, donc un autre hachage, donc un
    # defaut de cache SQL et un second passage complet du pipeline.
    for items, question in [([BLADE], ""), ([BLADE], "who directed this film?"),
                            ([item("A", confiance=0.5), item("B", confiance=0.5)], ""),
                            ([item("A", confiance=0.9), item("B", confiance=0.2)], "")]:
        total += 1
        frais = payload(*items)
        range_en_cache = json.loads(json.dumps(vision_cache.identification_payload(frais)))
        premiere = compose(frais, question)
        seconde = compose(range_en_cache, question)
        conforme = premiere == seconde and premiere != ""
        succes += conforme
        print("%s  modele et cache composent la meme question : %s"
              % ("OK   " if conforme else "ECHEC", premiere[:50]))

    print()
    print("-- Le garde-fou JSON de la sixieme tache")
    for charge, attendu, pourquoi in [
        ({}, False, "une charge vide n'est pas une identification"),
        ({"items": []}, False,
         "zero candidat SANS le dire est un echec, lecon de -221 sur le complex mode"),
        ({"items": [], "authoritative_empty": True}, True,
         "zero candidat AFFIRME est une reponse valide"),
        ({"items": [{"type": "movie", "value": "X"}]}, True, "un candidat suffit"),
        ({"image_answer": "the tagline reads ..."}, True,
         "une reponse sur les pixels suffit aussi"),
        ({"error": "no image reached the model"}, True, "une erreur declaree est valide"),
        ({"items": "Blade Runner"}, False, "items doit etre une liste"),
        ({"items": [{"value": "X"}], "about_image": "yes"}, False,
         "about_image doit etre un booleen"),
    ]:
        total += 1
        obtenu, message = json_guardrails.validate_llm_json(charge, "vision_identification")
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-5s %-42s %s" % ("OK   " if conforme else "ECHEC", obtenu,
                                     message[:42] or "(accepte)", pourquoi))

    print()
    print("-- Le cache ne garde que ce qui ne depend pas de la question")
    complet = payload(BLADE, about_image=True, image_answer="the tagline reads MORE HUMAN",
                      justification="poster, credits block readable")
    garde = vision_cache.identification_payload(complet)
    for cle, present, pourquoi in [
        ("items", True, "l'identification depend de l'image seule"),
        ("hints", True, "les indices aussi"),
        ("justification", True, "le diagnostic est ecrit en anglais et se garde"),
        ("authoritative_empty", True, "l'affirmation du vide se cache, contrairement a #8b"),
        ("about_image", False, "depend de ce que l'utilisateur a demande CE tour-ci"),
        ("image_answer", False, "depend de la question, donc jamais servi a une autre"),
    ]:
        total += 1
        conforme = (cle in garde) == present
        succes += conforme
        print("%s  %-20s %-9s %s" % ("OK   " if conforme else "ECHEC", cle,
                                     "garde" if present else "jete", pourquoi))

    for charge, attendu, pourquoi in [
        ({"items": [{"value": "X"}]}, True, "une identification se garde"),
        ({"items": [], "authoritative_empty": True}, True,
         "une photo hors cinema se garde : elle le restera demain"),
        ({"items": []}, False, "rien a garder"),
        ({"items": [{"value": "X"}], "error": "boom"}, False,
         "une erreur ne se fige jamais, le tour suivant doit avoir sa chance"),
    ]:
        total += 1
        obtenu = vision_cache.is_cacheable(charge)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  cacheable=%-5s  %s" % ("OK   " if conforme else "ECHEC", obtenu, pourquoi))

    print()
    print("-- Le contrat d'entree et de sortie, lu sur les modeles Pydantic de main.py")
    # Les deux moities front (TMDB-FRONT-088, VOICE-AGENT-158) dependent de trois choses
    # exactement : qu'une image seule ne parte pas en 422, que les champs vision existent dans
    # la reponse, et qu'ils aient des valeurs neutres pour un client qui ignore l'image. Les
    # classes sont lues sur le disque et executees a part, main.py entier n'etant pas
    # importable hors de la pile complete (chromadb, base de donnees, cles d'API).
    modeles = charge_modeles_pydantic()
    if modeles is None:
        print("SKIP   pydantic absent : les %d verifications de contrat n'ont pas tourne, "
              "elles ne sont pas comptees comme reussies" % 4)
    else:
        Requete, Reponse = modeles
        ref = "20260920-084157_vision_1.1.19_%s.jpg" % ("a" * 32)

        total += 1
        try:
            r = Requete(image_ref=ref)
            conforme = r.question is None and r.llm_model_vision == "default"
        except Exception:
            conforme = False
        succes += conforme
        print("%s  une image SEULE, sans question ni hachage, est acceptee (sinon 422 avant "
              "toute ligne de code)" % ("OK   " if conforme else "ECHEC"))

        total += 1
        try:
            Requete()
            conforme = False
        except Exception:
            conforme = True
        succes += conforme
        print("%s  une requete vide reste refusee : le champ image_ref ouvre une troisieme "
              "porte, il n'en ouvre pas une quatrieme" % ("OK   " if conforme else "ECHEC"))

        base = dict(question="x", sql_query="", justification="", error="",
                    entity_extraction_processing_time=0.0, text2sql_processing_time=0.0,
                    embeddings_processing_time=0.0, query_execution_time=0.0,
                    total_processing_time=0.0, llm_model_entity_extraction="gpt-4o",
                    llm_model_text2sql="gpt-4o", llm_model_complex="gpt-4o",
                    api_version="1.1.19")

        total += 1
        nue = Reponse(**base).model_dump()
        conforme = (nue["image_ref"] == "" and nue["vision_evidence"] is None
                    and nue["vision_model_used"] is False
                    and nue["vision_identification_processing_time"] == 0.0
                    and nue["llm_model_vision"] == "")
        succes += conforme
        print("%s  une reponse sans image porte les cinq champs a leur valeur neutre : un "
              "client qui ignore l'image ne voit rien changer" % ("OK   " if conforme else "ECHEC"))

        total += 1
        pleine = Reponse(vision_identification_processing_time=2.3, vision_model_used=True,
                         image_ref=ref, llm_model_vision="gpt-6-astra",
                         vision_evidence={"candidates": [], "cached": False},
                         **base).model_dump()
        conforme = (pleine["vision_model_used"] is True and pleine["image_ref"] == ref
                    and pleine["vision_evidence"]["cached"] is False
                    and pleine["llm_model_vision"] == "gpt-6-astra")
        succes += conforme
        print("%s  et une reponse vision les porte tous les cinq"
              % ("OK   " if conforme else "ECHEC"))

    print()
    print("-- La cle du cache est bien l'empreinte des octets, et elle est deja dans le nom")
    octets = b"\xff\xd8\xff" + b"des pixels" * 10
    empreinte = hashlib.md5(octets).hexdigest()
    nom = "20260920-084157_vision_1.1.19_%s.jpg" % empreinte
    total += 1
    conforme = uploads.parse_image_ref(nom)["md5"] == empreinte
    succes += conforme
    print("%s  le md5 lu dans l'image_ref est celui des octets deposes"
          % ("OK   " if conforme else "ECHEC"))

    total += 1
    autre = "20260921-101010_vision_1.1.19_%s.jpg" % empreinte
    conforme = uploads.parse_image_ref(autre)["md5"] == empreinte
    succes += conforme
    print("%s  la meme photo redeposee un autre jour porte le MEME md5 : c'est ce qui rend "
          "la seconde reconnaissance gratuite" % ("OK   " if conforme else "ECHEC"))

    for mauvais in ("../../etc/passwd", "20260920-084157_vision_1.1.19_zz.jpg",
                    "logo.jpg", ""):
        total += 1
        try:
            uploads.parse_image_ref(mauvais)
            conforme = False
        except uploads.UploadRefInvalid:
            conforme = True
        succes += conforme
        print("%s  refuse avant qu'un chemin existe : %r"
              % ("OK   " if conforme else "ECHEC", mauvais))

    print()
    print("%d/%d" % (succes, total))
    return 0 if succes == total else 1


if __name__ == "__main__":
    sys.exit(main())
