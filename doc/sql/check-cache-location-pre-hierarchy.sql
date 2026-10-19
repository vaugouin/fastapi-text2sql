-- Cached SQL that reads the location tables without the place hierarchy.
--
-- Read-only, voie 1. Written 2026-10-19. Since TMDB-MOVIE-PREPROCESS-048 and
-- FASTAPI-TEXT2SQL-332 (1.1.19 redeployed in place on Green), a named place used as a filter
-- goes through T_WC_T2S_LOCATION_ANCESTOR. The SQL cache (T_WC_T2S_CACHE) is keyed on the
-- question and the API version, and the version did not move, so a question cached before
-- the redeploy is still served its old SQL: "movies set in Paris" without the places inside
-- Paris. The evaluator never sees it (it reads with retrieve_from_cache=false); a user does.
-- This file counts those rows; purge-cache-location-pre-hierarchy.sql soft-deletes them.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '1. Living cache rows that read a location table, by version, language, side' AS SECTION;

SELECT API_VERSION, UI_LANGUAGE, IS_ANONYMIZED,
       SUM(SQL_QUERY LIKE '%LOCATION_ANCESTOR%') AS WITH_HIERARCHY,
       SUM(SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%') AS WITHOUT_HIERARCHY,
       MIN(TIM_UPDATED) AS OLDEST, MAX(TIM_UPDATED) AS NEWEST
FROM T_WC_T2S_CACHE
WHERE COALESCE(DELETED, 0) = 0
  AND (SQL_QUERY LIKE '%T_WC_T2S_LOCATION%' OR SQL_QUERY LIKE '%_LOCATION %' OR SQL_QUERY LIKE '%_LOCATION.%')
GROUP BY API_VERSION, UI_LANGUAGE, IS_ANONYMIZED
ORDER BY API_VERSION DESC, UI_LANGUAGE, IS_ANONYMIZED;

SELECT '2. The rows the purge would hit (current version, no hierarchy), newest first' AS SECTION;

SELECT ID_ROW, API_VERSION, UI_LANGUAGE, IS_ANONYMIZED, TIM_UPDATED, LEFT(QUESTION, 70) AS QUESTION,
       CASE WHEN SQL_QUERY LIKE '%_LOCATION.LOCATION_ROLE%' OR SQL_QUERY LIKE '%LOCATION_NAME%' THEN 'place filter or place list' ELSE 'other' END AS KIND
FROM T_WC_T2S_CACHE
WHERE COALESCE(DELETED, 0) = 0
  AND API_VERSION = (SELECT MAX(API_VERSION) FROM T_WC_T2S_CACHE)
  AND SQL_QUERY LIKE '%T_WC_T2S_LOCATION%'
  AND SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%'
ORDER BY TIM_UPDATED DESC
LIMIT 60;

SELECT '3. Count the purge would hit' AS SECTION;

SELECT COUNT(*) AS N
FROM T_WC_T2S_CACHE
WHERE COALESCE(DELETED, 0) = 0
  AND API_VERSION = (SELECT MAX(API_VERSION) FROM T_WC_T2S_CACHE)
  AND SQL_QUERY LIKE '%T_WC_T2S_LOCATION%'
  AND SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%';
