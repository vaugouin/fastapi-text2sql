-- FASTAPI-TEXT2SQL-061, 2026-11-12: T_WC_T2S_FEEDBACK, the user ratings of search answers.
--
-- One row per POST /feedback: a thumbs up (RATING 1) or a thumbs down (RATING -1) with an
-- optional comment, sent by t2s-front or voice-agent, tied to the answer it rates by
-- QUESTION_HASHED (the cache key of the question) and REQUEST_ID (the request_id of the
-- /search/text2sql response, also at the top of its JSON journal). The analysis fields
-- (ANALYSIS_STATUS new / analysed / fixed / not_a_defect, ANALYSIS_NOTE, TICKET_ID,
-- EVALUATION_IDS, TIM_ANALYSED) are filled later by the analysis (TEXT2SQL-EVAL-006).
-- While a thumbs down is 'new' or 'analysed', the search route bypasses the cache for that
-- question (feedback.f_has_open_negative_feedback); the cache rows are never modified.
-- feedback.py degrades silently (error 1146) until this runs: the code can be deployed
-- before or after it. Dates are Paris time, written by the API (logs.now_paris()).
--
-- ROUTING: DDL and a GRANT, so route 2 (the agent account has neither):
--   cd ~/docker/fastapi-text2sql-blue && git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-blue/doc/sql/T_WC_T2S_FEEDBACK.sql
-- (the clone of the colour in service, -blue or -green).
--
-- Then, for the analysis to write its fields from the agent account: add T_WC_T2S_FEEDBACK
-- to the tables of tools/createagentvaugouindb.sh and run it with --apply (separate step).

CREATE TABLE IF NOT EXISTS `T_WC_T2S_FEEDBACK` (
  `ID_FEEDBACK` int(11) NOT NULL AUTO_INCREMENT,
  `REQUEST_ID` varchar(64) DEFAULT NULL,
  `QUESTION` mediumtext DEFAULT NULL,
  `QUESTION_HASHED` varchar(64) DEFAULT NULL,
  `UI_LANGUAGE` varchar(5) DEFAULT NULL,
  `API_VERSION` varchar(20) DEFAULT NULL,
  `CLIENT` varchar(30) DEFAULT NULL,
  `RATING` tinyint(4) DEFAULT NULL,
  `COMMENT` text DEFAULT NULL,
  `SQL_QUERY` mediumtext DEFAULT NULL,
  `RESULT_ENTITY` varchar(50) DEFAULT NULL,
  `ANALYSIS_STATUS` varchar(20) NOT NULL DEFAULT 'new',
  `ANALYSIS_NOTE` mediumtext DEFAULT NULL,
  `TICKET_ID` varchar(50) DEFAULT NULL,
  `EVALUATION_IDS` varchar(500) DEFAULT NULL,
  `TIM_ANALYSED` datetime DEFAULT NULL,
  `DELETED` int(5) DEFAULT 0,
  `DAT_CREAT` date DEFAULT NULL,
  `TIM_CREATED` datetime DEFAULT NULL,
  `TIM_UPDATED` datetime DEFAULT NULL,
  PRIMARY KEY (`ID_FEEDBACK`),
  KEY `QUESTION_HASHED` (`QUESTION_HASHED`),
  KEY `REQUEST_ID` (`REQUEST_ID`),
  KEY `ANALYSIS_STATUS` (`ANALYSIS_STATUS`),
  KEY `RATING` (`RATING`),
  KEY `TIM_CREATED` (`TIM_CREATED`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The API account must be able to write it, or every POST /feedback answers 503 and the
-- bypass check stays silently off (maintenance/AGENTS.md: a table is born readable and not
-- writable, error 1142). No DELETE: a rating is soft-deleted with DELETED = 1.
GRANT SELECT, INSERT, UPDATE ON vaugouindb.T_WC_T2S_FEEDBACK TO 'moviematchro'@'%';
FLUSH PRIVILEGES;

-- Check: the table, its grant, and its rows (0 right after).
SHOW CREATE TABLE T_WC_T2S_FEEDBACK;
SHOW GRANTS FOR 'moviematchro'@'%';
SELECT COUNT(*) AS feedback_rows FROM T_WC_T2S_FEEDBACK;
