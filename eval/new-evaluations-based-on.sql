-- New evaluations for "based on" (FASTAPI-TEXT2SQL-320).
--
-- NOT YET APPLIED. Written 2026-10-09. 10 evaluations, English and French.
--
-- WHY THIS FILE EXISTS
-- tmdb-movie-preprocess process 73 (TMDB-MOVIE-PREPROCESS-055) built the "based on"
-- read-model on 2026-10-09: T_WC_T2S_SOURCE_WORK (17,464 sources) and the link tables
-- T_WC_T2S_MOVIE_SOURCE_WORK / T_WC_T2S_SERIE_SOURCE_WORK (25,234 links). The prompts
-- learn the tables in the same commit. These ten questions were chosen with Philippe on
-- 2026-10-09, each for a different way of failing: the right side being a movie (1), a
-- mixed answer novel + movie (2), right side movie with left side series (3), the hop to
-- the source's own columns (4), a ranking across kinds (5), the type filter on both sides
-- (6), the form filter asked in French and not confused with the Music genre (7), the
-- source found by its French name (8), the frontier with the "true story" topic (9), and
-- an honest empty answer (10).
--
-- THE ANCHORS were read on the live base on 2026-10-09 (tmdb-movie-preprocess,
-- doc/sql/test-055-post-run-20261009.txt, third run): ID_SOURCE_WORK is stable across
-- rebuilds (checked on the second and third runs), so it can be an anchor.
--   Scarface 1983 = ID_MOVIE 111; its sources = ID_SOURCE_WORK 7931 (the 1930 novel) and
--   11891 (the 1932 movie, ID_MOVIE 877). Fargo the series = ID_SERIE 60622 (adapted from
--   the movie). Apocalypse Now = ID_MOVIE 28 (adapted from Heart of Darkness, source 3909).
--   The topic "based on true story" = ID_TOPIC 18014. Pulp Fiction = ID_MOVIE 680, no
--   source.
--
-- CATEGORIES: no "adaptations" category exists. Movies basic (2) for the plain movie
-- questions, TV basic (6) for the series one, Movies complex (12) for the comparison,
-- Movies and TV series (17) for the mixed ones, Movies topics (9) for the frontier, and
-- Movies cast & crew (4), the historical home of the adaptation questions, for the
-- named-source ones. A dedicated category (next free id 63) is worth creating once these
-- ten have run.
--
-- RUN on the VPS, from the clone of the live colour, once the prompts are deployed:
--   cd ~/docker/fastapi-text2sql-<colour> && git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-<colour>/eval/new-evaluations-based-on.sql
-- Every INSERT is guarded on the question text: a second run inserts nothing.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 0. Pre-flight: must return 0 rows (none of the ten exists yet).
SELECT ID_T2S_EVALUATION, QUESTION FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN ('Which movies are remakes of Scarface (1932)?',
                   'What is Scarface (1983) based on?',
                   'Which TV series are adapted from a movie?',
                   'Which movies adapted from a TV series are rated higher than the series?',
                   'Which work has been adapted the most, movies and series together?',
                   'Movies and TV series based on video games',
                   'Movies adapted from a musical',
                   'Which movies are adapted from Heart of Darkness?',
                   'Movies based on a true story',
                   'What is Pulp Fiction based on?');

-- 1. Witnesses: the anchors as they stand today.
SELECT sw.ID_SOURCE_WORK, sw.SOURCE_WORK_NAME, sw.SOURCE_WORK_TYPE, sw.SOURCE_WORK_YEAR, sw.ID_MOVIE
FROM T_WC_T2S_SOURCE_WORK sw WHERE sw.ID_SOURCE_WORK IN (7931, 11891, 3909);
SELECT ID_MOVIE, MOVIE_TITLE, RELEASE_YEAR FROM T_WC_T2S_MOVIE WHERE ID_MOVIE IN (111, 877, 28, 680);
SELECT ID_SERIE, SERIE_TITLE FROM T_WC_T2S_SERIE WHERE ID_SERIE = 60622;
SELECT ID_TOPIC, TOPIC_NAME FROM T_WC_T2S_TOPIC WHERE ID_TOPIC = 18014;

-- 2. The ten evaluations.

-- 1. The right side is a movie: remakes reach the 1932 film through SOURCE_WORK.ID_MOVIE.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies are remakes of Scarface (1932)?', 'Quels films sont des remakes de Scarface (1932) ?',
       1, 0, 2, 0, CURDATE(), NOW(),
       '(?i)T_WC_T2S_MOVIE_SOURCE_WORK',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (111)',
       'A remake is a movie whose source is a movie: the source-work row of the 1932 film carries its ID_MOVIE, and the 1983 film must come out through that hop, not through a title match.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies are remakes of Scarface (1932)?') AS existing);

-- 2. A mixed answer: a novel and a movie, from the same join.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'What is Scarface (1983) based on?', 'De quoi est adapté Scarface (1983) ?',
       1, 0, 2, 0, CURDATE(), NOW(),
       '(?i)T_WC_T2S_SOURCE_WORK',
       'COUNT(*) &gt;= 2 AND ID_SOURCE_WORK IN (7931, 11891)',
       'One work, two sources of different kinds (the 1930 novel and the 1932 movie): both come from the single source-work join, none may be lost to a branch per kind.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'What is Scarface (1983) based on?') AS existing);

-- 3. Right side movie, left side series.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which TV series are adapted from a movie?', 'Quelles séries sont adaptées d''un film ?',
       1, 0, 6, 0, CURDATE(), NOW(),
       '(?i)T_WC_T2S_SERIE_SOURCE_WORK',
       'COUNT(*) &gt; 0 AND ID_SERIE IN (60622)',
       'The work studied is a series, the source a movie: the series link table with a movie source (Fargo, from the 1996 film).'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which TV series are adapted from a movie?') AS existing);

-- 4. The hop to the source's own columns (its rating).
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies adapted from a TV series are rated higher than the series?',
       'Quels films adaptés d''une série sont mieux notés que la série ?',
       1, 0, 12, 0, CURDATE(), NOW(),
       '(?is)T_WC_T2S_SOURCE_WORK.*ID_SERIE',
       'COUNT(*) &gt; 0',
       'Comparing a work with its source needs the source''s own rating: the query must hop from the source-work row to the T2S series through SOURCE_WORK.ID_SERIE.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies adapted from a TV series are rated higher than the series?') AS existing);

-- 5. A ranking across kinds; the anchor is refreshed every day.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL, LONG_DESC)
SELECT 'Which work has been adapted the most, movies and series together?',
       'Quelle œuvre a été la plus adaptée, films et séries confondus ?',
       1, 0, 17, 0, CURDATE(), NOW(),
       '(?i)T_WC_T2S_SOURCE_WORK',
       'COUNT(*) &gt; 0',
       'SELECT ID_SOURCE_WORK FROM T_WC_T2S_SOURCE_WORK WHERE DELETED = 0 ORDER BY MOVIE_COUNT + SERIE_COUNT DESC, ID_SOURCE_WORK ASC LIMIT 1',
       'Novels, movies and plays ranked on one scale: only possible because every source sits in one table. The most adapted work moves with the data, hence the refresh SQL.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which work has been adapted the most, movies and series together?') AS existing);

-- 6. The type filter, on both sides (the showcase question n° 19).
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Movies and TV series based on video games', 'Films et séries adaptés de jeux vidéo',
       1, 0, 17, 0, CURDATE(), NOW(),
       '(?i)SOURCE_WORK_TYPE ?= ?''game''',
       'COUNT(*) &gt; 0',
       'The kind of source is a filter on SOURCE_WORK_TYPE, never a topic or a keyword: 145 movies and 244 series on 2026-10-09.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Movies and TV series based on video games') AS existing);

-- 7. The form filter, in French, not confused with the Music genre.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Movies adapted from a musical', 'Films adaptés d''une comédie musicale',
       1, 0, 4, 0, CURDATE(), NOW(),
       '(?is)^(?!.*GENRE).*SOURCE_WORK_FORM ?= ?''musical''',
       'COUNT(*) &gt; 0',
       'A musical source is the form of the source work, not the Music genre of the movie: the SQL filters SOURCE_WORK_FORM and never a genre.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Movies adapted from a musical') AS existing);

-- 8. The source found by its name, French included.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies are adapted from Heart of Darkness?', 'Quels films sont adaptés d''Au cœur des ténèbres ?',
       1, 0, 4, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Source_work_name1&quot;])',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (28)',
       'A named source is a Source_work_name, matched on SOURCE_WORK_NAME or SOURCE_WORK_NAME_FR: Apocalypse Now shares no word with Conrad''s title, so only the source-work link can find it.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies are adapted from Heart of Darkness?') AS existing);

-- 9. The frontier: a true story is a topic, not a source work.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Movies based on a true story', 'Films inspirés d''une histoire vraie',
       1, 0, 9, 0, CURDATE(), NOW(),
       '(?is)^(?!.*SOURCE_WORK).*T_WC_T2S_TOPIC',
       'COUNT(*) &gt; 0',
       'No work is named in "based on a true story": it stays on the topic (2,428 movies), and must not be pulled into the source-work tables by the words "based on".'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Movies based on a true story') AS existing);

-- 10. An honest empty answer.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'What is Pulp Fiction based on?', 'De quoi est adapté Pulp Fiction ?',
       1, 0, 2, 0, CURDATE(), NOW(),
       '(?i)T_WC_T2S_SOURCE_WORK',
       'COUNT(*) == 0',
       'An original screenplay has no source: the query asks the source-work tables and gets nothing, rather than inventing a novel.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'What is Pulp Fiction based on?') AS existing);

-- 3. After-check: the ten rows and their ids.
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY AS CAT, QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN ('Which movies are remakes of Scarface (1932)?',
                   'What is Scarface (1983) based on?',
                   'Which TV series are adapted from a movie?',
                   'Which movies adapted from a TV series are rated higher than the series?',
                   'Which work has been adapted the most, movies and series together?',
                   'Movies and TV series based on video games',
                   'Movies adapted from a musical',
                   'Which movies are adapted from Heart of Darkness?',
                   'Movies based on a true story',
                   'What is Pulp Fiction based on?')
ORDER BY ID_T2S_EVALUATION;
