-- ============================================================================
-- T_WC_T2S_EVALUATION_EXECUTION: token totals per execution (FASTAPI-TEXT2SQL-296)
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-26. Run it BEFORE the first run of the evaluator
-- of the same commit: its scoring phase (20) writes these four columns, and an
-- evaluator that finds them missing stops on "Unknown column".
--
-- WHY. The API logged input and cached tokens and threw away the output and
-- reasoning ones, so the output side of every campaign's bill was unmeasured. On a
-- reasoning model (the GPT-6 line), reasoning tokens are billed at the OUTPUT price
-- and are exactly what can make a cheaper list price dearer in practice. The API
-- now returns `llm_usage`, per task, in every response; these columns hold the
-- request totals so a campaign can be summed in SQL. The per-task split stays in
-- JSON_RESULT: JSON_EXTRACT(JSON_RESULT, '$.llm_usage.text2sql.reasoning_tokens').
--
-- CONVENTIONS, as OpenAI bills: LLM_PROMPT_TOKENS includes LLM_CACHED_TOKENS, and
-- LLM_COMPLETION_TOKENS includes LLM_REASONING_TOKENS.
--
-- NO BACKFILL, ON PURPOSE. Existing rows keep NULL: their JSON_RESULT carries no
-- `llm_usage`, so there is nothing to compute them from. NULL means "not measured",
-- never zero. A rescore of such rows leaves them NULL.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / ADD KEY IF NOT EXISTS (MariaDB).
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '0. Before: token columns present on the execution table' AS SECTION;
SELECT COLUMN_NAME, COLUMN_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME LIKE 'LLM\_%\_TOKENS'
ORDER BY ORDINAL_POSITION;

ALTER TABLE T_WC_T2S_EVALUATION_EXECUTION
  ADD COLUMN IF NOT EXISTS `LLM_PROMPT_TOKENS` int(11) DEFAULT NULL
    COMMENT 'Jetons d entree de la requete, toutes taches, cache compris (-296). NULL = non mesure.'
    AFTER `ENTITY_MATCH_WORST_FUZZ_RATIO`,
  ADD COLUMN IF NOT EXISTS `LLM_CACHED_TOKENS` int(11) DEFAULT NULL
    COMMENT 'Part de LLM_PROMPT_TOKENS lue en cache (-296). NULL = non mesure.'
    AFTER `LLM_PROMPT_TOKENS`,
  ADD COLUMN IF NOT EXISTS `LLM_COMPLETION_TOKENS` int(11) DEFAULT NULL
    COMMENT 'Jetons de sortie de la requete, toutes taches, raisonnement compris (-296). NULL = non mesure.'
    AFTER `LLM_CACHED_TOKENS`,
  ADD COLUMN IF NOT EXISTS `LLM_REASONING_TOKENS` int(11) DEFAULT NULL
    COMMENT 'Part de LLM_COMPLETION_TOKENS consacree au raisonnement, facturee au prix de sortie (-296). NULL = non mesure.'
    AFTER `LLM_COMPLETION_TOKENS`;

ALTER TABLE T_WC_T2S_EVALUATION_EXECUTION
  ADD KEY IF NOT EXISTS `LLM_PROMPT_TOKENS` (`LLM_PROMPT_TOKENS`),
  ADD KEY IF NOT EXISTS `LLM_CACHED_TOKENS` (`LLM_CACHED_TOKENS`),
  ADD KEY IF NOT EXISTS `LLM_COMPLETION_TOKENS` (`LLM_COMPLETION_TOKENS`),
  ADD KEY IF NOT EXISTS `LLM_REASONING_TOKENS` (`LLM_REASONING_TOKENS`);

SELECT '1. After: four token columns; every existing row NULL in them' AS SECTION;
SELECT COLUMN_NAME, COLUMN_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME LIKE 'LLM\_%\_TOKENS'
ORDER BY ORDINAL_POSITION;

SELECT COUNT(*) AS ROWS_TOTAL,
       SUM(LLM_PROMPT_TOKENS IS NULL) AS PROMPT_NULL,
       SUM(LLM_COMPLETION_TOKENS IS NULL) AS COMPLETION_NULL,
       SUM(LLM_REASONING_TOKENS IS NULL) AS REASONING_NULL
FROM T_WC_T2S_EVALUATION_EXECUTION;
