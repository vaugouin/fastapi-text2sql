#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification de l'arrondi des nombres de la reponse, FASTAPI-TEXT2SQL-308, sans API ni base.

    uv run --with "fastapi>=0.104.1" --with httpx eval/verif-308.py

Les lignes du SQL genere passaient telles quelles : une note ponderee sortait sur seize
chiffres, et un AVG() sur une colonne entiere, rendu en Decimal par PyMySQL, sortait en
CHAINE JSON sur /search/text2sql (Pydantic v2) mais en nombre sur les endpoints d'entite
(jsonable_encoder). Les cas ci-dessous verifient :

1. les regles de precision de `response_rounding.round_number`, cle par cle ;
2. `Text2SQLResponse` : la sortie est arrondie, le Decimal devient un nombre, et les
   attributs gardent leur valeur brute pour le code qui les relit apres construction ;
3. l'ordre d'une liste triee sur la valeur exacte est le meme apres arrondi ;
4. `RoundedJSONResponse`, par une vraie route FastAPI ;
5. que les dix-huit endpoints d'entite de `main.py` portent bien la classe de reponse.

La classe `Text2SQLResponse` est lue sur le disque et non importee : `main.py` tire la base,
ChromaDB et OpenAI a l'import. Meme geste que `verif-274.py`.
"""
import io
import os
import re
import sys
from decimal import Decimal
from typing import List, Optional

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, field_serializer, field_validator, model_validator  # noqa: E402

from response_rounding import RoundedJSONResponse, round_number, round_tree  # noqa: E402

SOURCE = os.path.join(RACINE, "main.py")
src = io.open(SOURCE, encoding="utf-8").read()
debut = src.index("class TextMessage(BaseModel):")  # suivie de Text2SQLResponse, qui la reference
fin = src.index("\nclass ResultItem(BaseModel):", debut)
espace = {"BaseModel": BaseModel, "Optional": Optional, "List": List, "round_tree": round_tree,
          "field_serializer": field_serializer, "field_validator": field_validator,
          "model_validator": model_validator}
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
Text2SQLResponse = espace["Text2SQLResponse"]

succes = 0
total = 0


def verifie(libelle, obtenu, attendu):
    global succes, total
    total += 1
    conforme = obtenu == attendu and type(obtenu) is type(attendu)
    succes += conforme
    print("%s  %-46s -> %-22r attendu %r" % ("OK   " if conforme else "ECHEC", libelle, obtenu, attendu))


print("-- 1. Precision par cle")
verifie("IMDB_RATING_WEIGHTED", round_number("IMDB_RATING_WEIGHTED", 7.837261538461538), 7.84)
verifie("IMDB_RATING saisi", round_number("IMDB_RATING", 8.2), 8.2)
verifie("POPULARITY", round_number("POPULARITY", 13.3946), 13.39)
verifie("alias AVG_RATING", round_number("avg_rating", 7.123456789), 7.12)
verifie("Decimal AVG(RUNTIME)", round_number("AVG_RUNTIME", Decimal("148.4000")), 148.4)
verifie("Decimal SUM entier", round_number("TOTAL_VOTES", Decimal("42")), 42)
verifie("BUDGET entier en DOUBLE", round_number("BUDGET", 160000000.0), 160000000)
verifie("REVENUE non entier", round_number("REVENUE", 1234.567), 1234.57)
verifie("petite valeur, 3 chiffres", round_number("POPULARITY", 0.012345678), 0.0123)
verifie("zero", round_number("POPULARITY", 0.0), 0.0)
verifie("FRAME_RATE", round_number("FRAME_RATE", Decimal("23.9760")), 23.976)
verifie("AMOUNT intact", round_number("AMOUNT", Decimal("0.0001234500")), 0.00012345)
verifie("temps a la milliseconde", round_number("total_processing_time", 3.14159265), 3.142)
verifie("distance a 4 decimales", round_number("distance", 0.123456789), 0.1235)
verifie("fuzz_ratio a 1 decimale", round_number("fuzz_ratio", 76.54), 76.5)
verifie("entier inchange", round_number("ID_MOVIE", 603), 603)
verifie("booleen inchange", round_number("IS_ADULT", True), True)
verifie("chaine numerique inchangee", round_number("ID_IMDB", "0133093"), "0133093")
verifie("None inchange", round_number("IMDB_RATING", None), None)
nan = round_number("IMDB_RATING", float("nan"))
verifie("NaN laisse tel quel", nan != nan, True)

print()
print("-- 2. Text2SQLResponse")
champs = {nom: 0.0 for nom in ("entity_extraction_processing_time", "text2sql_processing_time",
                                "embeddings_processing_time", "query_execution_time")}
reponse = Text2SQLResponse(
    question="q", sql_query="s", justification="j", error="", api_version="test",
    llm_model_entity_extraction="m", llm_model_text2sql="m", llm_model_complex="m",
    total_processing_time=3.14159265, **champs,
    result=[{"index": 0, "data": {"ID_MOVIE": 603, "MOVIE_TITLE": "The Matrix",
                                  "IMDB_RATING_WEIGHTED": 7.837261538461538,
                                  "AVG_RUNTIME": Decimal("148.4000"), "BUDGET": 63000000.0}}],
    entity_match_scores=[{"distance": 0.123456789, "max_distance": 0.35, "fuzz_ratio": 88.0}],
    entity_match_worst_distance=0.123456789,
    vision_evidence={"candidates": [{"title": "The Matrix", "confidence": 0.876543}]},
)
json_texte = reponse.model_dump_json()
verifie("Decimal en nombre dans le JSON", '"AVG_RUNTIME":148.4' in json_texte, True)
verifie("aucune chaine 148.4000", '"148.4000"' in json_texte, False)
verifie("note ponderee arrondie", '"IMDB_RATING_WEIGHTED":7.84' in json_texte, True)
verifie("BUDGET entier", '"BUDGET":63000000}' in json_texte, True)
verifie("temps total", '"total_processing_time":3.142' in json_texte, True)
verifie("distance de la liste", '"distance":0.1235' in json_texte, True)
verifie("pire distance", '"entity_match_worst_distance":0.1235' in json_texte, True)
verifie("confiance de la vision", '"confidence":0.88' in json_texte, True)
dump = reponse.model_dump()
verifie("model_dump (journal) arrondi aussi", dump["result"][0]["data"]["AVG_RUNTIME"], 148.4)
verifie("attribut brut intact (Decimal)", reponse.result[0]["data"]["AVG_RUNTIME"], Decimal("148.4000"))
verifie("attribut brut intact (temps)", reponse.total_processing_time, 3.14159265)

print()
print("-- 3. L'ordre trie sur la valeur exacte survit a l'arrondi")
lignes = [(1, 7.8449), (2, 7.8412), (3, 7.8401), (4, 7.8399), (5, 7.83)]
arrondies = [(i, round_number("IMDB_RATING_WEIGHTED", v)) for i, v in lignes]
verifie("memes identifiants, meme ordre", [i for i, _ in arrondies], [1, 2, 3, 4, 5])
verifie("valeurs non croissantes",
        all(a[1] >= b[1] for a, b in zip(arrondies, arrondies[1:])), True)

print()
print("-- 4. RoundedJSONResponse sur une route FastAPI")
app = FastAPI()


@app.get("/movies/{id}", response_class=RoundedJSONResponse)
def film(id: int):
    return {"ID_MOVIE": id, "IMDB_RATING_WEIGHTED": 7.837261538461538,
            "AVG_RUNTIME": Decimal("148.4000"), "images": [{"ASPECT_RATIO": 1.77777777}]}


corps = TestClient(app).get("/movies/603").json()
verifie("note ponderee", corps["IMDB_RATING_WEIGHTED"], 7.84)
verifie("Decimal en nombre", corps["AVG_RUNTIME"], 148.4)
verifie("liste imbriquee", corps["images"][0]["ASPECT_RATIO"], 1.78)

print()
print("-- 5. Les endpoints d'entite de main.py")
decorateurs = re.findall(r'@app\.get\(\s*"/([a-z]+)/\{[^)]*\)', src)
sans = [d for d in decorateurs if "response_class=RoundedJSONResponse" not in
        src[src.index('"/' + d + '/{'):src.index(")", src.index('"/' + d + '/{'))]]
verifie("endpoints d'entite trouves", len(decorateurs), 18)
verifie("tous portent RoundedJSONResponse", sans, [])

print()
print("%d/%d" % (succes, total))
sys.exit(0 if succes == total else 1)
