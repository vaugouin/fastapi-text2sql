-- New evaluations closing FASTAPI-TEXT2SQL-211 (person-role collapse).
--
-- APPLIED 2026-08-26. 4 evaluations, English and French, across 2 categories, run in
-- both languages on 001.001.018 as executions 7064 to 7071. Section 1 is spent; section 4
-- is what the run itself made necessary and is NOT yet applied.
--
-- WHY THIS FILE EXISTS
-- On 2026-08-25, "La costumière du film Capote avec Philip seymour Hofmann" returned zero
-- rows four times running. Entity extraction was perfect, resolution was perfect, the SQL
-- was valid and executed without error. What it asked for was impossible: the generator had
-- folded the person being LISTED (the costume designer, designated by a role) into the
-- person being NAMED (the actor, a property of the film), so the query read "give me the
-- costume designer, provided she is Philip Seymour Hoffman".
--
-- The rule of this project is that an API defect closes with an evaluation, not with a
-- ticket alone. The check was run before writing this file, per the three ordered questions
-- (does the question exist / does it carry an assertion / would that assertion have caught
-- THIS defect):
--
--   * 15 questions in the bank name a role AND a person ("Movies directed by Scorsese with
--     Joe Pesci", ids 13, 97, 490, 539, 541, 542, 2164, ...). Every one of them answers with
--     MOVIES. The named person and the role both filter the same result. They cannot express
--     the collapse and could never have caught it.
--   * Category 27 (persons cast/crew) holds 20 questions, all 20 with a query_result
--     assertion, and not one names a second person: id 364, "Who did the cinematography on
--     the movie Le mépris?", is the closest and names nobody else.
--   * So: no question covers the case. Geste = write the evaluation, with its assertion.
--
-- WHAT THE ASSERTIONS PROTECT
-- Two clauses, and the second is the durable one.
--   COUNT(*) &gt; 0            catches the defect head-on. An empty DataFrame satisfies only
--                            "COUNT(*) == 0" written exactly so, and the collapse returns
--                            exactly zero rows, so this floor goes red the day it returns.
--   PERSON_NAME NOT IN (...)  states the invariant rather than the symptom: the answer to
--                            "the <role> of <film> with <actor>" is NEVER that actor. It
--                            holds whoever the costume designer turns out to be, so it
--                            survives a database refresh, and it stays red if a future
--                            generator collapses the roles the other way round.
-- Neither clause names an ID, on purpose: no anchor to re-verify, nothing to maintain.
--
-- ASSERTIONS_ENTITY_EXTRACTION IS LEFT NULL
-- The Capote question is observed extracting {Movie_title1, Person_name1} (usage log
-- 20260825-180913), but the other three have never been measured, and the house method for
-- an extraction assertion is three passes on each of the two languages. Do not assert what
-- has not been run. Section 3 holds a ready-to-edit block.
--
-- RE-RUN GUARD
-- Each INSERT is an INSERT ... SELECT guarded by NOT EXISTS on the English question, wrapped
-- in a derived table so MySQL error 1093 (reading the table being inserted into) does not
-- fire. Same idiom as new-evaluations-entity-types.sql; like that file, it has NOT been
-- executed against a server from this machine. Run section 0 first, then one single INSERT,
-- then section 0 again.
--
-- WHAT THE FIRST RUN FOUND (2026-08-26, executions 7064-7071)
-- Eight green out of eight, and three of the four for the right reasons: the generated SQL
-- carries the EXISTS form of the prompt rule, aliases included, and returns real people
-- (Kasia Walicka Maimone and Aldo Signoretti on Capote, Michael Chapman on Taxi Driver,
-- Vince Gilligan on Breaking Bad), in English and in French alike.
--
-- The counter-example, 2476, was green for the WRONG reason, and that is the finding.
-- English returns 1 row, Quentin Tarantino, through two aliased instances. French returns
-- 37, the director plus the whole cast, because it wrote the two credit filters as an OR on
-- a single instance: the "et" of the question became a disjunction. Its justification claims
-- the conjunction the SQL does not implement.
--
-- COUNT(*) &gt; 0 could not see it. That is the trap this project already named: a toothless
-- assertion is worse than an absent one, because an absence at least shows. Section 4 gives
-- it teeth, using an anchor taken from the observed English run. It will turn the French side
-- RED on purpose, and it must stay red until the prompt rule for the conjunctive form (added
-- to data/text_to_sql.md the same day, "The mirror case: ONE person in TWO roles") has been
-- exercised by a fresh run.


-- ---------------------------------------------------------------------------
-- 0. Pre-flight. Run this FIRST. It must return zero rows.
--    A row here means the question is already in the bank and section 1 will
--    skip it, which is the guard doing its job, not a problem.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Who is the costume designer of the movie Capote with Philip Seymour Hoffman?',
  'Who is the cinematographer of the movie Taxi Driver with Robert De Niro?',
  'Who created the TV series Breaking Bad with Bryan Cranston?',
  'Who both directed and acted in the movie Pulp Fiction?'
);


-- ---------------------------------------------------------------------------
-- 1. The new evaluations
-- ---------------------------------------------------------------------------

-- ===== category 27: Persons - Cast & Crew queries =====

-- The defect itself, in the words that produced it. Crew role on the movie side, qualified
-- by a cast member named in the same sentence.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is the costume designer of the movie Capote with Philip Seymour Hoffman?',
       'Qui est la costumière du film Capote avec Philip Seymour Hoffman ?',
       1, 0, 27, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND PERSON_NAME NOT IN (''Philip Seymour Hoffman'')',
       'A named actor qualifies the FILM, never the person returned. The two people must not share a join instance, or the query asks for a costume designer who is Philip Seymour Hoffman and returns nothing.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is the costume designer of the movie Capote with Philip Seymour Hoffman?') AS existing);

-- The same shape on another department, so the rule is tested beyond costumes. Title
-- identical in both languages on purpose: the *_FR title columns are less populated, and an
-- assertion calibrated on English can punish a French answer that is merely narrower.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is the cinematographer of the movie Taxi Driver with Robert De Niro?',
       'Qui est le directeur de la photographie du film Taxi Driver avec Robert De Niro ?',
       1, 0, 27, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND PERSON_NAME NOT IN (''Robert De Niro'')',
       'Same invariant as the costume-designer case, on a different crew department, so the rule is not learned for one department only.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is the cinematographer of the movie Taxi Driver with Robert De Niro?') AS existing);

-- The counter-example, and it is the reason the fix must not overshoot. One human really
-- does hold two roles here, so the shape the guard treats as suspicious is legitimate and
-- must keep answering.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who both directed and acted in the movie Pulp Fiction?',
       'Qui a à la fois réalisé et joué dans le film Pulp Fiction ?',
       1, 0, 27, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0',
       'One person in two roles on the same film is legitimate, and the query that expresses it looks exactly like the collapse it must not be confused with. Guards this rule against overshooting.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who both directed and acted in the movie Pulp Fiction?') AS existing);

-- ===== category 28: TV Series - Cast & Crew queries =====

-- The series side, which reaches T_WC_T2S_PERSON_SERIE and the Creator department that has
-- no movie equivalent.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who created the TV series Breaking Bad with Bryan Cranston?',
       'Qui est le créateur de la série Breaking Bad avec Bryan Cranston ?',
       1, 0, 28, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND PERSON_NAME NOT IN (''Bryan Cranston'')',
       'The same invariant on the series side, where the credit table is T_WC_T2S_PERSON_SERIE and the Creator department exists only there.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who created the TV series Breaking Bad with Bryan Cranston?') AS existing);


-- ---------------------------------------------------------------------------
-- 2. Verify. Should return the four rows above, with their assertions.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION,
       ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Who is the costume designer of the movie Capote with Philip Seymour Hoffman?',
  'Who is the cinematographer of the movie Taxi Driver with Robert De Niro?',
  'Who created the TV series Breaking Bad with Bryan Cranston?',
  'Who both directed and acted in the movie Pulp Fiction?'
)
ORDER BY ID_T2S_EVALUATION;


-- ---------------------------------------------------------------------------
-- 4. NOT YET APPLIED. Tighten evaluation 2476 so the conjunction is actually
--    tested. Guarded on the EXACT current value rather than on emptiness: it
--    applies once, does nothing on re-run, and withdraws itself if someone
--    edited the assertion in between.
--
--    COUNT(*) &lt; 5 rather than == 1: the answer set is small by nature, and a
--    strict count would break the day a second person gains both credits on the
--    film. 1 passes, 37 does not, which is the whole discrimination needed.
--    PERSON_NAME IN keeps the anchor honest, since a small WRONG set would
--    otherwise satisfy the count alone.
--
--    After it applies, re-run phase 11 for 2476 in both languages, then phase 20.
--    Scoring alone (phase 20) is not enough here: the stored JSON_RESULT predates
--    the prompt change, so it would score the old French answer.
--
--    ON THE QUOTES, AND WHY THE GUARD IS A LIKE. Section 1 wrote '' for the inner
--    apostrophes and the column came back holding &#039;, while the &gt; it also
--    wrote survived untouched. So the import path escapes apostrophes and leaves
--    ampersands alone. Both spellings therefore reach html.unescape() the same way
--    at eval/text2sql-eval.py:768, and '' is kept below because it is the one this
--    file has already been round-tripped with. The guard, however, must not depend
--    on guessing how the CURRENT value was escaped: matching the ID plus the
--    absence of PERSON_NAME is escaping-proof and still applies exactly once, since
--    the new value contains PERSON_NAME.
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
   SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &lt; 5 AND PERSON_NAME IN (''Quentin Tarantino'')',
       LONG_DESC = 'One person in two roles on the same film is legitimate, and the query that expresses it looks exactly like the collapse it must not be confused with. Guards the -211 rule against overshooting, and guards the conjunction itself: "and" between two roles needs two aliased credit instances both correlated on the same film, never an OR on one instance, which answers "either role" and returns the whole cast.'
 WHERE ID_T2S_EVALUATION = 2476
   AND ASSERTIONS_QUERY_RESULT LIKE 'COUNT(*)%'
   AND ASSERTIONS_QUERY_RESULT NOT LIKE '%PERSON_NAME%';

-- Verify. Expect one row carrying the new assertion.
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 55) AS QUESTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION = 2476;


-- ---------------------------------------------------------------------------
-- 3. Ready to edit, AFTER a run. Extraction assertions, once the key set has
--    been observed three times in each language. The Capote one matches what
--    usage log 20260825-180913 already shows; the other three are guesses
--    until measured, which is why none of them is applied above.
--    Guarded on emptiness so it applies once and withdraws itself.
-- ---------------------------------------------------------------------------
-- UPDATE T_WC_T2S_EVALUATION
--   SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Person_name1&quot;])'
--   WHERE QUESTION = 'Who is the costume designer of the movie Capote with Philip Seymour Hoffman?'
--     AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
