-- ============================================================================
-- FASTAPI-TEXT2SQL-309: free evals 475, 851, 923 and 1048 for their after-the-fix rerun on API 1.1.19
-- ============================================================================
--
-- Written 2026-10-04, for the typographic rescue of the resolver gate (commit 1cf0a46),
-- deployed in place on Green without a version bump, like -308.
--
-- Why these four. eval/eval-309.sh, stage `configured` against `none` (2026-10-04, run by
-- Philippe on the VPS), re-resolved live every value a gate refused in the 17 exported runs and
-- found four whose outcome the rescue changes, all on Movie_title:
--   475  "Bell' Antonio"                            -> Il bell'Antonio (76157), seen in EN
--   851  "Tron Arès"                                -> Tron : Ares (533533), seen in FR
--   923  "Jubilé"                                   -> Jubilee (41426), seen in FR
--   1048 "The.Human.Condition.II.Road.to.Eternity"  -> The Human Condition II: Road to Eternity (34528), seen in EN
-- (477, the duplicate of 475, is soft-deleted from the bank.) Both languages are replayed for
-- all four: the language where the refusal was seen is the fix, the other one the control. The
-- offline replay of the morning (eval/replay-rescue-309.py) found only 475 because it measured the
-- apostrophes alone on the five candidates the traces print.
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
-- Then: EVAL_IDS=475,851,923,1048 RESULT_ENTITY_MODEL=gpt-6-luna EVAL_LANGUAGE=en ./text2sql-eval.sh
--       (and EVAL_LANGUAGE=fr)
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'B0. Before: executions of evals 475, 851, 923, 1048 on API 1.1.19' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL, RESULT_ENTITY_MODEL,
       DELETED, ASSERTIONS_TOTAL_SCORE, COMPLEX_MODEL_USED, FIRST_PASS_FAILURE_CODE
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION IN (475, 851, 923, 1048)
ORDER BY ID_T2S_EVALUATION, LANG, TEXT2SQL_MODEL, COMPLEX_MODEL;

UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE API_VERSION = '001.001.019'
  AND ID_T2S_EVALUATION IN (475, 851, 923, 1048)
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol'
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o'
  AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND LANG IN ('en', 'fr');

SELECT 'A0. After: the rows freed for the rerun' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION IN (475, 851, 923, 1048)
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol' AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o' AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
GROUP BY ID_T2S_EVALUATION, LANG, DELETED
ORDER BY ID_T2S_EVALUATION, LANG, DELETED;
