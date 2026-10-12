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
-- SECTION B. Soft-deletes, for BOTH text2sql models of the 1.1.19 campaigns (gpt-4o
-- baseline and gpt-6-sol, the other four tasks on gpt-4o), the executions of the 25
-- questions the prompt change can move: every question where either model, in either
-- language, wrote a COUNT( or a GROUP BY in the exports of 2026-09-27. The reruns of
-- both configurations then replay exactly these (skip rule), plus 29, 89 and 867 which
-- have no row yet, so each question is answered by both models WITH THE SAME PROMPT:
-- the new one here, the old one everywhere else. Decision of Philippe, 2026-09-28: no
-- full gpt-4o rerun. DELETED = 1 is enough: phase 10 hard-deletes them at the next run.
--   45, 197, 352, 413, 446, 474, 790, 791, 792, 793, 1112, 2169, 2170, 2171, 2172, 2247, 2280, 2287, 2301, 2313, 2349, 2437, 2446, 2447, 2481
-- Caveat: -300 is live since 2026-09-28; the replayed rows carry it for both models alike.
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
  AND ENTITY_EXTRACTION_MODEL = 'gpt-4o'
  AND COMPLEX_MODEL = 'gpt-4o'
  AND TEXT2SQL_MODEL IN ('gpt-4o', 'gpt-6-sol')
  AND (RESULT_ENTITY_MODEL = 'gpt-4o' OR RESULT_ENTITY_MODEL IS NULL)
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND ID_T2S_EVALUATION IN (45, 197, 352, 413, 446, 474, 790, 791, 792, 793, 1112, 2169, 2170, 2171, 2172, 2247, 2280, 2287, 2301, 2313, 2349, 2437, 2446, 2447, 2481)
  AND DELETED = 0;

SELECT 'B1. After: 25 questions per model and language at DELETED = 1 (fewer where a language had no row)' AS SECTION;
SELECT TEXT2SQL_MODEL, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019'
GROUP BY TEXT2SQL_MODEL, LANG, DELETED
ORDER BY TEXT2SQL_MODEL, LANG, DELETED;
