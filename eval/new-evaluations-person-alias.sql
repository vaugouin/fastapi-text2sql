-- New evaluations closing FASTAPI-TEXT2SQL-214, -215, -218 and covering -219 (person aliases).
--
-- NOT YET APPLIED. Written 2026-08-26. 3 evaluations, English and French, one category.
--
-- WHY THIS FILE EXISTS
-- Four defects were measured on 2026-08-26 while preparing video #5, all on the same gesture:
-- asking for a person by a name that is not the one they are credited under.
--
--   "Marion Morrison"     zero rows. TMDb stores the birth name in full, "Marion Robert
--                         Morrison"; fuzz.ratio normalises by length and scored the two-word
--                         form 81.1 against a threshold of 87.8 (-214). The complex-question
--                         retry HAD identified John Wayne, wrote him into the free-text
--                         "note" that nothing reads, and rewrote the question with the same
--                         failing name (-215), so the second pass searched what had just
--                         failed, for the price of a strong-model call.
--   "Maurice Micklewhite" zero rows, and the trace never even named a Micklewhite: the
--                         ranker scored with WRatio, which grades a token subset ("Maurice
--                         Maurice") exactly like the real birth name, broke the tie on the
--                         highest TMDb id, and handed the gate an unrelated person to refuse
--                         (-218). The base holds "Maurice Joseph Micklewhite Jr.", two extra
--                         tokens, which then defeated the first version of the -214 guard.
--   "Arnol Swartzeneger"  found him, but by the expensive path. fuzz.ratio against the real
--                         name is 87.2, ABOVE the 84.5 threshold, so the gate would have
--                         accepted it; the candidate never reached the gate. The missing "d"
--                         moves the prefix pool to 'arnols%' while the target lives in
--                         'arnold%', and the BK-tree that exists to cover typos inside the
--                         prefix reaches 3 edits where 5 were needed (-219).
--
-- THE THREE ORDERED QUESTIONS, ASKED BEFORE WRITING THIS FILE
--   * Does a question in the bank cover the case? No. `grep -ril "morrison\|micklewhite\|
--     swartzeneger" eval/data/evaluation/` returns nothing on the export of 2026-08-26.
--   * Does it carry an assertion? Moot, there is no question.
--   * Would an existing assertion have caught THIS defect? Category 30 (persons, person-name
--     queries) holds name questions, but every one of them spells the name the way the
--     database does. A bank that only ever asks correctly cannot measure forgiveness.
--   So: write the evaluations, with their assertions.
--
-- WHAT THE ASSERTIONS PROTECT
-- Two levels, and no third.
--   COUNT(*) &gt; 0   the floor. All four defects returned zero rows or the wrong person; an
--                   empty DataFrame satisfies only "COUNT(*) == 0" written exactly so, so
--                   this clause goes red the day the regression returns.
--   ID_PERSON IN () the anchor, on an identity that does not drift. A TMDb person id is
--                   stable in a way a title or a count is not.
-- No counter-example (level 3). That level catches a query returning TOO MUCH, and none of
-- these defects has that shape: they return nothing, or one wrong person the anchor already
-- rejects.
--
-- NO ASSERTION_REFRESH_SQL, ON PURPOSE
-- Process 70 rebuilds ASSERTIONS_QUERY_RESULT from the refresh SQL at its next pass, which
-- would strip the "COUNT(*) &gt; 0 AND" half of every clause below and leave the bare id list.
-- There is nothing to refresh here anyway: these three ids are fixed identities, not a result
-- set that drifts with the database. Leaving the column NULL is what keeps the floor alive.
--
-- THE IDS ARE READ, NOT REMEMBERED
-- Verified by Philippe against person.php on 2026-08-26: John Wayne 4165, Michael Caine 3895,
-- Arnold Schwarzenegger 1100. This matters more than it looks: 3895 had been asserted from a
-- model's memory in the -218 ticket and happened to be right, which is the most dangerous
-- case, since an exact number stated without a source is never reopened.
--
-- ASSERTIONS_ENTITY_EXTRACTION IS LEFT NULL
-- The house method for an extraction assertion is three passes in each language, and these
-- questions have been run once, in English, by hand. Do not assert what has not been run.
--
-- ONE ASSERTION IS DELIBERATELY WEAKER THAN IT LOOKS, AND SECTION 3 SAYS SO
-- "Arnol Swartzeneger" passes TODAY through the strong-model retry, which is exactly the
-- expense -219 exists to remove. Its assertion therefore proves the outcome, not the fix.
-- When -219 ships, section 3 must be applied, or this evaluation stays green while measuring
-- the opposite of what is wanted. That is the -216 lesson: an evaluation green for the wrong
-- reason is an instrument that lies, and costlier than an absent one.
--
-- RE-RUN GUARD
-- Each INSERT is an INSERT ... SELECT guarded by NOT EXISTS on the English question, wrapped
-- in a derived table so MySQL error 1093 (reading the table being inserted into) does not
-- fire. Same idiom as new-evaluations-person-role-collapse.sql; like that file, it has NOT
-- been executed against a server from this machine, and is validated for syntax only.
--
-- HOW TO RUN
--   Run section 0 first, then the three INSERTs, then section 0 again.
--   mysql <db> < eval/new-evaluations-person-alias.sql
--   Then phase 31 to refresh the JSON export, and phases 11 + 20 to run and score them.


-- ---------------------------------------------------------------------------
-- 0. Pre-flight. Run this FIRST. It must return zero rows.
--    A row here means the question is already in the bank and section 1 will
--    skip it, which is the guard doing its job, not a problem.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Who is Marion Morrison?',
  'Who is Maurice Micklewhite?',
  'Arnol Swartzeneger'
);


-- ---------------------------------------------------------------------------
-- 1. The new evaluations
-- ---------------------------------------------------------------------------

-- ===== category 30: Persons - Person name queries =====

-- The birth name a user would actually type, two words, against a base that stores three.
-- This one is the crossroads of -214 and -215: either the alias resolves on the first pass,
-- or the retry rewrites the question with the credited name. The assertion does not care
-- which, and neither does the user.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is Marion Morrison?',
       'Qui est Marion Morrison ?',
       1, 0, 30, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_PERSON IN (4165)',
       'Birth name of John Wayne, stored by TMDb in full as "Marion Robert Morrison". The two-word form scored 81.1 against a threshold of 87.8 on 2026-08-26 and returned nothing, while the complex-question retry had identified John Wayne and put him in a field nothing reads. Asserts the identity returned, not the path taken: -214 satisfies it on the first pass, -215 on the second.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is Marion Morrison?') AS existing);

-- The same gesture where the base holds a generational suffix, so the query is two tokens
-- short and not one. This is the case that defeated the first version of the -214 guard and
-- forced the suffix rule; it is also the case where -218 could be observed on its own, since
-- the ranker handed the gate an unrelated person to refuse.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is Maurice Micklewhite?',
       'Qui est Maurice Micklewhite ?',
       1, 0, 30, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_PERSON IN (3895)',
       'Birth name of Michael Caine, stored by TMDb as "Maurice Joseph Micklewhite Jr.", two tokens more than the form a user types. On 2026-08-26 the trace never named a Micklewhite at all: WRatio grades a token subset ("Maurice Maurice") exactly like the real birth name and the tie fell to the highest TMDb id, so the gate was handed a stranger to refuse.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is Maurice Micklewhite?') AS existing);

-- A misspelling with one error inside the first six characters, which is what makes it
-- different from every other typo in the bank: the prefix pool cannot contain the target.
-- Question identical in both languages on purpose. A misspelled proper noun must not be
-- translated, or phases 5 and 6 would repair the very thing under test.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Arnol Swartzeneger',
       'Arnol Swartzeneger',
       1, 0, 30, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_PERSON IN (1100)',
       'Two errors, one of them in the first six characters. fuzz.ratio against the real name is 87.2, above the 84.5 threshold, so the gate would have accepted it; the candidate never reached the gate, because the missing "d" moves the prefix pool to arnols% while the target lives in arnold%, and the BK-tree reaches 3 edits where 5 were needed. Green today through the strong-model retry, which is the expense FASTAPI-TEXT2SQL-219 exists to remove: see section 3.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Arnol Swartzeneger') AS existing);


-- ---------------------------------------------------------------------------
-- 2. Post-flight. Run this AFTER section 1. It must return three rows,
--    each with its assertion, and no ASSERTION_REFRESH_SQL.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 40) AS QUESTION,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Who is Marion Morrison?',
  'Who is Maurice Micklewhite?',
  'Arnol Swartzeneger'
)
ORDER BY ID_T2S_EVALUATION;


-- ---------------------------------------------------------------------------
-- 3. NOT YET APPLICABLE. Apply the day FASTAPI-TEXT2SQL-219 ships, and not before.
--
-- Today "Arnol Swartzeneger" is green because the strong model rescued it, which is the
-- silent cost -219 describes: a case the lexical path should have handled, paid for at
-- strong-model price. The assertion above cannot see the difference, so the evaluation would
-- stay green through the very path the ticket removes.
--
-- The clause below has no equivalent in ASSERTIONS_QUERY_RESULT, which scores the returned
-- DataFrame and knows nothing about how it was obtained. Whether it goes here, in
-- ASSERTIONS_SQL_QUERY, or in a new assertion family reading complex_model_used, is a
-- decision for -219 itself. Leaving the question open in writing is the point: the trap is
-- to ship -219 and forget that this evaluation was already green.
-- ---------------------------------------------------------------------------
-- UPDATE T_WC_T2S_EVALUATION
-- SET LONG_DESC = CONCAT(LONG_DESC, ' Since FASTAPI-TEXT2SQL-219, this must resolve on the '
--                 'lexical path: complex_model_used false, complex_question_processing_time zero.')
-- WHERE QUESTION = 'Arnol Swartzeneger'
--   AND LONG_DESC NOT LIKE '%Since FASTAPI-TEXT2SQL-219%';
