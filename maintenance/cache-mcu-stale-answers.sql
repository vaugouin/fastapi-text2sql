-- MCU collection rebuilt on 2026-10-31: retire the cache rows whose stored ANSWER still says the old membership.
--
-- Why. Until 2026-10-31 the custom collection "Marvel Cinematic Universe (MCU)" (T_WC_CUSTOM_LIST 49, T2S
-- collection 4817) held every Marvel film from Howard the Duck (1986) to Logan (2017), 73 films, no series
-- (TMDB-MOVIE-PREPROCESS-057). The list was rewritten to the MCU proper (tmdb-movie-preprocess
-- doc/sql/custom-collection-mcu.sql) and process 41 rebuilt the collection at 20:55: 54 films, 36 series,
-- Iron Man first.
--
-- What a cache hit replays. A hit reuses SQL_QUERY and executes it again, so a list question heals by itself:
-- "the MCU films in release order" now returns Iron Man first without touching the cache. What does NOT heal is
-- the ANSWER column, the sentence the single-value model wrote from the old rows ("8,904 minutes, just over
-- 6 days"), served as is on the next hit. Those rows are the target. Soft delete only (DELETED = 1), the
-- convention of this folder: every lookup filters DELETED = 0, and a single UPDATE undoes it.
--
-- Part 1 reads, part 2 writes T_WC_T2S_CACHE only (voie 1). Run part 1 alone first if in doubt.
--   ssh vps-agent pull fastapi-text2sql-green
--   ssh vps-agent run fastapi-text2sql-green/maintenance/cache-mcu-stale-answers.sql

-- Part 1. The live rows that mention the MCU or Marvel, raw and anonymized, with what they would replay
SELECT ID_ROW, API_VERSION, UI_LANGUAGE, IS_ANONYMIZED, DAT_CREAT, RESULT_ENTITY,
       LEFT(QUESTION, 90) AS QUESTION, LEFT(ANSWER, 120) AS ANSWER
FROM T_WC_T2S_CACHE
WHERE DELETED = 0
  AND (QUESTION LIKE '%Marvel%' OR QUESTION LIKE '%MCU%'
       OR SQL_PROCESSED LIKE '%Marvel%' OR ANSWER LIKE '%Marvel%')
ORDER BY DAT_CREAT, ID_ROW;

-- Part 2. Retire those whose ANSWER carries a value computed from the old membership (a non-empty ANSWER).
-- Rows with an empty ANSWER are list answers: their SQL re-executes on the hit, nothing stale to retire.
UPDATE T_WC_T2S_CACHE
SET DELETED = 1, TIM_UPDATED = NOW(), ID_USER_UPDATED = 1
WHERE DELETED = 0
  AND (QUESTION LIKE '%Marvel%' OR QUESTION LIKE '%MCU%'
       OR SQL_PROCESSED LIKE '%Marvel%' OR ANSWER LIKE '%Marvel%')
  AND ANSWER IS NOT NULL AND ANSWER <> '';

-- Part 3. After: what is left live
SELECT COUNT(*) AS LIVE_MARVEL_ROWS, SUM(ANSWER IS NOT NULL AND ANSWER <> '') AS WITH_ANSWER
FROM T_WC_T2S_CACHE
WHERE DELETED = 0
  AND (QUESTION LIKE '%Marvel%' OR QUESTION LIKE '%MCU%'
       OR SQL_PROCESSED LIKE '%Marvel%' OR ANSWER LIKE '%Marvel%');
