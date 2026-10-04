-- ============================================================================
-- FASTAPI-TEXT2SQL-309: free eval 475 for its after-the-fix rerun on API 1.1.19
-- ============================================================================
--
-- Written 2026-10-04, for the typographic rescue of the resolver gate (commit 1cf0a46),
-- deployed in place on Green without a version bump, like -308.
--
-- Why only 475. eval/replay-rescue-309.py rescored offline every gate refusal of a title
-- resolver in the 17 runs then exported (230 refusals): the rescue fires on ONE question,
-- "Movie Bell' Antonio" (475; 477 was its duplicate, soft-deleted by Philippe the same day).
-- The French row is replayed too, as the control: its spelling "Film Bell'Antonio" already
-- passed the first pass, so the rescue must NOT fire there.
--
-- The evaluator skips every question that already has a row for the same (API version, five
-- models, language): DELETED = 1 frees it, phase 10 hard-deletes it at the start of the next
-- run, then the question is replayed. The "before" stays readable in the exports
-- (shared_data/text2sql-eval/evaluation_execution/001.001.019_*_gpt-6-sol_gpt-6-sol_gpt-4o_re-gpt-6-luna/).
--
-- Scope: the production configuration (extraction and text-to-SQL on gpt-6-sol, complex
-- question on gpt-4o, result entity on gpt-6-luna), EN and FR.
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- Then: EVAL_IDS=475 RESULT_ENTITY_MODEL=gpt-6-luna EVAL_LANGUAGE=en ./text2sql-eval.sh
--       (and EVAL_LANGUAGE=fr)
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'B0. Before: executions of eval 475 on API 1.1.19' AS SECTION;
SELECT LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL, RESULT_ENTITY_MODEL,
       DELETED, ASSERTIONS_TOTAL_SCORE, COMPLEX_MODEL_USED, FIRST_PASS_FAILURE_CODE
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION = 475
ORDER BY LANG, TEXT2SQL_MODEL, COMPLEX_MODEL;

UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE API_VERSION = '001.001.019'
  AND ID_T2S_EVALUATION = 475
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol'
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o'
  AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND LANG IN ('en', 'fr');

SELECT 'A0. After: the rows freed for the rerun' AS SECTION;
SELECT LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION = 475
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol' AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o' AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
GROUP BY LANG, DELETED
ORDER BY LANG, DELETED;
