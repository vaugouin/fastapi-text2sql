-- Retire the 1.1.17 evaluation executions so the suite actually re-runs.
--
-- NOT APPLIED, AND PROBABLY NEVER WILL BE. On 2026-08-21 the simpler path was taken instead:
-- strapiversion moved to 1.1.18, which opens an empty execution namespace, needs no writes at
-- all, and keeps the 1.1.17 runs intact as a comparison point rather than retiring them. The
-- repo convention asks for that bump anyway once a data/ prompt has changed, and three had.
-- This file is kept because the trap it documents is permanent and will bite again the day
-- someone re-runs a version that already carries executions without bumping.
--
-- Read section 1 first. Section 3 is the one that writes, section 4 undoes it. Soft delete
-- only (DELETED = 1), which is what every evaluator query already filters on.
--
-- WHY THIS IS NEEDED BEFORE A FULL RUN
-- The run phase of eval/text2sql-eval.py excludes any evaluation that already has a LIVE
-- execution row for the same API_VERSION, the same three models and the same LANG (the
-- `strnotinbase` subquery around line 372). So a "full re-run" over a version that already
-- has executions runs almost nothing. Retiring the old rows is not housekeeping, it is the
-- precondition.
--
-- THE TRAP IN KEEPING YESTERDAY'S ROWS
-- "Keep yesterday's executions" and "re-run everything" cannot both hold. Every evaluation
-- that keeps a live row for a given language is skipped in that language. Concretely, keeping
-- the 2026-08-21 rows means the 22 new evaluations and the unstable #606 are NOT re-measured
-- in English. Section 2 offers that middle ground anyway, since it is a legitimate choice,
-- but section 3 is the one that gives a baseline you can read.
--
-- WHY A CLEAN SWEEP IS WORTH IT
-- The 1.1.17 English execution set currently mixes 777 rows produced on 2026-07-12 by the
-- pre-fix prompt with 39 produced on 2026-08-21 by the fixed one, under one folder and one
-- version label. That mixture is exactly what made the last numbers unreadable: 270 passes
-- and 10 failures that measured July, not today. The marginal cost of also re-running the 57
-- recent rows is around 1.6M tokens against the ~82M the full two-language run will spend, so
-- roughly two percent for a set that means one thing instead of two.


-- ===========================================================================
-- 1. What is there. Read-only. Run this first.
-- ===========================================================================
SELECT API_VERSION, LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL,
       COUNT(*)           AS executions,
       MIN(TIM_EXECUTION) AS oldest,
       MAX(TIM_EXECUTION) AS newest,
       SUM(ASSERTIONS_ENTITY_EXTRACTION_SCORE IS NOT NULL) AS with_ee_score
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0
GROUP BY API_VERSION, LANG, ENTITY_EXTRACTION_MODEL, TEXT2SQL_MODEL, COMPLEX_MODEL
ORDER BY API_VERSION, LANG;

-- Same thing broken down by execution day, for 1.1.17 only: this is where the July/August
-- mixture becomes visible.
SELECT LANG, DATE(TIM_EXECUTION) AS day, COUNT(*) AS executions
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0
  AND API_VERSION = '001.001.017'
  AND ENTITY_EXTRACTION_MODEL = 'gpt-4o'
  AND TEXT2SQL_MODEL = 'gpt-4o'
  AND COMPLEX_MODEL = 'gpt-4o'
GROUP BY LANG, DATE(TIM_EXECUTION)
ORDER BY LANG, day;


-- ===========================================================================
-- 2. MIDDLE GROUND, only if you insist on keeping the 2026-08-21 rows.
--    Retires everything on 1.1.17 EXCEPT that day. Those evaluations will then
--    be skipped in English by the new run. Use section 3 instead if you want a
--    baseline that means one thing.
-- ===========================================================================
-- UPDATE T_WC_T2S_EVALUATION_EXECUTION
-- SET DELETED = 1
-- WHERE DELETED = 0
--   AND API_VERSION = '001.001.017'
--   AND ENTITY_EXTRACTION_MODEL = 'gpt-4o'
--   AND TEXT2SQL_MODEL = 'gpt-4o'
--   AND COMPLEX_MODEL = 'gpt-4o'
--   AND DATE(TIM_EXECUTION) <> '2026-08-21';


-- ===========================================================================
-- 3. CLEAN SWEEP, the recommended one. Retires every live 1.1.17 execution for
--    the gpt-4o triplet, in both languages, so the next run covers everything.
-- ===========================================================================
UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE DELETED = 0
  AND API_VERSION = '001.001.017'
  AND ENTITY_EXTRACTION_MODEL = 'gpt-4o'
  AND TEXT2SQL_MODEL = 'gpt-4o'
  AND COMPLEX_MODEL = 'gpt-4o';

-- Re-run section 1: the 001.001.017 / gpt-4o rows should have disappeared from it. Other
-- versions (1.1.14 to 1.1.16) and other model triplets are untouched, on purpose: they are
-- the historical comparison points.


-- ===========================================================================
-- 4. Undo, if the run has to be called off.
-- ===========================================================================
-- Nothing is destroyed, so this brings every row back. It also revives rows that were
-- already DELETED = 1 before today, which is why it is commented out rather than offered
-- as a symmetric operation. If that matters, snapshot the ID_ROW set before section 3:
--   CREATE TABLE T_WC_T2S_EVALUATION_EXECUTION_RETIRED_20260821 AS
--   SELECT ID_ROW FROM T_WC_T2S_EVALUATION_EXECUTION
--   WHERE DELETED = 0 AND API_VERSION = '001.001.017'
--     AND ENTITY_EXTRACTION_MODEL = 'gpt-4o' AND TEXT2SQL_MODEL = 'gpt-4o'
--     AND COMPLEX_MODEL = 'gpt-4o';
-- and then restore only those:
--   UPDATE T_WC_T2S_EVALUATION_EXECUTION e
--     JOIN T_WC_T2S_EVALUATION_EXECUTION_RETIRED_20260821 b ON b.ID_ROW = e.ID_ROW
--     SET e.DELETED = 0;
