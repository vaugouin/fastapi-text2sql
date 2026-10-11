-- ============================================================================
-- FASTAPI-TEXT2SQL-324: free evals 2530 to 2539 (EN and FR) for their rerun on API 1.1.19
-- after the Source_work_name threshold moved from 71.8 to 79.55
-- ============================================================================
--
-- Written 2026-10-11. The threshold of data/entity_resolution.json (hot-reloaded, no restart)
-- comes from the second run of the bench (eval/data/bench-source-work-20261011-2.txt). The
-- French anchors typed without accents ("Au coeur des tenebres") passed at 71.8 and were not
-- re-scored at 79.55: the ten "based on" evaluations of -320 are the check, EN and FR.
--
-- The evaluator skips every question that already has a row for the same (API version, five
-- models, language): DELETED = 1 frees it, phase 10 hard-deletes it at the start of the next
-- run, then the question is replayed. The "before" stays readable in the exports.
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- Then, between off-all.sh and on-all.sh:
--   EVAL_IDS=2530,2531,2532,2533,2534,2535,2536,2537,2538,2539 EVAL_LANGUAGE=en ./text2sql-eval.sh
--   EVAL_IDS=2530,2531,2532,2533,2534,2535,2536,2537,2538,2539 EVAL_LANGUAGE=fr ./text2sql-eval.sh
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'B0. Before: executions of evals 2530 to 2539 on API 1.1.19' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL, RESULT_ENTITY_MODEL,
       DELETED, ASSERTIONS_TOTAL_SCORE, COMPLEX_MODEL_USED, FIRST_PASS_FAILURE_CODE
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION BETWEEN 2530 AND 2539
ORDER BY ID_T2S_EVALUATION, LANG, TEXT2SQL_MODEL, COMPLEX_MODEL;

UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE API_VERSION = '001.001.019'
  AND ID_T2S_EVALUATION BETWEEN 2530 AND 2539
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol'
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o'
  AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND LANG IN ('en', 'fr');

SELECT 'A0. After: the rows freed for the rerun' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION BETWEEN 2530 AND 2539
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol' AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o' AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
GROUP BY ID_T2S_EVALUATION, LANG, DELETED
ORDER BY ID_T2S_EVALUATION, LANG, DELETED;
