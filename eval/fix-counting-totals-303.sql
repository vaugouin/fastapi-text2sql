-- ============================================================================
-- FASTAPI-TEXT2SQL-303: counting questions, bank and campaign clean-up
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-28, with the prompt change of the same commit
-- (data/text_to_sql.md, "A single total: one row, one column") and the window-count
-- guard in main.py.
--
-- SECTION A. Three single-total questions carried NO result assertion, so they never
-- ran in a campaign, and gpt-4o answering "How many movies did Martin Scorsese direct?"
-- with a list of 50 films never counted as a failure. The bank already says what a
-- single total must look like: 2313 and 2349 (Oscars of Katharine Hepburn, Walt
-- Disney) assert `COUNT(*) == 1 AND CELL(0, 0) ...`. Same shape here, with floors
-- rather than exact values, so a TMDb sync does not break them. `>` is stored
-- HTML-escaped (&gt;), like the rest of the column. Guarded on an empty column:
-- never overwrites a hand-written assertion, and a re-run changes nothing.
-- Consequence: these three questions join the next campaigns, so the eligible count
-- per language grows by three and must be compared on common questions only.
--
-- SECTION B. Soft-deletes every execution written by the gpt-6-sol text2sql campaign
-- on API 1.1.19 (2026-09-27, both languages). They were produced with the prompt
-- BEFORE this fix; the rerun must replace them all, which the skip rule only does
-- once they are gone. DELETED = 1 is enough: phase 10 of the evaluator hard-deletes
-- soft-deleted executions at the start of the next run (its pre-flight counts them).
-- Nothing else is touched: the gpt-4o baseline rows of 1.1.19 stay.
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'A0. Before: result assertions of the single-total questions' AS SECTION;
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 60) AS QUESTION, LEFT(QUESTION_FR, 60) AS QUESTION_FR,
       IS_EVAL, DELETED, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (29, 89, 867, 2313, 2349, 790, 791, 792, 793, 2169, 2170, 2171, 2172, 2247)
ORDER BY ID_T2S_EVALUATION;

-- #29 How many movies were directed by Martin Scorsese? One cell, more than twenty.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND CELL(0, 0) &gt; 20'
WHERE ID_T2S_EVALUATION = 29 AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #89 Nombre de films réalisés par Martin Scorsese. Same question, French wording.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND CELL(0, 0) &gt; 20'
WHERE ID_T2S_EVALUATION = 89 AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #867 How many movies were released this year? One cell; any year has releases.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND CELL(0, 0) &gt; 0'
WHERE ID_T2S_EVALUATION = 867 AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

SELECT 'A1. After' AS SECTION;
SELECT ID_T2S_EVALUATION, IS_EVAL, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (29, 89, 867)
ORDER BY ID_T2S_EVALUATION;

SELECT 'B0. Before: executions of API 1.1.19 by text2sql model and language' AS SECTION;
SELECT TEXT2SQL_MODEL, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019'
GROUP BY TEXT2SQL_MODEL, LANG, DELETED
ORDER BY TEXT2SQL_MODEL, LANG, DELETED;

UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE API_VERSION = '001.001.019'
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND DELETED = 0;

SELECT 'B1. After: every gpt-6-sol row DELETED = 1, gpt-4o untouched' AS SECTION;
SELECT TEXT2SQL_MODEL, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019'
GROUP BY TEXT2SQL_MODEL, LANG, DELETED
ORDER BY TEXT2SQL_MODEL, LANG, DELETED;
