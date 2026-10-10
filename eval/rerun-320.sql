-- ============================================================================
-- FASTAPI-TEXT2SQL-320: free evals 2537 and 2538 (FR) for their after-the-fix rerun on API 1.1.19
-- ============================================================================
--
-- Written 2026-10-10, after the first "based on" campaign (EN 10/10, FR 8/10).
--   2537 FR "Quels films sont adaptés d'Au cœur des ténèbres ?": the SQL compared the French
--        title to SOURCE_WORK_NAME. Fixed by commit 30223df: comparison on SOURCE_WORK_NAME OR
--        SOURCE_WORK_NAME_FR, and Source_work_name now resolved through the t2ssourceworks
--        embeddings collection (process 217 of embedding-update, run the same day).
--   2538 FR "Films inspirés d'une histoire vraie": the SQL looked for a topic "histoire vraie".
--        Fixed by the same commit: the true-story topics are written in English as stored.
-- Deployed in place on Green without a version bump. Only FR is replayed: EN passed both.
--
-- The evaluator skips every question that already has a row for the same (API version, five
-- models, language): DELETED = 1 frees it, phase 10 hard-deletes it at the start of the next
-- run, then the question is replayed. The "before" stays readable in the exports
-- (shared_data/text2sql-eval/evaluation_execution/001.001.019_fr_gpt-6-sol_gpt-6-sol_gpt-4o_re-gpt-6-luna/).
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- Then: EVAL_IDS=2537,2538 EVAL_LANGUAGE=fr ./text2sql-eval.sh   (result entity defaults to gpt-6-luna)
--
-- Second pass, same day (runner with -f): 2537 passed, 2538 failed again on a topic name the
-- first fix had invented ('based on true story'); the stored name is 'true story', the one every
-- passing EN execution uses. This file frees both rows again, so replay both (2537 as control):
-- EVAL_IDS=2537,2538 EVAL_LANGUAGE=fr ./text2sql-eval.sh
--
-- Third pass, same day (runner with -f): the SQL was right ('true story') but the provenance
-- guard (entity.find_unbacked_entity_literals) refused a literal found neither in the French
-- question nor in the extraction. Fix in data/entity_extraction.md: "histoire vraie" is
-- extracted as Topic_name = 'true story', which backs the literal and resolves exactly.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'B0. Before: executions of evals 2537, 2538 on API 1.1.19' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL, RESULT_ENTITY_MODEL,
       DELETED, ASSERTIONS_TOTAL_SCORE, COMPLEX_MODEL_USED, FIRST_PASS_FAILURE_CODE
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION IN (2537, 2538)
ORDER BY ID_T2S_EVALUATION, LANG, TEXT2SQL_MODEL, COMPLEX_MODEL;

UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE API_VERSION = '001.001.019'
  AND ID_T2S_EVALUATION IN (2537, 2538)
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol'
  AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o'
  AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
  AND (ANSWER_SINGLE_VALUE_MODEL = 'gpt-4o' OR ANSWER_SINGLE_VALUE_MODEL IS NULL)
  AND LANG = 'fr';

SELECT 'A0. After: the rows freed for the rerun' AS SECTION;
SELECT ID_T2S_EVALUATION, LANG, DELETED, COUNT(*) AS ROWS_COUNT
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE API_VERSION = '001.001.019' AND ID_T2S_EVALUATION IN (2537, 2538)
  AND ENTITY_EXTRACTION_MODEL = 'gpt-6-sol' AND TEXT2SQL_MODEL = 'gpt-6-sol'
  AND COMPLEX_MODEL = 'gpt-4o' AND RESULT_ENTITY_MODEL = 'gpt-6-luna'
GROUP BY ID_T2S_EVALUATION, LANG, DELETED
ORDER BY ID_T2S_EVALUATION, LANG, DELETED;
