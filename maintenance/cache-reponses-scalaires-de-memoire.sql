-- Retire from the SQL cache the answers the removed single-value branch wrote from memory.
--
-- FASTAPI-TEXT2SQL-331 (2026-10-15). Until that ticket, a SQL that returned one cell worth 0
-- made the API ask an LLM for the number, wrap it in a synthetic
-- `SELECT <value> AS '<question>' FROM DUAL`, and cache that SQL under the exact question.
-- The code is gone, but its cache rows would keep serving the remembered number to every
-- request that hits the exact-question cache. Known cases: "How many Academy Awards did
-- Katharine Hepburn win?" (4) and Walt Disney's (22), EN and FR, campaign rows of 2313 and
-- 2349 and three production requests of 2026-10-10.
--
-- Only exact-question rows can carry one: the anonymized store writes the LLM's own SQL.
-- The pattern is the synthetic shape exactly, a numeric or quoted scalar aliased to the
-- question and read FROM DUAL, with SQL_QUERY equal to SQL_PROCESSED.
--
-- Soft delete (DELETED = 1), which every cache lookup already honours. Undo: section 4.
-- Runs under the agent account (writes T_WC_T2S_CACHE only).

-- 1. What will be retired.
SELECT ID_ROW, API_VERSION, UI_LANGUAGE, TIM_UPDATED, LEFT(QUESTION, 90) AS QUESTION, LEFT(SQL_QUERY, 120) AS SQL_QUERY
FROM T_WC_T2S_CACHE
WHERE (DELETED IS NULL OR DELETED = 0)
  AND IS_ANONYMIZED = 0
  AND SQL_QUERY = SQL_PROCESSED
  AND SQL_QUERY REGEXP '^SELECT (-?[0-9.]+|''[^'']*'') AS ''.*'' FROM DUAL$'
ORDER BY TIM_UPDATED;

-- 2. Retire them.
UPDATE T_WC_T2S_CACHE
SET DELETED = 1, TIM_UPDATED = NOW()
WHERE (DELETED IS NULL OR DELETED = 0)
  AND IS_ANONYMIZED = 0
  AND SQL_QUERY = SQL_PROCESSED
  AND SQL_QUERY REGEXP '^SELECT (-?[0-9.]+|''[^'']*'') AS ''.*'' FROM DUAL$';

-- 3. Check: nothing live is left in that shape.
SELECT COUNT(*) AS LIVE_SYNTHETIC_ROWS_LEFT
FROM T_WC_T2S_CACHE
WHERE (DELETED IS NULL OR DELETED = 0)
  AND SQL_QUERY REGEXP '^SELECT (-?[0-9.]+|''[^'']*'') AS ''.*'' FROM DUAL$';

-- 4. Undo (not run): set DELETED back to 0 on the ID_ROW values listed by section 1.
-- UPDATE T_WC_T2S_CACHE SET DELETED = 0 WHERE ID_ROW IN (...);
