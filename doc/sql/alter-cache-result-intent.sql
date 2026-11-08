-- FASTAPI-TEXT2SQL-353, 2026-11-08: RESULT_INTENT on T_WC_T2S_CACHE.
--
-- The question's intent read by the answer-entity classifier when the SQL was written, as
-- compact JSON {"task":..,"focus":[..],"requested_view":..,"source":..}
-- (result_intent.dumps_for_cache, under 200 characters in practice). A cache hit skips the
-- classifier, so without this column it would answer with the keyword rules instead of the
-- stored reading. sql_cache.py degrades on "Unknown column" until this runs: the code can be
-- deployed before or after it.
--
-- ROUTING: DDL, so voie 2 (the agent account has no ALTER):
--   cd ~/docker/fastapi-text2sql-blue && git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-blue/doc/sql/alter-cache-result-intent.sql
-- (the clone of the colour in service, -blue or -green). Instant on MariaDB: a nullable
-- column added at the end is an INSTANT ALTER.

ALTER TABLE T_WC_T2S_CACHE
  ADD COLUMN IF NOT EXISTS RESULT_INTENT varchar(500) DEFAULT NULL AFTER RESULT_ENTITY;

-- Check: the column exists, and how many rows already carry an intent (0 right after).
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'T_WC_T2S_CACHE'
    AND COLUMN_NAME IN ('RESULT_ENTITY', 'RESULT_INTENT');
SELECT COUNT(*) AS rows_with_intent FROM T_WC_T2S_CACHE WHERE RESULT_INTENT IS NOT NULL;
