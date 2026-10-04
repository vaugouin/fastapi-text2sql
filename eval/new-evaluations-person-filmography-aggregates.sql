-- ============================================================================
-- New evaluations: an aggregate over one person's filmography
-- ============================================================================
--
-- NOT YET APPLIED. 2 evaluations, English and French, categories 12 and 10.
-- No evaluation id is assumed anywhere: both rows take the next AUTO_INCREMENT value,
-- every guard and every check reads them back by their English QUESTION, and section 3
-- prints the ids they actually received.
--
-- WHY THIS FILE EXISTS
-- Found on 2026-10-04 on Green (1.1.19), while verifying FASTAPI-TEXT2SQL-308, with two
-- questions sent with store_to_cache=false. Neither escalated (complex_model_used false),
-- both returned 29 rows, both were wrong:
--
--   * "average runtime of Christopher Nolan movies" averaged RUNTIME PER TECHNICAL FORMAT:
--     FROM T_WC_T2S_TECHNICAL ... GROUP BY t.ID_TECHNICAL, 29 rows (119.57, 75.27, 69, ...).
--     The question asks for one number. Reading of the cause (interpretation, not tested):
--     the SQL prompt has a single-total rule for COUNT only ("A single total answers with one
--     cell", data/text_to_sql.md), and nothing for AVG or SUM, so the model fell back on the
--     "entity rows with the aggregate as an extra column" rule and picked an entity to group by.
--   * "average IMDb rating of Stanley Kubrick movies per decade" searched Kubrick as CAST
--     (CREDIT_TYPE = 'cast'), then put a window AVG() OVER (PARTITION BY decade) on every
--     movie row. Result: his cameos and the documentaries about him, decades 1940 to 2020,
--     one row per film. The question asks for one row per decade of the films he directed.
--
-- The rule of this project: an API defect closes with an evaluation, not a ticket alone.
-- Checked before writing, per the three ordered questions (does the question exist / does it
-- carry an assertion / would that assertion have caught THIS defect), on the bank exported to
-- shared_data/text2sql-eval/evaluation on 2026-10-04:
--   * no question asks for an average over a person's films; the Nolan and Kubrick questions
--     in the bank (8, 541, 553, 568, ...) all list movies, and their ID_MOVIE IN (...)
--     assertions could never see an aggregate going wrong;
--   * 261 "What's the average movie budget by decade?" is the only decade aggregate, has no
--     category and no assertion, and names nobody.
-- So: no question covers either case. Gesture = write the evaluations, with assertions.
--
-- WHAT THE ASSERTIONS PROTECT
-- No entity id and no result column name is asserted, on purpose: the alias of an aggregate
-- is the model's choice (AVERAGE_RUNTIME, AVG_RUNTIME, DECADE_AVG_IMDB_RATING were all
-- observed), and the README 4.3 language has no way to say "whichever column". The shape is
-- carried by COUNT(*), the meaning by a SQL regex.
--
--   Nolan, ASSERTIONS_QUERY_RESULT  COUNT(*) == 1
--     The defect returned 29 rows. One number is one row, whatever its alias.
--   Nolan, ASSERTIONS_SQL_QUERY     AVG over RUNTIME, a director filter, no GROUP BY,
--                                   never CREDIT_TYPE = 'cast'.
--     The director filter is the trap a correct-looking query falls into: "Nolan movies"
--     filtered on CREDIT_TYPE = 'crew' alone also averages the films he only PRODUCED
--     (Man of Steel, Transcendence, ...). Director or Directing are both accepted, as
--     CREW_JOB = 'Director' and CREW_DEPARTMENT = 'Directing' are both used in the prompt.
--
--   Kubrick, ASSERTIONS_QUERY_RESULT  COUNT(*) >= 5 AND COUNT(*) <= 6
--     He directed in five decades, 1950s to 1990s (section 1b recomputes it). The per-film
--     shape returns 13 rows or more, the cast shape seven decades or more: both fail. The
--     upper bound tolerates a sixth row for a film with no RELEASE_YEAR, the one legitimate
--     way for a correct query to return more than five.
--   Kubrick, ASSERTIONS_SQL_QUERY     AVG over IMDB_RATING, a director filter, never
--                                     CREDIT_TYPE = 'cast'.
--     GROUP BY is NOT required: SELECT DISTINCT decade, AVG() OVER (PARTITION BY decade)
--     is a correct five-row answer, and COUNT(*) already rejects the per-film window.
--     IMDB_RATING is matched as a whole word, so an average of IMDB_RATING_WEIGHTED fails:
--     the question asks for the IMDb rating, not the house's weighted ranking score.
--
-- The regexes follow the house style (assertions-groupby-columns.sql): (?is), lookaheads,
-- backslashes doubled for the MariaDB string literal, the quote written \x27. Each is anchored
-- with \A so the negative lookaheads are tested once, from the start of the SQL, and not at
-- every position re.search() tries.
--
-- RESOLUTION_MODE 'standard': two factual joins, both must resolve without escalation.
-- ASSERTIONS_ENTITY_EXTRACTION stays NULL: never measured on these two questions, and the
-- house method for an extraction assertion is three passes in each language.
-- No ASSERTION_REFRESH_SQL: nothing here is an id list to refresh.
--
-- HOW TO RUN (VPS, live colour clone):
--   cd ~/docker/fastapi-text2sql-green
--   git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-green/eval/new-evaluations-person-filmography-aggregates.sql
-- Read sections 0 and 1 in the result before trusting section 2: if 1b does not show five
-- decades, the Kubrick bounds must be corrected and the file re-run (the guard makes a second
-- run skip what the first one inserted, so correct with an UPDATE guarded on the old value).
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. Before. Must return zero rows; a row means the question already exists and the
--    INSERT guard will skip it.
-- ---------------------------------------------------------------------------
SELECT '0. State before insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 80) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'What is the average runtime of Christopher Nolan movies?',
  'What is the average IMDb rating of Stanley Kubrick movies per decade?'
);

-- ---------------------------------------------------------------------------
-- 1. The reference answers, computed by name. Read them BEFORE inserting.
-- ---------------------------------------------------------------------------

-- 1a. Homonyms. One row per name is expected; two would mean the questions are ambiguous.
SELECT '1a. Person rows behind the two names' AS SECTION;

SELECT T_WC_T2S_PERSON.ID_PERSON, T_WC_T2S_PERSON.PERSON_NAME,
       T_WC_T2S_PERSON.KNOWN_FOR_DEPARTMENT, T_WC_T2S_PERSON.BIRTH_YEAR
FROM T_WC_T2S_PERSON
WHERE T_WC_T2S_PERSON.PERSON_NAME IN ('Christopher Nolan', 'Stanley Kubrick');

-- 1b. Kubrick as director, one row per decade. Five rows expected (1950 to 1990).
SELECT '1b. Kubrick, average IMDb rating per decade, as director' AS SECTION;

SELECT FLOOR(T_WC_T2S_MOVIE.RELEASE_YEAR / 10) * 10 AS DECADE,
       COUNT(DISTINCT T_WC_T2S_MOVIE.ID_MOVIE) AS FILMS,
       ROUND(AVG(T_WC_T2S_MOVIE.IMDB_RATING), 2) AS AVG_IMDB_RATING
FROM T_WC_T2S_MOVIE
WHERE EXISTS (
  SELECT 1 FROM T_WC_T2S_PERSON_MOVIE
  JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON
  WHERE T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE
    AND T_WC_T2S_PERSON.PERSON_NAME = 'Stanley Kubrick'
    AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew'
    AND T_WC_T2S_PERSON_MOVIE.CREW_JOB = 'Director')
GROUP BY FLOOR(T_WC_T2S_MOVIE.RELEASE_YEAR / 10) * 10
ORDER BY DECADE;

-- 1c. The defective shape, for contrast: Kubrick as cast spans more decades than six,
--     which is what makes the upper bound bite.
SELECT '1c. Kubrick as cast, number of decades (must exceed 6)' AS SECTION;

SELECT COUNT(DISTINCT FLOOR(T_WC_T2S_MOVIE.RELEASE_YEAR / 10)) AS DECADES_AS_CAST
FROM T_WC_T2S_MOVIE
JOIN T_WC_T2S_PERSON_MOVIE ON T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE
JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON
WHERE T_WC_T2S_PERSON.PERSON_NAME = 'Stanley Kubrick'
  AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'cast';

-- 1d. Nolan as director against Nolan in any crew role: the gap is what the director
--     filter of the regex protects.
SELECT '1d. Nolan, average runtime as director vs any crew role' AS SECTION;

SELECT 'director' AS SCOPE, COUNT(DISTINCT T_WC_T2S_MOVIE.ID_MOVIE) AS FILMS,
       ROUND(AVG(T_WC_T2S_MOVIE.RUNTIME), 1) AS AVG_RUNTIME
FROM T_WC_T2S_MOVIE
WHERE EXISTS (
  SELECT 1 FROM T_WC_T2S_PERSON_MOVIE
  JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON
  WHERE T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE
    AND T_WC_T2S_PERSON.PERSON_NAME = 'Christopher Nolan'
    AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew'
    AND T_WC_T2S_PERSON_MOVIE.CREW_JOB = 'Director')
UNION ALL
SELECT 'any crew role', COUNT(DISTINCT T_WC_T2S_MOVIE.ID_MOVIE),
       ROUND(AVG(T_WC_T2S_MOVIE.RUNTIME), 1)
FROM T_WC_T2S_MOVIE
WHERE EXISTS (
  SELECT 1 FROM T_WC_T2S_PERSON_MOVIE
  JOIN T_WC_T2S_PERSON ON T_WC_T2S_PERSON.ID_PERSON = T_WC_T2S_PERSON_MOVIE.ID_PERSON
  WHERE T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE
    AND T_WC_T2S_PERSON.PERSON_NAME = 'Christopher Nolan'
    AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew');

-- ---------------------------------------------------------------------------
-- 2. The evaluations. INSERT ... SELECT guarded by NOT EXISTS on the English question,
--    the guard wrapped in a derived table so MySQL error 1093 does not fire.
-- ---------------------------------------------------------------------------

-- ===== category 12: Movies - Complex queries =====
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE,
   ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'What is the average runtime of Christopher Nolan movies?',
       'Quelle est la durée moyenne des films de Christopher Nolan ?',
       1, 0, 12, 0, CURDATE(), NOW(), 'standard',
       '(?is)\\A(?=.*\\bAVG\\s*\\(\\s*(?:DISTINCT\\s+)?(?:\\w+\\.)?RUNTIME\\b)(?=.*\\b(?:Director|Directing)\\b)(?!.*\\bGROUP\\s+BY\\b)(?!.*\\bCREDIT_TYPE\\s*=\\s*\\x27cast\\x27)',
       'COUNT(*) == 1',
       'An average over one person''s films is a single number: one row, no GROUP BY. Grouping by another entity (observed: one average per technical format, 29 rows) answers a question nobody asked. The films are those he directed, not every film he worked on as crew.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is the average runtime of Christopher Nolan movies?') AS existing);

-- ===== category 10: Movies - Time-based queries =====
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE,
   ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'What is the average IMDb rating of Stanley Kubrick movies per decade?',
       'Quelle est la note IMDb moyenne des films de Stanley Kubrick par décennie ?',
       1, 0, 10, 0, CURDATE(), NOW(), 'standard',
       '(?is)\\A(?=.*\\bAVG\\s*\\(\\s*(?:DISTINCT\\s+)?(?:\\w+\\.)?IMDB_RATING\\b)(?=.*\\b(?:Director|Directing)\\b)(?!.*\\bCREDIT_TYPE\\s*=\\s*\\x27cast\\x27)',
       'COUNT(*) &gt;= 5 AND COUNT(*) &lt;= 6',
       'A director''s movies are the films he directed: searched as cast, Kubrick brings his cameos and every documentary about him, decades 1940 to 2020. Per decade means one row per decade, not the decade average repeated on every film.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is the average IMDb rating of Stanley Kubrick movies per decade?') AS existing);

-- ---------------------------------------------------------------------------
-- 3. After. Two rows, with the ids they received: these are the ids to run with
--    Phase 11 and to quote in the backlog.
-- ---------------------------------------------------------------------------
SELECT '3. State after insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, RESOLUTION_MODE,
       ASSERTIONS_QUERY_RESULT, ASSERTIONS_SQL_QUERY, LEFT(QUESTION, 80) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'What is the average runtime of Christopher Nolan movies?',
  'What is the average IMDb rating of Stanley Kubrick movies per decade?'
);
