-- FASTAPI-TEXT2SQL-374: export of the award name pool for the offline bench of an exact-name
-- strategy ahead of the ChromaDB collection 'awards' ("Oscar de la meilleure actrice" resolved to
-- 'Ophir de la meilleure actrice': the French document of award 269 was not among the ten
-- nearest neighbours, and nothing looks the name up in the table).
--
-- Read-only, voie 1. Written 2026-11-10. Feeds checks/bench-lexical-374-awards.py, which builds the
-- production lexicon (title_lexicon.TitleLexicon) on AWARD_NAME and AWARD_NAME_FR, counts the
-- homonyms, and replays the Award_name mentions of the campaigns and of the API logs against it.
--
-- One row per living award. Same packing as check-360-export-name-pool.sql: records packed 400 per
-- row with GROUP_CONCAT, fields separated by CHAR(31), records by the literal '@@REC@@', control
-- characters inside values replaced by spaces.
-- The result is a data file, NOT committed beside this .sql: the bench reads it from
-- shared_data/fastapi-text2sql/bench-374/.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION group_concat_max_len = 16777216;

-- Header, for the parser:
-- ID, POP, PERSONS, MOVIES, SERIES, TYPE, PARENT, WIKIDATA, NAME, NAME_FR

SELECT COUNT(*) AS AWARDS,
       SUM(AWARD_NAME_FR IS NOT NULL AND AWARD_NAME_FR <> '') AS WITH_FR,
       SUM(AWARD_NAME_FR IS NOT NULL AND AWARD_NAME_FR <> '' AND AWARD_NAME_FR <> AWARD_NAME) AS FR_DIFFERS,
       SUM(COALESCE(PERSON_COUNT, 0) + COALESCE(MOVIE_COUNT, 0) + COALESCE(SERIE_COUNT, 0) > 0) AS WITH_WINNERS
  FROM T_WC_T2S_AWARD
 WHERE COALESCE(DELETED, 0) = 0;

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR '@@REC@@') AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY a.ID_AWARD) AS RN,
      CONCAT_WS(CHAR(31),
         a.ID_AWARD,
         ROUND(COALESCE(a.POPULARITY, 0), 3),
         COALESCE(a.PERSON_COUNT, 0),
         COALESCE(a.MOVIE_COUNT, 0),
         COALESCE(a.SERIE_COUNT, 0),
         COALESCE(a.AWARD_TYPE, ''),
         COALESCE(a.ID_AWARD_PARENT, 0),
         COALESCE(a.ID_WIKIDATA, ''),
         REGEXP_REPLACE(COALESCE(a.AWARD_NAME, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(a.AWARD_NAME_FR, ''), '[[:cntrl:]]', ' ')) AS REC
      FROM T_WC_T2S_AWARD a
     WHERE COALESCE(a.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;
