#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification des deux exemptions de la garde d'entite de reponse, FASTAPI-TEXT2SQL-303 et -311.

    uv run eval/verif-311.py

La garde (-117/-136) regenere toute requete qui ne projette pas l'identifiant de l'entite
attendue. Deux formes n'en projettent aucun par construction :

- le total unique, une seule cellule d'agregat sans GROUP BY (-303 pour COUNT, -311 pour AVG
  et SUM). MIN et MAX restent dehors : "le film le plus long" ecrit SELECT MAX(RUNTIME) est une
  mauvaise reponse que la garde doit continuer de corriger en ligne de film ;
- la table de statistiques (-311), des agregats groupes par des ATTRIBUTS seulement (decennie,
  annee, langue). Un GROUP BY sur une identite (ID_*, *_NAME, *_TITLE, DESCRIPTION) n'en est pas
  une : "les realisateurs qui ont le plus de films" groupe sur PERSON_NAME seul est precisement
  la forme que la garde doit transformer en lignes de personnes, photos comprises.

Les cas "laisser passer" viennent des deux requetes du 2026-10-04 (premieres SQL de Nolan et de
Kubrick, mot pour mot) et de formes voisines ; les cas "doit regenerer" sont ceux pour lesquels
la garde existe. Le code teste est lu sur le disque et non importe, `main.py` ouvrant la base et
ChromaDB a l'import. Meme geste que `verif-274.py`.
"""
import io
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(RACINE, "main.py")
src = io.open(SOURCE, encoding="utf-8").read()
debut = src.index("_AGGREGATE_ITEM = re.compile(")
fin = src.index("# Single source of truth: result_entity -> (id column, primary table).")
espace = {"re": re}
exec(compile(src[debut:fin], SOURCE, "exec"), espace)
total_unique = espace["_is_single_total_select"]
table_stats = espace["_is_statistics_table_select"]


def garde_regenere(sql, id_attendu):
    """La decision de la garde, sans l'union ni l'identite -300 : regenere-t-elle ?"""
    select = re.split(r"\bfrom\b", sql, maxsplit=1, flags=re.IGNORECASE)[0].upper()
    if total_unique(sql) or table_stats(sql):
        return False
    return id_attendu not in select


M, P, PM = "T_WC_T2S_MOVIE", "T_WC_T2S_PERSON", "T_WC_T2S_PERSON_MOVIE"
NOLAN_1 = (f"SELECT DISTINCT AVG({M}.RUNTIME) AS AVERAGE_RUNTIME FROM {M} JOIN {PM} ON {PM}.ID_MOVIE = {M}.ID_MOVIE "
           f"JOIN {P} ON {P}.ID_PERSON = {PM}.ID_PERSON WHERE {P}.PERSON_NAME = '{{{{Person_name1}}}}' AND {PM}.CREDIT_TYPE = 'crew'")
KUBRICK_1 = (f"SELECT DISTINCT FLOOR({M}.RELEASE_YEAR / 10) * 10 AS DECADE, AVG({M}.IMDB_RATING) AS AVERAGE_IMDB_RATING "
             f"FROM {M} JOIN {PM} ON {PM}.ID_MOVIE = {M}.ID_MOVIE JOIN {P} ON {P}.ID_PERSON = {PM}.ID_PERSON "
             f"WHERE {P}.PERSON_NAME = '{{{{Person_name1}}}}' AND {PM}.CREDIT_TYPE = 'crew' AND {M}.RELEASE_YEAR IS NOT NULL "
             f"GROUP BY FLOOR({M}.RELEASE_YEAR / 10) * 10 ORDER BY DECADE ASC")
KUBRICK_FINAL = (f"SELECT DISTINCT {M}.ID_MOVIE, {M}.MOVIE_TITLE, FLOOR({M}.RELEASE_YEAR / 10) * 10 AS RELEASE_DECADE, "
                 f"(SELECT AVG(m2.IMDB_RATING) FROM {M} m2 WHERE FLOOR(m2.RELEASE_YEAR / 10) = FLOOR({M}.RELEASE_YEAR / 10)) "
                 f"AS DECADE_AVERAGE_IMDB_RATING FROM {M} ORDER BY RELEASE_DECADE ASC LIMIT 50")

CAS = [
    # (libelle, sql, id attendu, la garde doit-elle regenerer ?)
    ("Nolan, 1re SQL du 2026-10-04 (AVG seul)", NOLAN_1, "ID_TECHNICAL", False),
    ("Kubrick, 1re SQL du 2026-10-04 (par decennie)", KUBRICK_1, "ID_MOVIE", False),
    ("SUM seul", f"SELECT SUM({M}.REVENUE) AS TOTAL_REVENUE FROM {M} WHERE {M}.RELEASE_YEAR = 1994", "ID_MOVIE", False),
    ("ROUND(AVG()) seul", f"SELECT ROUND(AVG({M}.RUNTIME), 1) AS AVG_RUNTIME FROM {M}", "ID_MOVIE", False),
    ("COUNT seul (-303)", f"SELECT COUNT(DISTINCT {M}.ID_MOVIE) AS MOVIE_COUNT FROM {M} WHERE {M}.IS_DOCUMENTARY = 1", "ID_MOVIE", False),
    ("films par annee", f"SELECT {M}.RELEASE_YEAR, COUNT(DISTINCT {M}.ID_MOVIE) AS MOVIE_COUNT FROM {M} GROUP BY {M}.RELEASE_YEAR ORDER BY {M}.RELEASE_YEAR", "ID_MOVIE", False),
    ("duree moyenne par langue, GROUP BY alias", f"SELECT {M}.ORIGINAL_LANGUAGE AS LANG, AVG({M}.RUNTIME) AS AVG_RUNTIME FROM {M} GROUP BY LANG", "ID_MOVIE", False),
    ("par decennie, GROUP BY ordinal", f"SELECT FLOOR({M}.RELEASE_YEAR/10)*10 AS DECADE, MAX({M}.RUNTIME) AS LONGEST FROM {M} GROUP BY 1", "ID_MOVIE", False),
    ("par decennie, chaine contenant FROM", f"SELECT FLOOR({M}.RELEASE_YEAR/10)*10 AS DECADE, COUNT(*) AS N FROM {M} WHERE {M}.TAGLINE <> 'from, here' GROUP BY DECADE", "ID_MOVIE", False),

    ("MAX seul, le film le plus long (-303)", f"SELECT MAX({M}.RUNTIME) AS LONGEST FROM {M}", "ID_MOVIE", True),
    ("MIN seul", f"SELECT MIN({M}.RELEASE_YEAR) FROM {M}", "ID_MOVIE", True),
    ("realisateurs groupes sur le nom seul", f"SELECT {P}.PERSON_NAME, COUNT(DISTINCT {M}.ID_MOVIE) AS FILM_COUNT FROM {P} JOIN {PM} ON {PM}.ID_PERSON = {P}.ID_PERSON JOIN {M} ON {M}.ID_MOVIE = {PM}.ID_MOVIE GROUP BY {P}.PERSON_NAME ORDER BY FILM_COUNT DESC", "ID_PERSON", True),
    ("groupe sur le titre", f"SELECT {M}.MOVIE_TITLE, COUNT(*) AS N FROM {M} GROUP BY {M}.MOVIE_TITLE", "ID_MOVIE", True),
    ("groupe sur un alias de nom", f"SELECT {P}.PERSON_NAME AS WHO, COUNT(*) AS N FROM {P} GROUP BY WHO", "ID_PERSON", True),
    ("groupe sur un ordinal de nom", f"SELECT {P}.PERSON_NAME, COUNT(*) AS N FROM {P} GROUP BY 1", "ID_PERSON", True),
    ("liste de noms sans agregat", f"SELECT {P}.PERSON_NAME FROM {P} JOIN {PM} ON {PM}.ID_PERSON = {P}.ID_PERSON WHERE {PM}.ID_MOVIE = 949", "ID_PERSON", True),
    ("titres filtres par une moyenne en sous-requete", f"SELECT {M}.MOVIE_TITLE FROM {M} WHERE {M}.RUNTIME > (SELECT AVG(m2.RUNTIME) FROM {M} m2)", "ID_MOVIE", True),
    ("decennie + titre non groupe", f"SELECT FLOOR({M}.RELEASE_YEAR/10)*10 AS DECADE, {M}.MOVIE_TITLE, AVG({M}.IMDB_RATING) FROM {M} GROUP BY DECADE", "ID_MOVIE", True),
    ("decennie sans agregat (GROUP BY de dedoublonnage)", f"SELECT FLOOR({M}.RELEASE_YEAR/10)*10 AS DECADE FROM {M} GROUP BY DECADE", "ID_MOVIE", True),
    ("moyenne fenetree par ligne, sans GROUP BY", f"SELECT FLOOR({M}.RELEASE_YEAR/10)*10 AS DECADE, AVG({M}.IMDB_RATING) OVER (PARTITION BY FLOOR({M}.RELEASE_YEAR/10)) AS R FROM {M}", "ID_MOVIE", True),
    ("acteurs de Heat projetant le film", f"SELECT {M}.ID_MOVIE, {M}.MOVIE_TITLE FROM {M} WHERE {M}.MOVIE_TITLE = 'Heat'", "ID_PERSON", True),
    ("UNION refusee par l exemption (la garde a sa propre regle UNION)", f"SELECT RELEASE_YEAR, COUNT(*) FROM {M} GROUP BY RELEASE_YEAR UNION SELECT FIRST_AIR_YEAR, COUNT(*) FROM T_WC_T2S_SERIE GROUP BY FIRST_AIR_YEAR", "ID_MOVIE", True),

    ("Kubrick, SQL finale du 2026-10-04 (porte ID_MOVIE, la garde est satisfaite)", KUBRICK_FINAL, "ID_MOVIE", False),
]


def main():
    succes = 0
    for libelle, sql, id_attendu, attendu in CAS:
        obtenu = garde_regenere(sql, id_attendu)
        conforme = obtenu == attendu
        succes += conforme
        print("%s  %-62s regenere=%-5s attendu=%s" % ("OK   " if conforme else "ECHEC", libelle, obtenu, attendu))
    print()
    print("%d/%d" % (succes, len(CAS)))
    return 0 if succes == len(CAS) else 1


if __name__ == "__main__":
    sys.exit(main())
