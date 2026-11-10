-- Cached answers that still return every namesake of a person the complex model identified,
-- or nobody when the model's birth year was off.
--
-- Read-only, voie 1. Written 2026-11-10. FASTAPI-TEXT2SQL-372 (deployed in place on Blue
-- 1.1.20, restart of 2026-11-08 around 20:45) settles a described person whose rewrite
-- `Person <name> born in <year>` matches several persons: what the complex model knows
-- (known_for, department, country) picks one, queried by its IMDb id. The SQL cache is keyed on
-- the question and the API version, and the version did not move, so a description answered
-- before the restart keeps its old SQL, `PERSON_NAME = ... AND BIRTH_YEAR = ...`, which returns
-- both namesakes (or nobody). The evaluator reads with retrieve_from_cache=false; the voice app
-- does not. Names are read from SQL_PROCESSED: SQL_QUERY keeps the person placeholders.
--
-- A stale row is: current version, living, a person name + birth year lookup in its SQL, no
-- IMDb id filter, and either two persons or more with that name and year, or none at that year
-- but at least one within two years. Rows whose question is itself the bare lookup
-- (`Person John Hughes born in 1950`) are listed apart: there both rows are the right answer.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

DROP TEMPORARY TABLE IF EXISTS tmp_372_lookup;
CREATE TEMPORARY TABLE tmp_372_lookup AS
SELECT c.ID_ROW, c.API_VERSION, c.UI_LANGUAGE, c.IS_ANONYMIZED, c.TIM_UPDATED, c.QUESTION,
       REPLACE(SUBSTRING(t.T, LOCATE('''', t.T) + 1, CHAR_LENGTH(t.T) - LOCATE('''', t.T) - 1),
               '''''', '''') AS PNAME,
       CAST(NULLIF(REGEXP_SUBSTR(REGEXP_SUBSTR(c.SQL_PROCESSED,
               'BIRTH_YEAR (=|BETWEEN) [( ]*[0-9]{4}'), '[0-9]{4}$'), '') AS UNSIGNED) AS YR
FROM T_WC_T2S_CACHE c
JOIN (SELECT ID_ROW, REGEXP_SUBSTR(SQL_PROCESSED, 'PERSON_NAME = ''([^'']|'''')*''') AS T
        FROM T_WC_T2S_CACHE) t ON t.ID_ROW = c.ID_ROW
WHERE COALESCE(c.DELETED, 0) = 0
  AND c.API_VERSION = (SELECT MAX(API_VERSION) FROM T_WC_T2S_CACHE)
  AND c.SQL_PROCESSED LIKE '%PERSON_NAME = %BIRTH_YEAR%'
  AND c.SQL_PROCESSED NOT LIKE '%ID_IMDB = %';

SELECT '1. Person name + birth year lookups cached in the current version' AS SECTION;

SELECT API_VERSION, UI_LANGUAGE, IS_ANONYMIZED, COUNT(*) AS N,
       MIN(TIM_UPDATED) AS OLDEST, MAX(TIM_UPDATED) AS NEWEST
FROM tmp_372_lookup
GROUP BY API_VERSION, UI_LANGUAGE, IS_ANONYMIZED
ORDER BY UI_LANGUAGE, IS_ANONYMIZED;

DROP TEMPORARY TABLE IF EXISTS tmp_372_pairs;
CREATE TEMPORARY TABLE tmp_372_pairs (
  PNAME varchar(250) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  YR int NOT NULL,
  PRIMARY KEY (PNAME, YR));
INSERT IGNORE INTO tmp_372_pairs
SELECT LEFT(PNAME, 250), YR FROM tmp_372_lookup WHERE YR IS NOT NULL AND PNAME <> '';

DROP TEMPORARY TABLE IF EXISTS tmp_372_counts;
CREATE TEMPORARY TABLE tmp_372_counts AS
SELECT p.PNAME, p.YR,
       COUNT(DISTINCT CASE WHEN pe.BIRTH_YEAR = p.YR THEN pe.ID_PERSON END) AS N_EXACT,
       COUNT(DISTINCT pe.ID_PERSON) AS N_WINDOW
FROM tmp_372_pairs p
LEFT JOIN T_WC_T2S_PERSON pe ON pe.PERSON_NAME = p.PNAME
     AND pe.BIRTH_YEAR BETWEEN p.YR - 2 AND p.YR + 2
     AND COALESCE(pe.DELETED, 0) = 0
GROUP BY p.PNAME, p.YR;

DROP TEMPORARY TABLE IF EXISTS tmp_372_stale;
CREATE TEMPORARY TABLE tmp_372_stale AS
SELECT l.*, COALESCE(n.N_EXACT, 0) AS N_EXACT, COALESCE(n.N_WINDOW, 0) AS N_WINDOW,
       (l.QUESTION REGEXP '^[[:space:]]*(Person|Personne)[[:space:]].*[0-9]{4}[[:space:]]*$') AS IS_BARE_LOOKUP
FROM tmp_372_lookup l
LEFT JOIN tmp_372_counts n
       ON n.PNAME = LEFT(l.PNAME, 250) COLLATE utf8mb4_unicode_ci AND n.YR = l.YR;

SELECT '1b. Diagnostic: what the extraction reads (sample)' AS SECTION;

SELECT ID_ROW, IS_ANONYMIZED, LEFT(PNAME, 30) AS PNAME, YR, LEFT(QUESTION, 60) AS QUESTION
FROM tmp_372_lookup ORDER BY TIM_UPDATED DESC LIMIT 8;

SELECT '2. Stale: a description cached with two namesakes, or none at a year that is off (candidates for the purge)' AS SECTION;

SELECT ID_ROW, UI_LANGUAGE, IS_ANONYMIZED, TIM_UPDATED, LEFT(PNAME, 30) AS PNAME, YR,
       N_EXACT, N_WINDOW, LEFT(QUESTION, 110) AS QUESTION
FROM tmp_372_stale
WHERE IS_BARE_LOOKUP = 0 AND (N_EXACT >= 2 OR (N_EXACT = 0 AND N_WINDOW >= 1))
ORDER BY TIM_UPDATED DESC
LIMIT 200;

SELECT '3. Bare lookups with namesakes (correct as they are, kept)' AS SECTION;

SELECT ID_ROW, UI_LANGUAGE, LEFT(PNAME, 30) AS PNAME, YR, N_EXACT, LEFT(QUESTION, 70) AS QUESTION
FROM tmp_372_stale
WHERE IS_BARE_LOOKUP = 1 AND N_EXACT >= 2
ORDER BY TIM_UPDATED DESC
LIMIT 50;

SELECT '4. Every living cache row of the evaluation questions 2692 to 2704, any version' AS SECTION;

SELECT c.ID_ROW, e.ID_T2S_EVALUATION, c.API_VERSION, c.UI_LANGUAGE, c.IS_ANONYMIZED, c.TIM_UPDATED,
       (c.SQL_QUERY LIKE '%ID_IMDB = %') AS BY_IMDB_ID, LEFT(c.QUESTION, 80) AS QUESTION
FROM T_WC_T2S_EVALUATION e
JOIN T_WC_T2S_CACHE c ON (c.QUESTION = e.QUESTION OR c.QUESTION = e.QUESTION_FR)
WHERE e.ID_T2S_EVALUATION BETWEEN 2692 AND 2704
  AND COALESCE(c.DELETED, 0) = 0
ORDER BY e.ID_T2S_EVALUATION, c.UI_LANGUAGE;

SELECT '5. Counts' AS SECTION;

SELECT SUM(IS_BARE_LOOKUP = 0 AND N_EXACT >= 2) AS STALE_NAMESAKES,
       SUM(IS_BARE_LOOKUP = 0 AND N_EXACT = 0 AND N_WINDOW >= 1) AS STALE_YEAR_OFF,
       SUM(IS_BARE_LOOKUP = 1 AND N_EXACT >= 2) AS BARE_WITH_NAMESAKES,
       SUM(N_EXACT = 1) AS UNIQUE_LOOKUPS,
       MAX(ID_ROW) AS MAX_ID_ROW
FROM tmp_372_stale;
