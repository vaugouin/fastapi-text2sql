-- Entity-extraction assertion for evaluation 2481, the genre that qualifies a collection.
--
-- NOT YET APPLIED. Written 2026-08-27.
--
-- WHY THIS FILE EXISTS
-- "Répertorier les collections de science-fiction avec exactement 3 films" returned zero rows
-- on 2026-08-26. Entity extraction produced NO entity at all, the text2sql generator wrote
-- '{{Movie_genre1}}' anyway, and the query was discarded as ambiguous
-- (FASTAPI-TEXT2SQL-220).
--
-- The cause is not the French. The bank holds 33 evaluations asserting genre extraction and
-- their French forms are genuinely French: "Liste de films d'horreur" asserts /^Horror$/i,
-- "Quels sont les meilleurs films romantiques ?" asserts /^Romance$/i. The model translates
-- French genre words to the English canonical form as a matter of routine, and the bank
-- checks it, since it is replayed with --lang fr.
--
-- The cause is the trigger condition. Every one of those 33 questions names the medium:
-- "films d'horreur", "films romantiques", "séries télévisées". The rule read "Extract
-- Movie_genre when the user question mentions a movie genre AND the question is about movies
-- (not TV series)". This question is about COLLECTIONS. The word "films" appears in it, but
-- as the counted unit, not as what the genre qualifies. There was no branch for that, and
-- for a collection there is no "matching side" either, so a model that abstains is applying
-- the rule to the letter.
--
-- THE HOLE THIS ASSERTION FILLS
-- 49 evaluations pair a genre with movies. Five pair a genre with a collection, and in four
-- of those the genre still qualifies the MOVIES ("sci-fi movies from the Criterion
-- Collection"), the collection being one more filter. The fifth is 2481. None of the five
-- carries an entity-extraction assertion. The case where the genre qualifies the collection
-- itself had never been posed, which is exactly why nobody had hit it.
--
-- IT WILL BE RED, AND THAT IS THE POINT
-- Run today, against the prompt as it was on 2026-08-26, this assertion fails: extraction
-- returns no entity at all, so entity_keys($) is empty and seteq() is false. It turns green
-- only once the corrected trigger in data/entity_extraction.md is deployed, which is what
-- makes it a measurement rather than a decoration. Do not "fix" it by weakening it.
--
-- WHY seteq AND NOT A LOOSER CHECK
-- seteq demands the exact key set. "exactly 3 movies" is a numeric constraint the extractor
-- has no placeholder for, so Movie_genre1 alone is the whole expected inventory. If a future
-- prompt starts extracting a count placeholder, this assertion goes red and that is correct:
-- it would be a change of contract worth noticing.
--
-- IDEMPOTENT
-- Guarded on the assertion still being empty, so re-running changes nothing and it never
-- overwrites a later hand edit. Not executed against a server from this machine; validated
-- for syntax and convention only.
--
-- HOW TO RUN
--   mysql <db> < eval/assertions-entity-extraction-genre-indirect.sql
-- then re-run phase 11 (the API call) and phase 20 for evaluation 2481 only. Layer 1 of the
-- harness already enforces that the placeholders in `question` match the entity keys, so the
-- sentence itself is deliberately not pinned (see assertions-entity-extraction-language-neutral.sql).


-- ---------------------------------------------------------------------------
-- 0. Pre-flight. Must return one row, with ASSERTIONS_ENTITY_EXTRACTION empty.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 60) AS QUESTION,
       ASSERTIONS_ENTITY_EXTRACTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'List science fiction collections with exactly 3 movies';


-- ---------------------------------------------------------------------------
-- 1. The assertion
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_ENTITY_EXTRACTION =
      'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Science Fiction$/i)',
    TIM_UPDATED = NOW()
WHERE QUESTION = 'List science fiction collections with exactly 3 movies'
  AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');


-- ---------------------------------------------------------------------------
-- 2. Post-flight. Must return the row with the assertion set.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 60) AS QUESTION, ASSERTIONS_ENTITY_EXTRACTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'List science fiction collections with exactly 3 movies';


-- ---------------------------------------------------------------------------
-- 3. The four neighbours that share the hole, for the day someone wants them.
--    In all four the genre qualifies the MOVIES and the collection is a filter, so they are
--    the ALREADY-COVERED shape and should extract Movie_genre today. Writing their
--    assertions would turn four silent passes into four measured ones. Left commented
--    because none of the four has been run and read: do not assert what has not been
--    observed, which is the house rule.
-- ---------------------------------------------------------------------------
-- SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 70), ASSERTIONS_ENTITY_EXTRACTION
-- FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION IN (208, 354, 2196, 2199);
