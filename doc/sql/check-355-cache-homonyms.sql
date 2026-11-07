-- Cached answers that still return every namesake of a work the complex model identified.
--
-- Read-only, voie 1. Written 2026-11-07. FASTAPI-TEXT2SQL-355 (deployed in place on Blue
-- 1.1.20, 2026-11-05) settles a riddle whose rewrite `Movie X (YYYY)` matches several works:
-- the credits the complex model knows pick one, queried by its IMDb id. The SQL cache
-- (T_WC_T2S_CACHE) is keyed on the question and the API version, and the version did not
-- move, so a riddle answered before the restart keeps its old SQL, a title + year lookup
-- that returns both films (the *Taxi Driver* tagline of GUESS-277). The evaluator reads with
-- retrieve_from_cache=false and never sees it; the voice app does.
--
-- A stale row is: current version, living, a title + year lookup in its SQL, no IMDb id
-- filter, and two works or more in the base for that title within one year. Rows whose
-- question is itself the bare lookup (`Movie Taxi Driver (1976)`) are listed apart: there
-- the two rows are the right answer.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

DROP TEMPORARY TABLE IF EXISTS tmp_355_lookup;
CREATE TEMPORARY TABLE tmp_355_lookup AS
SELECT c.ID_ROW, c.API_VERSION, c.UI_LANGUAGE, c.IS_ANONYMIZED, c.TIM_UPDATED,
       c.QUESTION,
       CASE WHEN c.SQL_QUERY LIKE '%T_WC_T2S_SERIE.SERIE_TITLE = %' THEN 'serie' ELSE 'movie' END AS KIND,
       REPLACE(SUBSTRING(t.T, LOCATE('''', t.T) + 1, CHAR_LENGTH(t.T) - LOCATE('''', t.T) - 1),
               '''''', '''') AS TITLE,
       CAST(NULLIF(REGEXP_SUBSTR(REGEXP_SUBSTR(c.SQL_QUERY,
               '(RELEASE_YEAR|FIRST_AIR_YEAR) BETWEEN [( ]*[0-9]{4}'), '[0-9]{4}$'), '') AS UNSIGNED) AS YR
FROM T_WC_T2S_CACHE c
JOIN (SELECT ID_ROW, REGEXP_SUBSTR(SQL_QUERY, '(MOVIE|SERIE)_TITLE = ''([^'']|'''')*''') AS T
        FROM T_WC_T2S_CACHE) t ON t.ID_ROW = c.ID_ROW
WHERE COALESCE(c.DELETED, 0) = 0
  AND c.API_VERSION = (SELECT MAX(API_VERSION) FROM T_WC_T2S_CACHE)
  AND (c.SQL_QUERY LIKE '%T_WC_T2S_MOVIE.MOVIE_TITLE = %RELEASE_YEAR BETWEEN%'
       OR c.SQL_QUERY LIKE '%T_WC_T2S_SERIE.SERIE_TITLE = %FIRST_AIR_YEAR BETWEEN%')
  AND c.SQL_QUERY NOT LIKE '%ID_IMDB = %';

SELECT '1. Title + year lookups cached in the current version' AS SECTION;

SELECT API_VERSION, KIND, UI_LANGUAGE, IS_ANONYMIZED, COUNT(*) AS N,
       MIN(TIM_UPDATED) AS OLDEST, MAX(TIM_UPDATED) AS NEWEST
FROM tmp_355_lookup
GROUP BY API_VERSION, KIND, UI_LANGUAGE, IS_ANONYMIZED
ORDER BY KIND, UI_LANGUAGE, IS_ANONYMIZED;

-- The namesakes are counted per distinct (kind, title, year), one indexed equality per title
-- column: a correlated OR over the three columns ran past the 600 s statement limit. A
-- temporary table can be opened once per statement, hence one INSERT per column.
DROP TEMPORARY TABLE IF EXISTS tmp_355_pairs;
CREATE TEMPORARY TABLE tmp_355_pairs (
  KIND varchar(5) NOT NULL,
  TITLE varchar(250) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  YR int NOT NULL,
  PRIMARY KEY (KIND, TITLE, YR));
INSERT IGNORE INTO tmp_355_pairs
SELECT KIND, LEFT(TITLE, 250), YR FROM tmp_355_lookup WHERE YR IS NOT NULL AND TITLE <> '';

DROP TEMPORARY TABLE IF EXISTS tmp_355_ids;
CREATE TEMPORARY TABLE tmp_355_ids (
  KIND varchar(5) NOT NULL,
  TITLE varchar(250) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  YR int NOT NULL,
  ID int NOT NULL);
INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, m.ID_MOVIE FROM tmp_355_pairs p
JOIN T_WC_T2S_MOVIE m ON m.MOVIE_TITLE = p.TITLE
WHERE p.KIND = 'movie' AND m.RELEASE_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, m.ID_MOVIE FROM tmp_355_pairs p
JOIN T_WC_T2S_MOVIE m ON m.MOVIE_TITLE_FR = p.TITLE
WHERE p.KIND = 'movie' AND m.RELEASE_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, m.ID_MOVIE FROM tmp_355_pairs p
JOIN T_WC_T2S_MOVIE m ON m.ORIGINAL_TITLE = p.TITLE
WHERE p.KIND = 'movie' AND m.RELEASE_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, s.ID_SERIE FROM tmp_355_pairs p
JOIN T_WC_T2S_SERIE s ON s.SERIE_TITLE = p.TITLE
WHERE p.KIND = 'serie' AND s.FIRST_AIR_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, s.ID_SERIE FROM tmp_355_pairs p
JOIN T_WC_T2S_SERIE s ON s.SERIE_TITLE_FR = p.TITLE
WHERE p.KIND = 'serie' AND s.FIRST_AIR_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

INSERT INTO tmp_355_ids
SELECT p.KIND, p.TITLE, p.YR, s.ID_SERIE FROM tmp_355_pairs p
JOIN T_WC_T2S_SERIE s ON s.ORIGINAL_TITLE = p.TITLE
WHERE p.KIND = 'serie' AND s.FIRST_AIR_YEAR BETWEEN p.YR - 1 AND p.YR + 1;

DROP TEMPORARY TABLE IF EXISTS tmp_355_stale;
CREATE TEMPORARY TABLE tmp_355_stale AS
SELECT l.*, COALESCE(n.NAMESAKES, 0) AS NAMESAKES,
       (l.QUESTION REGEXP '^[[:space:]]*(Movie|Film|Serie|Série)[[:space:]].*[(][0-9]{4}[)][[:space:]]*$') AS IS_BARE_LOOKUP
FROM tmp_355_lookup l
LEFT JOIN (SELECT KIND, TITLE, YR, COUNT(DISTINCT ID) AS NAMESAKES
             FROM tmp_355_ids GROUP BY KIND, TITLE, YR) n
       ON n.KIND = l.KIND COLLATE utf8mb4_unicode_ci
      AND n.TITLE = LEFT(l.TITLE, 250) COLLATE utf8mb4_unicode_ci AND n.YR = l.YR;

SELECT '1b. Diagnostic: what the extraction reads (sample, pairs, matched ids)' AS SECTION;

SELECT ID_ROW, IS_ANONYMIZED, KIND, LEFT(TITLE, 40) AS TITLE, YR, LEFT(QUESTION, 50) AS QUESTION
FROM tmp_355_lookup ORDER BY TIM_UPDATED DESC LIMIT 8;

SELECT ID_ROW, LEFT(SUBSTRING(SQL_QUERY, LOCATE('_TITLE = ', SQL_QUERY), 120), 120) AS SQL_QUERY_AT_TITLE,
       LEFT(SUBSTRING(SQL_PROCESSED, LOCATE('_TITLE = ', SQL_PROCESSED), 120), 120) AS SQL_PROCESSED_AT_TITLE
FROM T_WC_T2S_CACHE WHERE ID_ROW = (SELECT MAX(ID_ROW) FROM tmp_355_lookup);

SELECT (SELECT COUNT(*) FROM tmp_355_pairs) AS PAIRS;
SELECT (SELECT COUNT(*) FROM tmp_355_ids) AS IDS;

SELECT '2. Stale: a description cached with two namesakes or more (candidates for the purge)' AS SECTION;

SELECT ID_ROW, UI_LANGUAGE, IS_ANONYMIZED, TIM_UPDATED, KIND, TITLE, YR, NAMESAKES,
       LEFT(QUESTION, 110) AS QUESTION
FROM tmp_355_stale
WHERE NAMESAKES >= 2 AND IS_BARE_LOOKUP = 0
ORDER BY TIM_UPDATED DESC
LIMIT 200;

SELECT '3. Bare lookups with namesakes (correct as they are, kept)' AS SECTION;

SELECT ID_ROW, UI_LANGUAGE, KIND, TITLE, YR, NAMESAKES, LEFT(QUESTION, 70) AS QUESTION
FROM tmp_355_stale
WHERE NAMESAKES >= 2 AND IS_BARE_LOOKUP = 1
ORDER BY TIM_UPDATED DESC
LIMIT 50;

SELECT '4. GUESS-277: every living row of the Taxi Driver tagline, any version' AS SECTION;

SELECT ID_ROW, API_VERSION, UI_LANGUAGE, IS_ANONYMIZED, TIM_UPDATED,
       (SQL_QUERY LIKE '%ID_IMDB = %') AS BY_IMDB_ID, LEFT(QUESTION, 90) AS QUESTION
FROM T_WC_T2S_CACHE
WHERE COALESCE(DELETED, 0) = 0
  AND (QUESTION LIKE '%nobody who dreams%' OR QUESTION LIKE '%moins que rien%')
ORDER BY TIM_UPDATED DESC;

SELECT '5. Counts' AS SECTION;

SELECT SUM(NAMESAKES >= 2 AND IS_BARE_LOOKUP = 0) AS STALE,
       SUM(NAMESAKES >= 2 AND IS_BARE_LOOKUP = 1) AS BARE_WITH_NAMESAKES,
       SUM(NAMESAKES < 2) AS UNIQUE_LOOKUPS,
       MAX(ID_ROW) AS MAX_ID_ROW
FROM tmp_355_stale;
