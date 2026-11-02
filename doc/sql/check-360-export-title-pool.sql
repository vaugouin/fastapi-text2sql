-- FASTAPI-TEXT2SQL-360: export of the movie and series title pool for the offline lexical bench.
--
-- Read-only, voie 1. Written 2026-11-02. Feeds checks/bench-lexical-360.py, which replays the
-- movie and series mentions of the 1.1.19 campaigns against a lexical candidate generator and
-- compares it with what ChromaDB returned.
--
-- One row per living movie or series: TMDb forms (EN, FR, original) from the T2S table, plus the
-- Wikidata forms keyed by ID_WIKIDATA from the V2 dump tables (wikidata-crawler):
-- LABELS_JSON (en, fr, mul) and ALIASES_JSON (en, fr; arrays kept as JSON text).
-- Tabs and line breaks are replaced by spaces so the batch output stays one row per line.
--
-- The result is a data file (about 800,000 rows). It is NOT committed beside this .sql: the
-- bench reads it from shared_data/fastapi-text2sql/bench-360/ (see the script's docstring).

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'm' AS FAM, m.ID_MOVIE AS ID, m.RELEASE_YEAR AS YR, COALESCE(m.IMDB_VOTES, 0) AS VOTES,
       ROUND(COALESCE(m.POPULARITY, 0), 3) AS POP, COALESCE(m.ID_WIKIDATA, '') AS QID,
       REPLACE(REPLACE(REPLACE(COALESCE(m.MOVIE_TITLE, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS T_EN,
       REPLACE(REPLACE(REPLACE(COALESCE(m.MOVIE_TITLE_FR, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS T_FR,
       REPLACE(REPLACE(REPLACE(COALESCE(m.ORIGINAL_TITLE, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' ') AS T_ORIG,
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.en')), '') AS WL_EN,
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.fr')), '') AS WL_FR,
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.mul')), '') AS WL_MUL,
       COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.en'), '') AS WA_EN,
       COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.fr'), '') AS WA_FR
  FROM T_WC_T2S_MOVIE m
  LEFT JOIN T_WC_WIKIDATA_MOVIE w ON w.ID_WIKIDATA = m.ID_WIKIDATA AND m.ID_WIKIDATA <> ''
 WHERE COALESCE(m.DELETED, 0) = 0
UNION ALL
SELECT 's', s.ID_SERIE, s.FIRST_AIR_YEAR, COALESCE(s.IMDB_VOTES, 0),
       ROUND(COALESCE(s.POPULARITY, 0), 3), COALESCE(s.ID_WIKIDATA, ''),
       REPLACE(REPLACE(REPLACE(COALESCE(s.SERIE_TITLE, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' '),
       REPLACE(REPLACE(REPLACE(COALESCE(s.SERIE_TITLE_FR, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' '),
       REPLACE(REPLACE(REPLACE(COALESCE(s.ORIGINAL_TITLE, ''), CHAR(9), ' '), CHAR(10), ' '), CHAR(13), ' '),
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.en')), ''),
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.fr')), ''),
       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.mul')), ''),
       COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.en'), ''),
       COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.fr'), '')
  FROM T_WC_T2S_SERIE s
  LEFT JOIN T_WC_WIKIDATA_SERIE w ON w.ID_WIKIDATA = s.ID_WIKIDATA AND s.ID_WIKIDATA <> ''
 WHERE COALESCE(s.DELETED, 0) = 0;
