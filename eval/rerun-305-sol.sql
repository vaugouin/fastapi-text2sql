-- ============================================================================
-- FASTAPI-TEXT2SQL-305: free the gpt-6-sol campaigns of API 1.1.19 for a full rerun
-- ============================================================================
--
-- Written 2026-10-01, after d1feeba (documentaries are movies, the identifier and
-- documentary rules, the three holes of the drop rule) was deployed in place on Green
-- and fix-bench-305.sql applied. The prompt change touches 525 of the 872 questions,
-- so the rerun is complete, not partial as for -303.
--
-- The evaluator skips every question that already has a row for the same
-- (API version, five models, language): without this file, a gpt-6-sol run on 1.1.19
-- makes zero calls. DELETED = 1 is enough: phase 10 hard-deletes these rows at the
-- start of the next run, then phase 11 replays every question.
--
-- Scope: gpt-6-sol on text2sql, the four other tasks on gpt-4o, EN and FR. The gpt-4o
-- baseline is NOT touched here: the prompt is common to both models, so the net of Sol
-- against gpt-4o is only fair once the baseline is replayed too (same statement with
-- TEXT2SQL_MODEL = 'gpt-4o').
--
-- The 2026-09-27 executions stay readable in the local exports
-- (eval/data/evaluation_execution/001.001.019_*_gpt-4o_gpt-6-sol_gpt-4o/).
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

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
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND (RESULT_ENTITY_MODEL = 'gpt-4o' OR RESULT_ENTITY_MODEL IS NULL)
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND DELETED = 0;

SELECT 'B1. After: gpt-6-sol rows at DELETED = 1 in both languages, gpt-4o unchanged' AS SECTION;
SELECT TEXT2SQL_MODEL, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019'
GROUP BY TEXT2SQL_MODEL, LANG, DELETED
ORDER BY TEXT2SQL_MODEL, LANG, DELETED;
