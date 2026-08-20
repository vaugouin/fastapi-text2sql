-- Cache maintenance: twin rows, and entries poisoned by an empty extraction.
--
-- NOT YET APPLIED. Read-only sections first (0 to 3), writes last (4 to 6), and the two
-- cleanups must run in the order given: section 5 before section 6. Every write is a soft
-- delete (DELETED = 1), which every cache lookup already honours, so all of it is undone
-- with a single UPDATE.
--
--
-- 1. THE TWIN ROW, AND WHY IT IS THE MARKER
--
-- A request writes two cache rows, the raw question and the anonymized one. When entity
-- extraction returns no entity at all, the anonymized question IS the raw question and both
-- writes carry the same question_hashed, computed once from the raw text. The two rows then
-- share QUESTION and QUESTION_HASHED and differ only by IS_ANONYMIZED, because the
-- _anonymized payloads only diverge from their siblings once entity resolution substitutes
-- placeholders, and the empty-result answer rewrite happens after both writes.
--
-- So a twin pair is not merely a wasted row. It is the mechanical, after-the-fact signature
-- of "entity extraction extracted nothing on this question". That is what makes this file
-- worth keeping: the marker is free and exact.
--
-- It also made the lookup ambiguous. Neither cache lookup filtered on IS_ANONYMIZED, and
-- `ORDER BY TIM_UPDATED DESC LIMIT 1` cannot separate two rows written in the same request
-- when TIM_UPDATED is a second-granularity datetime, so the row served depended on the
-- execution plan. Harmless while the twins were byte-identical, a coin toss the day anything
-- made the two payloads diverge before the write.
--
-- Both halves are fixed in code (main.py, the anonymized write is skipped when it would
-- duplicate; sql_cache.py, both lookups take an is_anonymized flag). New twins no longer
-- form. This file cleans the ones already in the table.
--
--
-- 2. POISONED IS A SUBSET OF TWINNED, NOT THE SAME THING
--
-- An empty extraction is not a defect by itself: "List actors" legitimately has no entity,
-- and its cached SQL is correct. The defect is the other case, where extraction returned
-- nothing AND the text2sql step still wrote a literal into a title or name column. That is
-- the signature of the May-to-August regression: MOVIE_TITLE = 'Les bas fonds', an exact
-- comparison on a value nobody resolved, which bypasses the ChromaDB multi-language
-- resolution (MOVIE_TITLE_FR, ORIGINAL_TITLE) that was the only thing able to match it.
--
-- Those entries return zero rows and, worse, keep returning zero rows after the prompt is
-- fixed, because the cache is keyed on API_VERSION and the version was not bumped. They are
-- the reason this cleanup is not cosmetic.
--
--
-- 3. A LASTING USE
--
-- Section 1 should return zero from now on. If it ever returns rows again, the write-side
-- guard in main.py has regressed. Re-running it after a deploy costs nothing and is a
-- cheaper regression check than anything in eval/.


-- ===========================================================================
-- 0. Inventory. Read-only.
-- ===========================================================================
SELECT IS_ANONYMIZED,
       COUNT(*)                       AS rows_live,
       COUNT(DISTINCT API_VERSION)    AS versions,
       MIN(TIM_UPDATED)               AS oldest,
       MAX(TIM_UPDATED)               AS newest
FROM T_WC_T2S_CACHE
WHERE (DELETED IS NULL OR DELETED = 0)
GROUP BY IS_ANONYMIZED;
-- A NULL bucket here means legacy rows predating the column. sql_cache.py currently reads
-- NULL as non-anonymized; once this returns no NULL bucket, that clause can be tightened to
-- a bare IS_ANONYMIZED = 0.


-- ===========================================================================
-- 1. Twin pairs: how many, and in what state. Read-only.
-- ===========================================================================
SELECT COUNT(*)                 AS pairs,
       SUM(same_payload)        AS with_identical_payload,
       SUM(same_second)         AS with_untiebreakable_ordering,
       SUM(wrote_a_literal)     AS poisoned
FROM (
  SELECT
    (    COALESCE(a.SQL_QUERY, '')     = COALESCE(r.SQL_QUERY, '')
     AND COALESCE(a.SQL_PROCESSED, '') = COALESCE(r.SQL_PROCESSED, '')
     AND COALESCE(a.JUSTIFICATION, '') = COALESCE(r.JUSTIFICATION, '')
     AND COALESCE(a.ANSWER, '')        = COALESCE(r.ANSWER, '')
    )                                                              AS same_payload,
    (a.TIM_UPDATED = r.TIM_UPDATED)                                AS same_second,
    (r.SQL_PROCESSED REGEXP '(MOVIE_TITLE|ORIGINAL_TITLE|SERIE_TITLE|EPISODE_TITLE|PERSON_NAME|CAST_CHARACTER|COMPANY_NAME|NETWORK_NAME|COLLECTION_NAME|AWARD_NAME|NOMINATION_NAME|MOVEMENT_NAME|GROUP_NAME|LIST_NAME|DEATH_NAME|TOPIC_NAME)(_FR)?[[:space:]]*(=|LIKE)')
                                                                   AS wrote_a_literal
  FROM T_WC_T2S_CACHE a
  JOIN T_WC_T2S_CACHE r
    ON  r.QUESTION_HASHED = a.QUESTION_HASHED
    AND r.API_VERSION     = a.API_VERSION
    AND r.UI_LANGUAGE     = a.UI_LANGUAGE
    AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
    AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
    AND (r.DELETED IS NULL OR r.DELETED = 0)
  WHERE a.IS_ANONYMIZED = 1
    AND (a.DELETED IS NULL OR a.DELETED = 0)
) t;
-- The join is on QUESTION_HASHED (indexed, 64 chars) for speed, but the text equality is
-- what isolates the twins: EVERY anonymized row carries the hash of its ORIGINAL question,
-- not of its own QUESTION, so the hash alone pairs every request's two rows, twinned or not.
-- The text comparison is forced to utf8mb4_bin because the table collation is
-- utf8mb4_unicode_ci and would call two questions equal that differ only by case or accent.


-- ===========================================================================
-- 2. Twin pairs, row by row. Read-only. Read this before any write.
-- ===========================================================================
SELECT r.ID_ROW                     AS id_raw,
       a.ID_ROW                     AS id_twin,
       r.API_VERSION,
       r.UI_LANGUAGE,
       r.TIM_UPDATED,
       (a.TIM_UPDATED = r.TIM_UPDATED)  AS same_second,
       LEFT(r.QUESTION, 70)             AS question,
       LEFT(r.SQL_PROCESSED, 120)       AS cached_sql
FROM T_WC_T2S_CACHE a
JOIN T_WC_T2S_CACHE r
  ON  r.QUESTION_HASHED = a.QUESTION_HASHED
  AND r.API_VERSION     = a.API_VERSION
  AND r.UI_LANGUAGE     = a.UI_LANGUAGE
  AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
  AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
  AND (r.DELETED IS NULL OR r.DELETED = 0)
WHERE a.IS_ANONYMIZED = 1
  AND (a.DELETED IS NULL OR a.DELETED = 0)
ORDER BY r.TIM_UPDATED DESC;


-- ===========================================================================
-- 3. The poisoned subset, row by row. Read-only. This is the population that
--    still returns zero rows to real users. Read it before section 5.
-- ===========================================================================
SELECT r.ID_ROW                     AS id_raw,
       a.ID_ROW                     AS id_twin,
       r.UI_LANGUAGE,
       r.TIM_UPDATED,
       LEFT(r.QUESTION, 70)             AS question,
       LEFT(r.SQL_PROCESSED, 160)       AS cached_sql
FROM T_WC_T2S_CACHE a
JOIN T_WC_T2S_CACHE r
  ON  r.QUESTION_HASHED = a.QUESTION_HASHED
  AND r.API_VERSION     = a.API_VERSION
  AND r.UI_LANGUAGE     = a.UI_LANGUAGE
  AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
  AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
  AND (r.DELETED IS NULL OR r.DELETED = 0)
WHERE a.IS_ANONYMIZED = 1
  AND (a.DELETED IS NULL OR a.DELETED = 0)
  AND r.SQL_PROCESSED REGEXP '(MOVIE_TITLE|ORIGINAL_TITLE|SERIE_TITLE|EPISODE_TITLE|PERSON_NAME|CAST_CHARACTER|COMPANY_NAME|NETWORK_NAME|COLLECTION_NAME|AWARD_NAME|NOMINATION_NAME|MOVEMENT_NAME|GROUP_NAME|LIST_NAME|DEATH_NAME|TOPIC_NAME)(_FR)?[[:space:]]*(=|LIKE)'
ORDER BY r.TIM_UPDATED DESC;


-- ===========================================================================
-- 4. Safety net. Copies every row involved in any twin pair, which is a
--    superset of both cleanups below. Rename the date suffix on each run.
-- ===========================================================================
CREATE TABLE T_WC_T2S_CACHE_TWINS_20260820 AS
SELECT c.*
FROM T_WC_T2S_CACHE c
WHERE (c.DELETED IS NULL OR c.DELETED = 0)
  AND c.ID_ROW IN (
    SELECT id FROM (
      SELECT a.ID_ROW AS id
      FROM T_WC_T2S_CACHE a
      JOIN T_WC_T2S_CACHE r
        ON  r.QUESTION_HASHED = a.QUESTION_HASHED
        AND r.API_VERSION     = a.API_VERSION
        AND r.UI_LANGUAGE     = a.UI_LANGUAGE
        AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
        AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
        AND (r.DELETED IS NULL OR r.DELETED = 0)
      WHERE a.IS_ANONYMIZED = 1 AND (a.DELETED IS NULL OR a.DELETED = 0)
      UNION
      SELECT r.ID_ROW AS id
      FROM T_WC_T2S_CACHE a
      JOIN T_WC_T2S_CACHE r
        ON  r.QUESTION_HASHED = a.QUESTION_HASHED
        AND r.API_VERSION     = a.API_VERSION
        AND r.UI_LANGUAGE     = a.UI_LANGUAGE
        AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
        AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
        AND (r.DELETED IS NULL OR r.DELETED = 0)
      WHERE a.IS_ANONYMIZED = 1 AND (a.DELETED IS NULL OR a.DELETED = 0)
    ) AS involved
  );


-- ===========================================================================
-- 5. RUN THIS BEFORE SECTION 6. Retires BOTH rows of each poisoned pair, so
--    the question is recomputed with the fixed prompt on its next ask.
-- ===========================================================================
UPDATE T_WC_T2S_CACHE a
JOIN T_WC_T2S_CACHE r
  ON  r.QUESTION_HASHED = a.QUESTION_HASHED
  AND r.API_VERSION     = a.API_VERSION
  AND r.UI_LANGUAGE     = a.UI_LANGUAGE
  AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
  AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
  AND (r.DELETED IS NULL OR r.DELETED = 0)
SET a.DELETED = 1,
    r.DELETED = 1
WHERE a.IS_ANONYMIZED = 1
  AND (a.DELETED IS NULL OR a.DELETED = 0)
  AND r.SQL_PROCESSED REGEXP '(MOVIE_TITLE|ORIGINAL_TITLE|SERIE_TITLE|EPISODE_TITLE|PERSON_NAME|CAST_CHARACTER|COMPANY_NAME|NETWORK_NAME|COLLECTION_NAME|AWARD_NAME|NOMINATION_NAME|MOVEMENT_NAME|GROUP_NAME|LIST_NAME|DEATH_NAME|TOPIC_NAME)(_FR)?[[:space:]]*(=|LIKE)';


-- ===========================================================================
-- 6. RUN THIS AFTER SECTION 5. Of the twin pairs that remain, all harmless by
--    now, retires only the redundant anonymized row and keeps the raw one.
--    The payload guard means a pair whose two rows differ is left alone: it is
--    not a twin in the sense this file means, and it wants a human look.
-- ===========================================================================
UPDATE T_WC_T2S_CACHE a
JOIN T_WC_T2S_CACHE r
  ON  r.QUESTION_HASHED = a.QUESTION_HASHED
  AND r.API_VERSION     = a.API_VERSION
  AND r.UI_LANGUAGE     = a.UI_LANGUAGE
  AND r.QUESTION        = a.QUESTION COLLATE utf8mb4_bin
  AND (r.IS_ANONYMIZED = 0 OR r.IS_ANONYMIZED IS NULL)
  AND (r.DELETED IS NULL OR r.DELETED = 0)
SET a.DELETED = 1
WHERE a.IS_ANONYMIZED = 1
  AND (a.DELETED IS NULL OR a.DELETED = 0)
  AND COALESCE(a.SQL_QUERY, '')     = COALESCE(r.SQL_QUERY, '')
  AND COALESCE(a.SQL_PROCESSED, '') = COALESCE(r.SQL_PROCESSED, '')
  AND COALESCE(a.JUSTIFICATION, '') = COALESCE(r.JUSTIFICATION, '')
  AND COALESCE(a.ANSWER, '')        = COALESCE(r.ANSWER, '');


-- ===========================================================================
-- 7. Verification, and the undo.
-- ===========================================================================
-- Re-run section 1. Both counts should now be zero.
--
-- To undo everything, the backup table holds the ID_ROW of every row touched:
-- UPDATE T_WC_T2S_CACHE c
--   JOIN T_WC_T2S_CACHE_TWINS_20260820 b ON b.ID_ROW = c.ID_ROW
--   SET c.DELETED = COALESCE(b.DELETED, 0);
