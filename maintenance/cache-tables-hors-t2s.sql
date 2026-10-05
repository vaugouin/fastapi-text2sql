-- ============================================================================
-- Cached SQL that names a table outside the T2S backup perimeter
-- ============================================================================
--
-- READ ONLY. Written 2026-10-05, validated for syntax only: the DB is not
-- reachable outside the VPS, so nothing here has been run before its first pass.
--
-- WHY. Since FASTAPI-TEXT2SQL-179 and -313 the API code reads only T_WC_T2S_*
-- tables plus five non-T2S tables, which tools/backupvaugouindb-t2s.sh now backs
-- up (EXTRA_TABLES, commit befb567):
--   T_WC_WIKIPEDIA_PAGE_LANG, T_WC_WIKIPEDIA_PAGE_LANG_IMAGE,
--   T_WC_WIKIPEDIA_PAGE_LANG_SECTION, T_WC_WIKIDATA_MEDIA_RESOURCE,
--   T_WC_WIKIDATA_MEDIA_RESOURCE_URL.
-- The SQL cache (T_WC_T2S_CACHE) is restored with that backup, and it holds SQL
-- written by the generator before those migrations. A cached query that names any
-- other T_WC_ table works today, because the full database is there, and would fail
-- on a restore from the T2S backup alone. The entries naming T_WC_TMDB_GENRE were
-- already retired by Philippe on 2026-10-05. The suspects left: the episode and
-- season tables, which the prompt never described and which the generator guessed
-- anyway (FASTAPI-TEXT2SQL-185), and anything else it may have made up.
--
-- THE MARKER, AND WHY IT IS EXACT. A row is a suspect when SQL_QUERY or
-- SQL_PROCESSED still contains "T_WC_" followed by anything but "T2S_" once the
-- five allowed names are removed from the text. The allowed names are removed
-- longest first, so T_WC_WIKIPEDIA_PAGE_LANG does not eat the start of its _IMAGE
-- and _SECTION siblings. A name the generator invented (a table that does not
-- exist) is caught too, since the test is on the text, not on information_schema.
--
-- ONLY ACTIVE ROWS COUNT. Every cache lookup filters (DELETED IS NULL OR
-- DELETED = 0), so a retired row can never be served; section A shows the retired
-- count for reference only.
--
-- NOTHING IS WRITTEN. If section A finds active suspects, the retirement is a
-- separate decision (soft delete, backup table first, per maintenance/AGENTS.md).
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION max_statement_time = 0;

SELECT NOW() AS measured_at;

-- The cache text with the five allowed names removed, longest names first.
DROP TEMPORARY TABLE IF EXISTS tmp_cache_outside_t2s;
CREATE TEMPORARY TABLE tmp_cache_outside_t2s AS
SELECT c.ID_ROW,
       COALESCE(c.DELETED, 0) AS IS_DELETED,
       c.IS_ANONYMIZED,
       c.UI_LANGUAGE,
       c.API_VERSION,
       c.DAT_CREAT,
       LEFT(c.QUESTION, 140) AS QUESTION_START,
       REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
           CONCAT_WS(' ', c.SQL_QUERY, c.SQL_PROCESSED),
           'T_WC_WIKIPEDIA_PAGE_LANG_SECTION', ''),
           'T_WC_WIKIPEDIA_PAGE_LANG_IMAGE', ''),
           'T_WC_WIKIDATA_MEDIA_RESOURCE_URL', ''),
           'T_WC_WIKIDATA_MEDIA_RESOURCE', ''),
           'T_WC_WIKIPEDIA_PAGE_LANG', '') AS SQL_LEFT
FROM T_WC_T2S_CACHE c;


-- ############################################################################
-- ### A . HOW MANY                                                         ###
-- ############################################################################

SELECT '=== A . cache rows naming a table outside the T2S backup ===' AS section;

SELECT IS_DELETED,
       COUNT(*) AS cache_rows,
       SUM(SQL_LEFT REGEXP 'T_WC_(?!T2S_)[A-Z]') AS outside_t2s,
       SUM(INSTR(SQL_LEFT, 'T_WC_TMDB_') > 0) AS naming_tmdb,
       SUM(INSTR(SQL_LEFT, 'T_WC_WIKIDATA_') > 0) AS naming_other_wikidata,
       SUM(INSTR(SQL_LEFT, 'T_WC_WIKIPEDIA_') > 0) AS naming_other_wikipedia,
       SUM(INSTR(SQL_LEFT, 'T_WC_IMDB_') > 0) AS naming_imdb
FROM tmp_cache_outside_t2s
GROUP BY IS_DELETED
ORDER BY IS_DELETED;
-- Active row (IS_DELETED = 0) with outside_t2s = 0: the T2S backup is enough for
-- every cached answer, nothing else to do.


-- ############################################################################
-- ### B . WHICH TABLES (active rows)                                        ###
-- ############################################################################

SELECT '=== B . table names found, active rows only ===' AS section;

-- Exact count per real table: every non-T2S T_WC_ table of the schema, searched
-- as a substring of the cleaned text. A short name also matches inside a longer
-- one (T_WC_TMDB_SEASON inside T_WC_TMDB_SEASON_IMAGE): read the pair together.
SELECT t.TABLE_NAME, COUNT(*) AS active_cache_rows
FROM information_schema.TABLES t
JOIN tmp_cache_outside_t2s c
  ON c.IS_DELETED = 0
 AND INSTR(c.SQL_LEFT, t.TABLE_NAME) > 0
WHERE t.TABLE_SCHEMA = DATABASE()
  AND t.TABLE_NAME LIKE 'T!_WC!_%' ESCAPE '!'
  AND t.TABLE_NAME NOT LIKE 'T!_WC!_T2S!_%' ESCAPE '!'
GROUP BY t.TABLE_NAME
ORDER BY active_cache_rows DESC, t.TABLE_NAME;

-- Names that exist in no table of the schema: the generator made them up.
-- REGEXP_SUBSTR returns the first such name of each row only.
SELECT REGEXP_SUBSTR(c.SQL_LEFT, 'T_WC_(?!T2S_)[A-Z0-9_]+') AS first_outside_name,
       COUNT(*) AS active_cache_rows,
       MAX(t.TABLE_NAME IS NOT NULL) AS exists_in_schema
FROM tmp_cache_outside_t2s c
LEFT JOIN information_schema.TABLES t
  ON t.TABLE_SCHEMA = DATABASE()
 AND t.TABLE_NAME = REGEXP_SUBSTR(c.SQL_LEFT, 'T_WC_(?!T2S_)[A-Z0-9_]+')
WHERE c.IS_DELETED = 0
  AND c.SQL_LEFT REGEXP 'T_WC_(?!T2S_)[A-Z]'
GROUP BY first_outside_name
ORDER BY active_cache_rows DESC;


-- ############################################################################
-- ### C . SAMPLES (active rows)                                             ###
-- ############################################################################

SELECT '=== C . the first 40 active suspects ===' AS section;

SELECT c.ID_ROW, c.IS_ANONYMIZED, c.UI_LANGUAGE, c.API_VERSION, c.DAT_CREAT,
       REGEXP_SUBSTR(c.SQL_LEFT, 'T_WC_(?!T2S_)[A-Z0-9_]+') AS first_outside_name,
       c.QUESTION_START
FROM tmp_cache_outside_t2s c
WHERE c.IS_DELETED = 0
  AND c.SQL_LEFT REGEXP 'T_WC_(?!T2S_)[A-Z]'
ORDER BY c.DAT_CREAT DESC, c.ID_ROW DESC
LIMIT 40;

DROP TEMPORARY TABLE IF EXISTS tmp_cache_outside_t2s;
