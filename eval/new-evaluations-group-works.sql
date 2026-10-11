-- New evaluations for a group's works (FASTAPI-TEXT2SQL-325).
--
-- NOT YET APPLIED. Written 2026-10-11. 5 evaluations, English and French on each row.
--
-- WHY THIS FILE EXISTS
-- On Philippe's shoot of 2026-10-11 (voice-agent 1.2.18, take 11-46-42), "Which movies did
-- they make together?" about the Beatles returned five films, computed at question time by
-- intersecting the members' person credits, with the voice's own caveat that the list
-- included projects where only two members worked. tmdb-movie-preprocess process 74
-- (TMDB-MOVIE-PREPROCESS-059) now stores a group's works in T_WC_T2S_GROUP_MOVIE /
-- T_WC_T2S_GROUP_SERIE, and the prompt reads them. Per the backlog rule, the defect is
-- closed by evaluations WITH assertions, not by the ticket alone.
--
-- THE BANK BEFORE THIS FILE: three questions name these groups, 2226 (members of The
-- Beatles), 2232 (members of Monty Python) and 2234 (who were the Marx Brothers). All three
-- are MEMBERSHIP questions and all three already carry an assertion; none asks about the
-- works. So these five are new questions, not assertions added to old ones.
--
-- THE ANCHORS are TMDb ids, stable, read from earlier evaluation executions:
--   Life of Brian = ID_MOVIE 583, Monty Python and the Holy Grail = ID_MOVIE 762,
--   Monty Python's Flying Circus = ID_SERIE 849, A Hard Day's Night = ID_MOVIE 704,
--   Duck Soup = ID_MOVIE 3063. Section 1 prints them, and what process 74 stored for them.
--
-- WHAT EACH ASSERTION CHECKS
--   result: the works that must be there (coverage, extra rows never break it).
--   sql:    the answer is read from the group-works table, and never rebuilt by
--           intersecting person credits (no HAVING, no T_WC_T2S_PERSON_GROUP).
--   extraction: the group is extracted as Group_name1, and nothing else.
-- The ticket's "no row with a single member" holds by construction of the table (a work is
-- stored only with the group credited or at least two members), so it is asserted by the
-- SQL regex (the table is used) rather than on a column the result does not project.
-- "All four Beatles" asserts what must be there (A Hard Day's Night), not the observed list.
--
-- CATEGORY: 34, Persons - Group Queries, where the group questions already live.
-- RESOLUTION_MODE: standard, a works question must resolve without escalation.
--
-- RUN on the VPS, from the clone of the live colour, once the prompts are deployed AND
-- process 74 has built the two tables:
--   cd ~/docker/fastapi-text2sql-<colour> && git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-<colour>/eval/new-evaluations-group-works.sql
-- Every INSERT is guarded on the question text: a second run inserts nothing.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 0. Pre-flight: must return 0 rows (none of the five exists yet).
SELECT ID_T2S_EVALUATION, QUESTION FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN ('Which movies did Monty Python make together?',
                   'Which TV series did Monty Python make?',
                   'Which movies did the Beatles make together?',
                   'Which movies did all four Beatles appear in?',
                   'Movies by the Marx Brothers');

-- 1. Witnesses: the anchors, and what process 74 stored for them.
SELECT ID_MOVIE, MOVIE_TITLE, RELEASE_YEAR FROM T_WC_T2S_MOVIE WHERE ID_MOVIE IN (583, 762, 704, 3063);
SELECT ID_SERIE, SERIE_TITLE FROM T_WC_T2S_SERIE WHERE ID_SERIE = 849;
SELECT g.ID_GROUP, g.GROUP_NAME, g.PERSON_COUNT, gm.ID_MOVIE, gm.MEMBER_COUNT, gm.MEMBER_SHARE,
       gm.IS_GROUP_CREDITED, gm.CREDIT_KINDS, gm.DISPLAY_ORDER
FROM T_WC_T2S_GROUP_MOVIE gm JOIN T_WC_T2S_GROUP g ON g.ID_GROUP = gm.ID_GROUP
WHERE gm.ID_MOVIE IN (583, 762, 704, 3063) AND gm.DELETED = 0
ORDER BY g.GROUP_NAME, gm.DISPLAY_ORDER;
SELECT g.ID_GROUP, g.GROUP_NAME, g.PERSON_COUNT, gs.ID_SERIE, gs.MEMBER_COUNT, gs.MEMBER_SHARE,
       gs.IS_GROUP_CREDITED, gs.CREDIT_KINDS, gs.DISPLAY_ORDER
FROM T_WC_T2S_GROUP_SERIE gs JOIN T_WC_T2S_GROUP g ON g.ID_GROUP = gs.ID_GROUP
WHERE gs.ID_SERIE = 849 AND gs.DELETED = 0;

-- 2. The five evaluations.

-- 1. A troupe's films; the French form of the same row is the French evaluation.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies did Monty Python make together?', 'Quels films les Monty Python ont-ils faits ensemble ?',
       1, 0, 34, 0, CURDATE(), NOW(), 'standard',
       'seteq(entity_keys($), [&quot;Group_name1&quot;])',
       '(?is)^(?!.*HAVING).*T_WC_T2S_GROUP_MOVIE',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (583, 762)',
       'A group''s works are read from T_WC_T2S_GROUP_MOVIE (FASTAPI-TEXT2SQL-325), never rebuilt by intersecting the members'' credits: Life of Brian and Holy Grail must come out of the stored table.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies did Monty Python make together?') AS existing);

-- 2. The same troupe, series side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which TV series did Monty Python make?', 'Quelles séries les Monty Python ont-ils faites ?',
       1, 0, 34, 0, CURDATE(), NOW(), 'standard',
       'seteq(entity_keys($), [&quot;Group_name1&quot;])',
       '(?is)^(?!.*HAVING).*T_WC_T2S_GROUP_SERIE',
       'COUNT(*) &gt; 0 AND ID_SERIE IN (849)',
       'Series were not covered by the question-time intersection at all: the series side of a group''s works comes from T_WC_T2S_GROUP_SERIE, and Flying Circus must be there.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which TV series did Monty Python make?') AS existing);

-- 3. The question of the shoot.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies did the Beatles make together?', 'Quels films les Beatles ont-ils faits ensemble ?',
       1, 0, 34, 0, CURDATE(), NOW(), 'standard',
       'seteq(entity_keys($), [&quot;Group_name1&quot;])',
       '(?is)^(?!.*HAVING).*T_WC_T2S_GROUP_MOVIE',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (704)',
       'Asked on camera on 2026-10-11, answered by intersecting person credits with a caveat about two-member projects. The stored works answer it, A Hard Day''s Night first among them.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies did the Beatles make together?') AS existing);

-- 4. "All four": the counted form, where MEMBER_SHARE = 1 would demand Pete Best too.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies did all four Beatles appear in?', 'Dans quels films les quatre Beatles ont-ils tous joué ?',
       1, 0, 34, 0, CURDATE(), NOW(), 'standard',
       'seteq(entity_keys($), [&quot;Group_name1&quot;])',
       '(?is)^(?!.*HAVING).*T_WC_T2S_GROUP_MOVIE',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (704)',
       'A counted "all four" filters on MEMBER_COUNT (or the group credited), not on MEMBER_SHARE = 1: PERSON_COUNT includes Pete Best, so a share filter would empty the answer. A Hard Day''s Night, with the four of them, must remain.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Which movies did all four Beatles appear in?') AS existing);

-- 5. A neighbour of eval 2234 (who were the Marx Brothers), works side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, RESOLUTION_MODE, ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_SQL_QUERY,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Movies by the Marx Brothers', 'Films des Marx Brothers',
       1, 0, 34, 0, CURDATE(), NOW(), 'standard',
       'seteq(entity_keys($), [&quot;Group_name1&quot;]) AND matches($.Group_name1, /Marx Brothers/i)',
       '(?is)^(?!.*HAVING).*T_WC_T2S_GROUP_MOVIE',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (3063)',
       'The shortest form of a works question, with no verb: "movies by" a group reads its works, not a person filter on one brother. Duck Soup must be there.'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION = 'Movies by the Marx Brothers') AS existing);

-- 3. After-check: the five rows and their ids.
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY AS CAT, RESOLUTION_MODE, QUESTION, QUESTION_FR
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN ('Which movies did Monty Python make together?',
                   'Which TV series did Monty Python make?',
                   'Which movies did the Beatles make together?',
                   'Which movies did all four Beatles appear in?',
                   'Movies by the Marx Brothers')
ORDER BY ID_T2S_EVALUATION;
