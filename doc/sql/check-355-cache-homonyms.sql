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

DROP TEMPORARY TABLE IF EXISTS tmp_355_stale;
CREATE TEMPORARY TABLE tmp_355_stale AS
SELECT l.*,
       CASE WHEN l.KIND = 'movie' THEN
         (SELECT COUNT(*) FROM T_WC_T2S_MOVIE m
           WHERE (m.MOVIE_TITLE = l.TITLE OR m.MOVIE_TITLE_FR = l.TITLE OR m.ORIGINAL_TITLE = l.TITLE)
             AND m.RELEASE_YEAR BETWEEN l.YR - 1 AND l.YR + 1)
       ELSE
         (SELECT COUNT(*) FROM T_WC_T2S_SERIE s
           WHERE (s.SERIE_TITLE = l.TITLE OR s.SERIE_TITLE_FR = l.TITLE OR s.ORIGINAL_TITLE = l.TITLE)
             AND s.FIRST_AIR_YEAR BETWEEN l.YR - 1 AND l.YR + 1)
       END AS NAMESAKES,
       (l.QUESTION REGEXP '^[[:space:]]*(Movie|Film|Serie|Série)[[:space:]].*[(][0-9]{4}[)][[:space:]]*$') AS IS_BARE_LOOKUP
FROM tmp_355_lookup l;

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
