-- ============================================================================
-- T_WC_T2S_EVALUATION_EXECUTION: the two model columns that -232 left out
-- (FASTAPI-TEXT2SQL-234)
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-25. Run it BEFORE the first run of the new
-- evaluator (commit of the same day): the evaluator now reads and writes these two
-- columns, and an evaluator that finds them missing stops on "Unknown column".
--
-- WHY. The API takes five model selectors since -232, the execution table stored
-- three. Two campaigns differing only by --result-entity-model were therefore
-- skipped as already done, or, forced through, written into the baseline's folder.
-- With these columns the skip rule and the run folder are keyed on all five.
--
-- NO BACKFILL, ON PURPOSE. Existing rows keep NULL in both columns. NULL does not
-- mean gpt-4o, it means "written before the question arose"; filling it in would
-- invent a measurement. The evaluator treats NULL like the default gpt-4o when it
-- matches rows (so the baseline 001.001.019 stays one campaign and keeps its
-- three-model folder name), and exports it as null.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / ADD KEY IF NOT EXISTS (MariaDB). A re-run
-- changes nothing.
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '0. Before: the three model columns, and whether the two new ones exist' AS SECTION;
SELECT COLUMN_NAME, COLUMN_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME LIKE '%\_MODEL'
ORDER BY ORDINAL_POSITION;

ALTER TABLE T_WC_T2S_EVALUATION_EXECUTION
  ADD COLUMN IF NOT EXISTS `RESULT_ENTITY_MODEL` varchar(50) DEFAULT NULL
    COMMENT 'Modele de la tache result_entity pour ce passage (-234). NULL = ligne ecrite avant que la colonne existe, pas gpt-4o.'
    AFTER `COMPLEX_MODEL`,
  ADD COLUMN IF NOT EXISTS `ANSWER_SINGLE_VALUE_MODEL` varchar(50) DEFAULT NULL
    COMMENT 'Modele de la tache answer_single_value pour ce passage (-234). NULL = ligne ecrite avant que la colonne existe, pas gpt-4o.'
    AFTER `RESULT_ENTITY_MODEL`;

ALTER TABLE T_WC_T2S_EVALUATION_EXECUTION
  ADD KEY IF NOT EXISTS `RESULT_ENTITY_MODEL` (`RESULT_ENTITY_MODEL`),
  ADD KEY IF NOT EXISTS `ANSWER_SINGLE_VALUE_MODEL` (`ANSWER_SINGLE_VALUE_MODEL`);

SELECT '1. After: five model columns; every existing row NULL in the two new ones' AS SECTION;
SELECT COLUMN_NAME, COLUMN_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME LIKE '%\_MODEL'
ORDER BY ORDINAL_POSITION;

SELECT COUNT(*) AS ROWS_TOTAL,
       SUM(RESULT_ENTITY_MODEL IS NULL) AS RESULT_ENTITY_MODEL_NULL,
       SUM(ANSWER_SINGLE_VALUE_MODEL IS NULL) AS ANSWER_SINGLE_VALUE_MODEL_NULL
FROM T_WC_T2S_EVALUATION_EXECUTION;
