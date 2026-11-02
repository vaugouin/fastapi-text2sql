-- FASTAPI-TEXT2SQL-360: export of the movie and series title pool for the offline lexical bench.
--
-- Read-only, voie 1. Written 2026-11-02. Feeds checks/bench-lexical-360.py, which replays the
-- movie and series mentions of the 1.1.19 campaigns against a lexical candidate generator and
-- compares it with what ChromaDB returned.
--
-- One row per living movie or series: TMDb forms (EN, FR, original) from the T2S table, plus the
-- Wikidata forms keyed by ID_WIKIDATA from the V2 dump tables (wikidata-crawler):
-- LABELS_JSON (en, fr, mul) and ALIASES_JSON (en, fr; arrays kept as JSON text).
-- Output format: the client prints a padded table, so records are packed 400 per row with
-- GROUP_CONCAT (rows of similar length, little padding): fields separated by CHAR(31), records
-- by CHAR(30), control characters inside values replaced by spaces.
--
-- The result is a data file (about 800,000 rows). It is NOT committed beside this .sql: the
-- bench reads it from shared_data/fastapi-text2sql/bench-360/ (see the script's docstring).

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION group_concat_max_len = 16777216;

-- Header, for the parser: FAM, ID, YR, VOTES, POP, QID, T_EN, T_FR, T_ORIG, WL_EN, WL_FR, WL_MUL, WA_EN, WA_FR

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR CHAR(30)) AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY m.ID_MOVIE) AS RN,
      CONCAT_WS(CHAR(31),
         'm',
         m.ID_MOVIE,
         COALESCE(m.RELEASE_YEAR, ''),
         COALESCE(m.IMDB_VOTES, 0),
         ROUND(COALESCE(m.POPULARITY, 0), 3),
         REGEXP_REPLACE(COALESCE(m.ID_WIKIDATA, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(m.MOVIE_TITLE, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(m.MOVIE_TITLE_FR, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(m.ORIGINAL_TITLE, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.en')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.fr')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.mul')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.en'), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.fr'), ''), '[[:cntrl:]]', ' ')) AS REC
      FROM T_WC_T2S_MOVIE m
      LEFT JOIN T_WC_WIKIDATA_MOVIE w ON w.ID_WIKIDATA = m.ID_WIKIDATA AND m.ID_WIKIDATA <> ''
     WHERE COALESCE(m.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR CHAR(30)) AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY s.ID_SERIE) AS RN,
      CONCAT_WS(CHAR(31),
         's',
         s.ID_SERIE,
         COALESCE(s.FIRST_AIR_YEAR, ''),
         COALESCE(s.IMDB_VOTES, 0),
         ROUND(COALESCE(s.POPULARITY, 0), 3),
         REGEXP_REPLACE(COALESCE(s.ID_WIKIDATA, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(s.SERIE_TITLE, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(s.SERIE_TITLE_FR, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(s.ORIGINAL_TITLE, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.en')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.fr')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(w.LABELS_JSON, '$.mul')), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.en'), ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(JSON_EXTRACT(w.ALIASES_JSON, '$.fr'), ''), '[[:cntrl:]]', ' ')) AS REC
      FROM T_WC_T2S_SERIE s
      LEFT JOIN T_WC_WIKIDATA_SERIE w ON w.ID_WIKIDATA = s.ID_WIKIDATA AND s.ID_WIKIDATA <> ''
     WHERE COALESCE(s.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;
