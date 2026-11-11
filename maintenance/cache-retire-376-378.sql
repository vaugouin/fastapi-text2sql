-- FASTAPI-TEXT2SQL-376, -377, -378: retire the 1.1.20 cache rows that would replay the SQL written before the prompt fix.
--
-- Why. The prompt change of 2026-11-11 (data/text_to_sql.md: "when" and "in order" questions sorted by
-- date, "movies" next to a collection on the film table alone, per-year trends capped at the current
-- year; data/complex_question.md: a question about a franchise's works keeps its question form) ships
-- without a version bump, so the exact-question and anonymized-question tiers of T_WC_T2S_CACHE still
-- serve the 1.1.20 SQL for every question already answered. "When were the Harry Potter movies
-- released?" was served on 2026-11-11 from such a row: a UNION ordered by IMDB_RATING_WEIGHTED DESC.
-- The evaluator is not concerned (it asks with retrieve_from_cache false); the users of the fronts are.
--
-- What is retired, on API_VERSION 001.001.020 only:
--   (a) the raw rows whose QUESTION is, byte for byte, the English or French question of evaluations
--       2600 to 2619 (sequences and trends), 2721 to 2730 (timelines) and 2830 to 2839 (this lot),
--       plus the ticket's question;
--   (b) every row sharing the QUESTION_HASHED of an (a) row: its anonymized twin carries the hash of
--       the ORIGINAL question (maintenance/AGENTS.md, "Key facts about the cache");
--   (c) every live anonymized row whose QUESTION is one of those anonymized templates, whichever raw
--       question wrote it: "When were the {{Collection_name1}} films released?" serves every collection.
-- Soft delete only (DELETED = 1), the convention of this folder: every lookup filters on DELETED, and
-- one UPDATE undoes it (`SET DELETED = 0 WHERE TIM_UPDATED = <the run's timestamp> AND ID_USER_UPDATED = 1`).
-- Not executed when written (2026-11-11): validated for syntax only.
--
-- ROUTING: UPDATE on T_WC_T2S_CACHE only, temporary tables, no DDL: voie 1. Run it right after
-- the pull that brings the prompt into the clone in service (Blue for 1.1.20):
--   ssh vps-agent pull fastapi-text2sql-blue
--   ssh vps-agent run fastapi-text2sql-blue/maintenance/cache-retire-376-378.sql

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Part 1. The questions, the hashes of their raw rows, and the anonymized templates of those hashes.
CREATE TEMPORARY TABLE TMP_376_QUESTIONS AS
SELECT QUESTION AS Q FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION BETWEEN 2600 AND 2619 OR ID_T2S_EVALUATION BETWEEN 2721 AND 2730
   OR ID_T2S_EVALUATION BETWEEN 2830 AND 2839
UNION
SELECT QUESTION_FR FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION BETWEEN 2600 AND 2619 OR ID_T2S_EVALUATION BETWEEN 2721 AND 2730
   OR ID_T2S_EVALUATION BETWEEN 2830 AND 2839
UNION
SELECT 'When were the Harry Potter movies released?';

CREATE TEMPORARY TABLE TMP_376_HASHES AS
SELECT DISTINCT T_WC_T2S_CACHE.QUESTION_HASHED AS H
FROM T_WC_T2S_CACHE
JOIN TMP_376_QUESTIONS ON T_WC_T2S_CACHE.QUESTION COLLATE utf8mb4_bin = TMP_376_QUESTIONS.Q COLLATE utf8mb4_bin
WHERE T_WC_T2S_CACHE.API_VERSION = '001.001.020'
  AND (T_WC_T2S_CACHE.DELETED IS NULL OR T_WC_T2S_CACHE.DELETED = 0)
  AND (T_WC_T2S_CACHE.IS_ANONYMIZED IS NULL OR T_WC_T2S_CACHE.IS_ANONYMIZED = 0);

CREATE TEMPORARY TABLE TMP_376_TEMPLATES AS
SELECT DISTINCT T_WC_T2S_CACHE.QUESTION AS T
FROM T_WC_T2S_CACHE
JOIN TMP_376_HASHES ON T_WC_T2S_CACHE.QUESTION_HASHED = TMP_376_HASHES.H
WHERE T_WC_T2S_CACHE.API_VERSION = '001.001.020'
  AND (T_WC_T2S_CACHE.DELETED IS NULL OR T_WC_T2S_CACHE.DELETED = 0)
  AND T_WC_T2S_CACHE.IS_ANONYMIZED = 1;

SELECT (SELECT COUNT(*) FROM TMP_376_QUESTIONS) AS QUESTIONS,
       (SELECT COUNT(*) FROM TMP_376_HASHES) AS RAW_HASHES,
       (SELECT COUNT(*) FROM TMP_376_TEMPLATES) AS ANONYMIZED_TEMPLATES;

-- Part 2. Before: the live rows that part 3 retires, one line each.
SELECT ID_ROW, UI_LANGUAGE, IS_ANONYMIZED, DAT_CREAT, LEFT(QUESTION, 90) AS QUESTION,
       LEFT(SUBSTRING_INDEX(SQL_QUERY, 'ORDER BY', -1), 80) AS ORDER_BY
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (QUESTION_HASHED IN (SELECT H FROM TMP_376_HASHES)
       OR (IS_ANONYMIZED = 1 AND QUESTION COLLATE utf8mb4_bin IN (SELECT T COLLATE utf8mb4_bin FROM TMP_376_TEMPLATES)))
ORDER BY QUESTION_HASHED, IS_ANONYMIZED, ID_ROW;

-- Part 3. The write.
UPDATE T_WC_T2S_CACHE
SET DELETED = 1, TIM_UPDATED = NOW(), ID_USER_UPDATED = 1
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (QUESTION_HASHED IN (SELECT H FROM TMP_376_HASHES)
       OR (IS_ANONYMIZED = 1 AND QUESTION COLLATE utf8mb4_bin IN (SELECT T COLLATE utf8mb4_bin FROM TMP_376_TEMPLATES)));

SELECT ROW_COUNT() AS ROWS_RETIRED;

-- Part 4. After: nothing of the targeted rows is left live (expected 0), and what was retired just now.
SELECT COUNT(*) AS STILL_LIVE
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (QUESTION_HASHED IN (SELECT H FROM TMP_376_HASHES)
       OR (IS_ANONYMIZED = 1 AND QUESTION COLLATE utf8mb4_bin IN (SELECT T COLLATE utf8mb4_bin FROM TMP_376_TEMPLATES)));

SELECT COUNT(*) AS RETIRED_TODAY
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020' AND DELETED = 1 AND ID_USER_UPDATED = 1
  AND TIM_UPDATED >= CURDATE()
  AND (QUESTION_HASHED IN (SELECT H FROM TMP_376_HASHES)
       OR (IS_ANONYMIZED = 1 AND QUESTION COLLATE utf8mb4_bin IN (SELECT T COLLATE utf8mb4_bin FROM TMP_376_TEMPLATES)));
