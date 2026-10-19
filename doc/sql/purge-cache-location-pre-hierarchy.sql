-- Soft-delete cached SQL that reads the location tables without the place hierarchy.
--
-- Voie 1: one UPDATE on T_WC_T2S_CACHE (DELETED = 1), nothing else. Written 2026-10-19.
-- check-cache-location-pre-hierarchy-20261019.txt counted 111 living rows of 001.001.019
-- that read T_WC_T2S_LOCATION without T_WC_T2S_LOCATION_ANCESTOR, raw and anonymized, EN and
-- FR, the oldest from 2026-10-03. The lookups (sql_cache.py) read only non-deleted rows of
-- the current version, so each question gets fresh SQL on its next ask, with the hierarchy
-- when it needs it. Some of the 111 are place lists ("Where was Game of Thrones filmed?")
-- that do not need it; regenerating them costs one call each and they were not worth a
-- finer filter. Reversible: the rows stay, flagged; ID_ROW 1 to 21455 bounds the run so
-- a row written after this count is never touched.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '1. Before' AS SECTION;

SELECT COUNT(*) AS N
FROM T_WC_T2S_CACHE
WHERE COALESCE(DELETED, 0) = 0 AND API_VERSION = '001.001.019' AND ID_ROW <= 21455
  AND SQL_QUERY LIKE '%T_WC_T2S_LOCATION%' AND SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%';

UPDATE T_WC_T2S_CACHE
   SET DELETED = 1
 WHERE COALESCE(DELETED, 0) = 0 AND API_VERSION = '001.001.019' AND ID_ROW <= 21455
   AND SQL_QUERY LIKE '%T_WC_T2S_LOCATION%' AND SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%';

SELECT '2. After: rows flagged, rows left' AS SECTION;

SELECT SUM(COALESCE(DELETED, 0) = 1) AS FLAGGED, SUM(COALESCE(DELETED, 0) = 0) AS LEFT_LIVING
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.019' AND ID_ROW <= 21455
  AND SQL_QUERY LIKE '%T_WC_T2S_LOCATION%' AND SQL_QUERY NOT LIKE '%LOCATION_ANCESTOR%';
