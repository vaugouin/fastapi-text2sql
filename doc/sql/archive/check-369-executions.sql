-- FASTAPI-TEXT2SQL-369: state of the executions of evaluations 2664 to 2668 (read only, voie 1).
-- Shows whether the retire file has run (DELETED = 1 on the earlier 1.1.20 rows) and whether the
-- closing campaign has written new live rows, with their scores. 2026-11-08.
--   ssh vps-agent pull fastapi-text2sql-blue
--   ssh vps-agent run fastapi-text2sql-blue/doc/sql/archive/check-369-executions.sql

SELECT ID_T2S_EVALUATION, LANG, DELETED, API_VERSION, TIM_EXECUTION, TIM_UPDATED,
       ASSERTIONS_RESULT_SCORE, ASSERTIONS_TOTAL_SCORE, COMPLEX_MODEL_USED, TOTAL_PROCESSING_TIME
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE ID_T2S_EVALUATION IN (2664, 2665, 2666, 2667, 2668)
ORDER BY ID_T2S_EVALUATION, LANG, TIM_UPDATED;
