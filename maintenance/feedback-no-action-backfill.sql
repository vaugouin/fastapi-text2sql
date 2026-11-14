-- feedback-no-action-backfill.sql
-- FASTAPI-TEXT2SQL-061, 2026-11-14: a thumbs up without a comment needs no analysis. Since this
-- date feedback.py records it as ANALYSIS_STATUS 'no_action'; this file moves the rows written
-- before the change (expected: ID_FEEDBACK 1 to 3) from 'new' to 'no_action'.
-- Voie 1 (agent account, T_WC_T2S_FEEDBACK is writable): ssh vps-agent run fastapi-text2sql-<colour>/maintenance/feedback-no-action-backfill.sql
-- Rerunnable: only 'new' rows with RATING > 0 and a blank comment are touched.

SELECT '0. Before: new thumbs up without a comment (expected 3)' AS SECTION;
SELECT ID_FEEDBACK, TIM_CREATED, CLIENT, RATING, COMMENT, ANALYSIS_STATUS
FROM T_WC_T2S_FEEDBACK
WHERE ANALYSIS_STATUS = 'new' AND RATING > 0 AND (COMMENT IS NULL OR TRIM(COMMENT) = '')
ORDER BY ID_FEEDBACK;

UPDATE T_WC_T2S_FEEDBACK
SET ANALYSIS_STATUS = 'no_action', TIM_UPDATED = NOW()
WHERE ANALYSIS_STATUS = 'new' AND RATING > 0 AND (COMMENT IS NULL OR TRIM(COMMENT) = '');

SELECT '1. After: every row, by status and rating' AS SECTION;
SELECT ANALYSIS_STATUS, RATING, COUNT(*) AS N
FROM T_WC_T2S_FEEDBACK
WHERE (DELETED IS NULL OR DELETED = 0)
GROUP BY ANALYSIS_STATUS, RATING
ORDER BY ANALYSIS_STATUS, RATING;
