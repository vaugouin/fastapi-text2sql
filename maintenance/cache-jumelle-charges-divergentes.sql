-- Diagnostic: a twin pair whose two rows do NOT carry the same payload.
--
-- READ-ONLY. Four SELECTs, nothing is written. Point it at another pair by changing
-- the two ID_ROW values below; @raw is the IS_ANONYMIZED = 0 row, @twin the other.
SET @raw  = 9075;
SET @twin = 9076;
--
-- WHY THIS FILE EXISTS
-- Section 1 of cache-jumelles-et-empoisonnees.sql, run on 2026-08-21, found exactly one
-- twin pair in the live cache and reported with_identical_payload = 0. That contradicts
-- the model the cleanup file is built on.
--
-- The model says: two cache rows twin when entity extraction returns nothing, because the
-- anonymized question is then the raw question and both writes carry the same
-- question_hashed. In that situation the payloads cannot diverge, since the _anonymized
-- values are seeded identical to their siblings and only separate when entity resolution
-- substitutes placeholders, of which there are none.
--
-- This pair breaks that. ID_ROW 9075 and 9076 are consecutive and share TIM_UPDATED to the
-- second, so they come from one request, and yet their payloads differ. Reading the code did
-- not explain it:
--   - sql_query_llm is captured at main.py:2419, BEFORE entity resolution reassigns
--     sql_query, and both rows store that same value in SQL_QUERY.
--   - the answer-entity guard at main.py:2276 keeps sql_query and sql_query_anonymized in
--     step, and does the same for justification and answer.
--   - the pagination strip happens after sql_query_processed_base / sql_query_anonymized_base
--     are captured, so it cannot separate the two cached copies.
--   - the empty-result answer rewrite is at main.py:2989, after both writes.
-- So the mechanism is unidentified. Do not assume; measure, which is what this file is for.
--
-- WHY IT MATTERS
-- It makes the read-side ambiguity concrete rather than hypothetical. Before the
-- IS_ANONYMIZED filter landed, neither lookup discriminated between these two rows, and
-- `ORDER BY TIM_UPDATED DESC LIMIT 1` had nothing to break the tie at second granularity.
-- On this question, which row got served depended on the execution plan, and the two rows
-- do not say the same thing. The coin toss described as a future risk was already running.
--
-- The pair is left in place: the payload guard in section 6 of the cleanup file refuses to
-- retire a pair whose rows differ, and correctly so. It wants an explanation, not a delete.


-- 1. Which field actually differs
SELECT
  (SELECT COALESCE(SQL_QUERY, '')     FROM T_WC_T2S_CACHE WHERE ID_ROW = @raw) =
  (SELECT COALESCE(SQL_QUERY, '')     FROM T_WC_T2S_CACHE WHERE ID_ROW = @twin) AS sql_query_same,
  (SELECT COALESCE(SQL_PROCESSED, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @raw) =
  (SELECT COALESCE(SQL_PROCESSED, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @twin) AS sql_processed_same,
  (SELECT COALESCE(JUSTIFICATION, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @raw) =
  (SELECT COALESCE(JUSTIFICATION, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @twin) AS justification_same,
  (SELECT COALESCE(ANSWER, '')        FROM T_WC_T2S_CACHE WHERE ID_ROW = @raw) =
  (SELECT COALESCE(ANSWER, '')        FROM T_WC_T2S_CACHE WHERE ID_ROW = @twin) AS answer_same,
  (SELECT COALESCE(RESULT_ENTITY, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @raw) =
  (SELECT COALESCE(RESULT_ENTITY, '') FROM T_WC_T2S_CACHE WHERE ID_ROW = @twin) AS result_entity_same;

-- 2. The two rows side by side. Lengths first: a length difference localises the divergence
--    faster than reading two long SQL statements.
SELECT ID_ROW, IS_ANONYMIZED, RESULT_ENTITY, UI_LANGUAGE, API_VERSION, TIM_UPDATED,
       CHAR_LENGTH(QUESTION)      AS len_question,
       CHAR_LENGTH(SQL_QUERY)     AS len_sql_query,
       CHAR_LENGTH(SQL_PROCESSED) AS len_sql_processed,
       CHAR_LENGTH(ANSWER)        AS len_answer,
       LEFT(ANSWER, 100)          AS answer,
       LEFT(JUSTIFICATION, 100)   AS justification
FROM T_WC_T2S_CACHE
WHERE ID_ROW IN (@raw, @twin)
ORDER BY IS_ANONYMIZED;

-- 3. Both SQL_PROCESSED in full, to see where they part company
SELECT ID_ROW, IS_ANONYMIZED, SQL_PROCESSED
FROM T_WC_T2S_CACHE
WHERE ID_ROW IN (@raw, @twin)
ORDER BY IS_ANONYMIZED;

-- 4. The whole question. The point is whether an entity SHOULD have come out of it: if one
--    should have, the pair is a second, distinct extraction failure and not a twin at all.
SELECT ID_ROW, QUESTION, LEFT(SQL_QUERY, 400) AS sql_query_llm
FROM T_WC_T2S_CACHE
WHERE ID_ROW = @raw;
