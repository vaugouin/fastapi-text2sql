-- FASTAPI-TEXT2SQL-386: retire the 1.1.20 cache rows of the questions about Yasujirō Ozu's films.
--
-- Why. The prompt change of 2026-11-14 (`273b6af`, data/text_to_sql.md: every crew filter tying a
-- person to a work excludes CREW_JOB 'Thanks' and 'In Memory Of') ships without a version bump, so
-- the cache still serves the 1.1.20 SQL written before it. "Map the filming locations of Yasujiro
-- Ozu's films" (iPad, 2026-11-14 18:10) brought West Berlin in through Ozu's "In Memory Of" credit on
-- Wings of Desire (1987). The evaluator is not concerned (retrieve_from_cache false); the fronts are.
--
-- What is retired, on API_VERSION 001.001.020 only:
--   (a) every live raw row whose QUESTION names Ozu (EN, FR, any form of the question);
--   (b) every row sharing the QUESTION_HASHED of an (a) row: its anonymized twin carries the hash of
--       the ORIGINAL question (maintenance/AGENTS.md, "Key facts about the cache");
--   (c) every live anonymized row whose QUESTION is one of those templates AND whose SQL is pre-fix
--       (a crew filter without the tribute exclusion): "{{Person_name1}}'s films" serves every person,
--       so a post-fix template, or one with no crew filter, stays.
-- Soft delete only (DELETED = 1), the convention of this folder; one UPDATE undoes it
-- (`SET DELETED = 0 WHERE TIM_UPDATED = <the run's timestamp> AND ID_USER_UPDATED = 1`).
--
-- ROUTING: UPDATE on T_WC_T2S_CACHE only, temporary tables, no DDL: voie 1.
--   ssh vps-agent pull fastapi-text2sql-blue
--   ssh vps-agent run fastapi-text2sql-blue/maintenance/cache-retire-386-ozu.sql

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Part 1. The hashes of the raw Ozu rows, and the pre-fix anonymized templates of those hashes.
CREATE TEMPORARY TABLE TMP_386_HASHES AS
SELECT DISTINCT QUESTION_HASHED AS H
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (IS_ANONYMIZED IS NULL OR IS_ANONYMIZED = 0)
  AND QUESTION LIKE '%Ozu%';

CREATE TEMPORARY TABLE TMP_386_TEMPLATES AS
SELECT DISTINCT T_WC_T2S_CACHE.QUESTION AS T
FROM T_WC_T2S_CACHE
JOIN TMP_386_HASHES ON T_WC_T2S_CACHE.QUESTION_HASHED = TMP_386_HASHES.H
WHERE T_WC_T2S_CACHE.API_VERSION = '001.001.020'
  AND (T_WC_T2S_CACHE.DELETED IS NULL OR T_WC_T2S_CACHE.DELETED = 0)
  AND T_WC_T2S_CACHE.IS_ANONYMIZED = 1;

SELECT (SELECT COUNT(*) FROM TMP_386_HASHES) AS RAW_HASHES,
       (SELECT COUNT(*) FROM TMP_386_TEMPLATES) AS ANONYMIZED_TEMPLATES;

-- Part 2. Before: the live rows that part 3 retires, one line each.
CREATE TEMPORARY TABLE TMP_386_ROWS AS
SELECT ID_ROW
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (QUESTION_HASHED IN (SELECT H FROM TMP_386_HASHES)
       OR (IS_ANONYMIZED = 1
           AND QUESTION COLLATE utf8mb4_bin IN (SELECT T COLLATE utf8mb4_bin FROM TMP_386_TEMPLATES)
           AND SQL_QUERY LIKE '%''crew''%'
           AND SQL_QUERY NOT LIKE '%In Memory Of%'));

SELECT c.ID_ROW, c.UI_LANGUAGE, c.IS_ANONYMIZED, c.DAT_CREAT, LEFT(c.QUESTION, 90) AS QUESTION,
       (c.SQL_QUERY LIKE '%In Memory Of%') AS POST_FIX
FROM T_WC_T2S_CACHE c JOIN TMP_386_ROWS r ON r.ID_ROW = c.ID_ROW
ORDER BY c.QUESTION_HASHED, c.IS_ANONYMIZED, c.ID_ROW;

-- Part 3. The write.
UPDATE T_WC_T2S_CACHE
SET DELETED = 1, TIM_UPDATED = NOW(), ID_USER_UPDATED = 1
WHERE ID_ROW IN (SELECT ID_ROW FROM TMP_386_ROWS)
  AND (DELETED IS NULL OR DELETED = 0);

SELECT ROW_COUNT() AS ROWS_RETIRED;

-- Part 4. After: no live raw Ozu row is left (expected 0).
SELECT COUNT(*) AS OZU_STILL_LIVE
FROM T_WC_T2S_CACHE
WHERE API_VERSION = '001.001.020'
  AND (DELETED IS NULL OR DELETED = 0)
  AND (IS_ANONYMIZED IS NULL OR IS_ANONYMIZED = 0)
  AND QUESTION LIKE '%Ozu%';
