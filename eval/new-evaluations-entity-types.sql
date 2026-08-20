-- New evaluations for the entity types the bank never exercised.
--
-- NOT YET APPLIED. 22 evaluations, English and French, across 9 categories.
--
-- RE-RUN GUARD, AND ITS ONE UNVERIFIED ASSUMPTION
-- Each INSERT is an INSERT ... SELECT guarded by a NOT EXISTS on the English question, so a
-- second pass inserts nothing. This is deliberately unlike assertions-year-bounds.sql, whose
-- INSERT carries no guard and whose header warns against replaying the file.
-- The subquery reads the table being inserted into. MySQL documents a restriction on that
-- (error 1093), and the standard workaround, used here, is to wrap the subquery in a derived
-- table so the server materialises it. That idiom is widely used and expected to work on
-- MariaDB, but it was NOT executed against a server before shipping: this machine has no
-- MariaDB client and no Docker. Run section 0 first, then one single INSERT, then section 0
-- again. If the guard is rejected outright you will see error 1093 immediately, on one
-- statement, with nothing inserted twice. Section 5 holds a guard-free fallback.
-- The comparison uses the table collation, utf8mb4_unicode_ci, so the guard is case- and
-- accent-insensitive. For a duplicate guard that is the behaviour you want.
--
-- WHY THIS FILE EXISTS
-- assertions-entity-extraction.sql covers 26 placeholder types, but the coverage it can reach
-- is bounded by what the bank already asks. Three types came out at zero (Status_name,
-- Nomination_name, Wikidata_property_ID) and several at one, not because the extraction
-- ignores them but because no question in 1424 exercises them. That gap cannot be closed with
-- assertions, only with new questions. It matters now: the extraction prompt is about to be
-- split into an open-entity half and a closed-vocabulary half, and Status_name, Serie_type,
-- Movie_genre, Serie_genre, Department_name and Technical_format all land in the closed half.
-- Splitting a component nothing measures is how the May regression happened.
--
-- HOW THESE WERE CHOSEN
-- 26 questions were drafted, then measured against the deployed extraction prompt, gpt-4o at
-- temperature 0, three passes on each of the two languages. A question is kept only when the
-- key set is identical across all three passes AND identical between English and French AND
-- contains the type it was written for. Four were dropped and are documented at the end: they
-- are findings about the prompt, not bad questions.
--
-- The tier-2 matches() clause is present only where the value itself was identical across all
-- six observations. Closed-vocabulary normalisation turns out to be the least reproducible
-- part of the extraction ("post-production" instead of the canonical "Post Production",
-- "Drame" instead of "Drama"), so several of these carry the key-set assertion alone.
--
-- ASSERTIONS_QUERY_RESULT IS LEFT NULL
-- These questions have never been run against the database, and inventing a row-count
-- assertion would be guessing. Section 3 holds a ready-to-edit block for the ones worth a
-- COUNT(*) > 0 once you have checked they return something.
--
-- Types added: Status_name (3), Nomination_name (3), Serie_type (2), Wikidata_property_ID (2), Criterion_spine_ID (2), IMDb_person_ID (2), Death_name (2), Network_name (2), Birth_year (1), Death_year (1), TMDb_ID (1), Wikidata_ID (1)


-- ---------------------------------------------------------------------------
-- 0. Pre-flight. Run this FIRST. It must return zero rows.
--    A row here means the question is already in the bank and section 1 will
--    skip it, which is the guard doing its job, not a problem.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 60) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Movies still in production',
  'Movies in post-production',
  'Canceled TV series',
  'List miniseries',
  'What talk shows are in the database?',
  'Which movies were nominated for the Academy Award for Best Picture?',
  'Which actors were nominated for the Golden Globe?',
  'TV series nominated for the Primetime Emmy Award',
  'Movies tagged with Wikidata property P136',
  'What is Wikidata property P161?',
  'What is Criterion spine number 100?',
  'Criterion spine 42',
  'Show me the person with IMDb ID nm0000233',
  'Who is nm0000151?',
  'Actresses born in 1934',
  'Directors who died in 2010',
  'Which people died from a heart attack?',
  'Actors who died of cancer',
  'Which series did AMC produce?',
  'Show me Apple TV+ series',
  'What is the TMDb movie 27205?',
  'What is Wikidata item Q47703?'
);


-- ---------------------------------------------------------------------------
-- 1. The new evaluations
-- ---------------------------------------------------------------------------

-- ===== category 2: Movies - Basic Queries =====
-- Status_name -> In Production, the status the bank never exercised on the movie side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Movies still in production', 'Films encore en production',
       1, 0, 2, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Status_name1&quot;]) AND matches($.Status_name1, /^In Production$/i)',
       'In Production, the status the bank never exercised on the movie side.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Movies still in production') AS existing);
-- Status_name -> Post Production, a two-word canonical whose French alias is identical.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Movies in post-production', 'Films en post-production',
       1, 0, 2, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Status_name1&quot;])',
       'Post Production, a two-word canonical whose French alias is identical.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Movies in post-production') AS existing);

-- ===== category 6: TV Series - Basic queries =====
-- Status_name -> Canceled on the series side, where the French alias annule must map back to English.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Canceled TV series', 'Séries télévisées annulées',
       1, 0, 6, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Status_name1&quot;])',
       'Canceled on the series side, where the French alias annule must map back to English.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Canceled TV series') AS existing);
-- Serie_type -> Miniseries, whose French form carries a hyphen and an accent.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'List miniseries', 'Liste des mini-séries',
       1, 0, 6, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Serie_type1&quot;])',
       'Miniseries, whose French form carries a hyphen and an accent.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'List miniseries') AS existing);
-- Serie_type -> Talk Show, a two-word canonical written with and without a hyphen.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'What talk shows are in the database?', 'Quels talk-shows sont dans la base ?',
       1, 0, 6, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Serie_type1&quot;])',
       'Talk Show, a two-word canonical written with and without a hyphen.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What talk shows are in the database?') AS existing);

-- ===== category 7: Production Companies & Networks Queries =====
-- Network_name -> Network_name had a single assertion. AMC is also a cinema chain, so the domain matters.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Which series did AMC produce?', 'Quelles séries AMC a-t-elle produites ?',
       1, 0, 7, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Network_name1&quot;]) AND matches($.Network_name1, /^AMC$/i)',
       'Network_name had a single assertion. AMC is also a cinema chain, so the domain matters.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which series did AMC produce?') AS existing);
-- Network_name -> A network whose name carries a plus sign, a surface form nothing else in the bank has.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Show me Apple TV+ series', 'Montre-moi les séries Apple TV+',
       1, 0, 7, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Network_name1&quot;]) AND matches($.Network_name1, /^Apple TV\\+$/i)',
       'A network whose name carries a plus sign, a surface form nothing else in the bank has.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Show me Apple TV+ series') AS existing);

-- ===== category 11: Movies - Awards Queries =====
-- Nomination_name -> Nomination_name had zero coverage. The same label is also an Award_name, so this is the nomination-versus-award boundary, tested on the movie side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Which movies were nominated for the Academy Award for Best Picture?', 'Quels films ont été nommés à l''Oscar du meilleur film ?',
       1, 0, 11, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Nomination_name1&quot;])',
       'Nomination_name had zero coverage. The same label is also an Award_name, so this is the nomination-versus-award boundary, tested on the movie side.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which movies were nominated for the Academy Award for Best Picture?') AS existing);

-- ===== category 19: Movies - ID Queries =====
-- Wikidata_property_ID -> Wikidata_property_ID had zero coverage, and a P number must never be read as a Wikidata_ID.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Movies tagged with Wikidata property P136', 'Films associés à la propriété Wikidata P136',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Wikidata_property_ID1&quot;]) AND matches($.Wikidata_property_ID1, /^P136$/i)',
       'Wikidata_property_ID had zero coverage, and a P number must never be read as a Wikidata_ID.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Movies tagged with Wikidata property P136') AS existing);
-- Wikidata_property_ID -> Same type, bare interrogative form.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'What is Wikidata property P161?', 'Qu''est-ce que la propriété Wikidata P161 ?',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Wikidata_property_ID1&quot;]) AND matches($.Wikidata_property_ID1, /^P161$/i)',
       'Same type, bare interrogative form.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is Wikidata property P161?') AS existing);
-- Criterion_spine_ID -> A bare integer that only its context makes an identifier.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'What is Criterion spine number 100?', 'Quel est le film Criterion numéro 100 ?',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Criterion_spine_ID1&quot;]) AND matches($.Criterion_spine_ID1, /^100$/i)',
       'A bare integer that only its context makes an identifier.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is Criterion spine number 100?') AS existing);
-- Criterion_spine_ID -> Same, telegraphic form, where the context word is nearly absent.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Criterion spine 42', 'Criterion numéro 42',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Criterion_spine_ID1&quot;]) AND matches($.Criterion_spine_ID1, /^42$/i)',
       'Same, telegraphic form, where the context word is nearly absent.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Criterion spine 42') AS existing);
-- TMDb_ID -> A bare integer that only the word TMDb turns into an identifier.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'What is the TMDb movie 27205?', 'Quel est le film TMDb 27205 ?',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^27205$/i)',
       'A bare integer that only the word TMDb turns into an identifier.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is the TMDb movie 27205?') AS existing);
-- Wikidata_ID -> A Q number, to sit opposite the P numbers above.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'What is Wikidata item Q47703?', 'Qu''est-ce que l''élément Wikidata Q47703 ?',
       1, 0, 19, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q47703$/i)',
       'A Q number, to sit opposite the P numbers above.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is Wikidata item Q47703?') AS existing);

-- ===== category 25: Persons - ID Queries =====
-- IMDb_person_ID -> nm identifiers had two assertions against nine for the tt form.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Show me the person with IMDb ID nm0000233', 'Montre-moi la personne avec l''identifiant IMDb nm0000233',
       1, 0, 25, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0000233$/i)',
       'nm identifiers had two assertions against nine for the tt form.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Show me the person with IMDb ID nm0000233') AS existing);
-- IMDb_person_ID -> Bare nm identifier, no surrounding vocabulary at all.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Who is nm0000151?', 'Qui est nm0000151 ?',
       1, 0, 25, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0000151$/i)',
       'Bare nm identifier, no surrounding vocabulary at all.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is nm0000151?') AS existing);

-- ===== category 35: Persons - Birth and Death =====
-- Birth_year -> Birth_year fell out of coverage entirely once the unstable rows were withheld.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Actresses born in 1934', 'Actrices nées en 1934',
       1, 0, 35, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Birth_year1&quot;]) AND matches($.Birth_year1, /^1934$/i)',
       'Birth_year fell out of coverage entirely once the unstable rows were withheld.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Actresses born in 1934') AS existing);
-- Death_year -> Death_year had a single assertion, alongside Department_name in the same question.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Directors who died in 2010', 'Réalisateurs morts en 2010',
       1, 0, 35, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Death_year1&quot;,&quot;Department_name1&quot;]) AND matches($.Death_year1, /^2010$/i)',
       'Death_year had a single assertion, alongside Department_name in the same question.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Directors who died in 2010') AS existing);
-- Death_name -> A medical cause of death, the Death_name side with only two assertions.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Which people died from a heart attack?', 'Quelles personnes sont mortes d''une crise cardiaque ?',
       1, 0, 35, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Death_name1&quot;])',
       'A medical cause of death, the Death_name side with only two assertions.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which people died from a heart attack?') AS existing);
-- Death_name -> A cause that is also a common topic word, so the boundary matters.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Actors who died of cancer', 'Acteurs morts d''un cancer',
       1, 0, 35, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Death_name1&quot;]) AND matches($.Death_name1, /^cancer$/i)',
       'A cause that is also a common topic word, so the boundary matters.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Actors who died of cancer') AS existing);

-- ===== category 46: TV Series - Awards Queries =====
-- Nomination_name -> Same boundary on the series side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'TV series nominated for the Primetime Emmy Award', 'Séries nommées aux Primetime Emmy Awards',
       1, 0, 46, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Nomination_name1&quot;])',
       'Same boundary on the series side.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'TV series nominated for the Primetime Emmy Award') AS existing);

-- ===== category 49: Persons - Awards Queries =====
-- Nomination_name -> Same boundary on the person side.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
SELECT 'Which actors were nominated for the Golden Globe?', 'Quels acteurs ont été nommés au Golden Globe ?',
       1, 0, 49, 0, CURDATE(), NOW(),
       'seteq(entity_keys($), [&quot;Nomination_name1&quot;]) AND matches($.Nomination_name1, /^Golden Globe$/i)',
       'Same boundary on the person side.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which actors were nominated for the Golden Globe?') AS existing);


-- ---------------------------------------------------------------------------
-- 2. Verification
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 52) AS QUESTION,
       ASSERTIONS_ENTITY_EXTRACTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Movies still in production',
  'Movies in post-production',
  'Canceled TV series',
  'List miniseries',
  'What talk shows are in the database?',
  'Which movies were nominated for the Academy Award for Best Picture?',
  'Which actors were nominated for the Golden Globe?',
  'TV series nominated for the Primetime Emmy Award',
  'Movies tagged with Wikidata property P136',
  'What is Wikidata property P161?',
  'What is Criterion spine number 100?',
  'Criterion spine 42',
  'Show me the person with IMDb ID nm0000233',
  'Who is nm0000151?',
  'Actresses born in 1934',
  'Directors who died in 2010',
  'Which people died from a heart attack?',
  'Actors who died of cancer',
  'Which series did AMC produce?',
  'Show me Apple TV+ series',
  'What is the TMDb movie 27205?',
  'What is Wikidata item Q47703?'
)
ORDER BY ID_T2S_EVALUATION_CATEGORY, ID_T2S_EVALUATION;


-- ---------------------------------------------------------------------------
-- 3. Optional, once you have confirmed these questions return rows
-- ---------------------------------------------------------------------------
-- UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) > 0'
--   WHERE QUESTION IN (
--     'Movies still in production',
--     'Movies in post-production',
--     'Canceled TV series',
--     'List miniseries',
--     'What talk shows are in the database?',
--     'Which movies were nominated for the Academy Award for Best Picture?',
--     'Which actors were nominated for the Golden Globe?',
--     'TV series nominated for the Primetime Emmy Award',
--     'Movies tagged with Wikidata property P136',
--     'What is Wikidata property P161?',
--     'What is Criterion spine number 100?',
--     'Criterion spine 42',
--     'Show me the person with IMDb ID nm0000233',
--     'Who is nm0000151?',
--     'Actresses born in 1934',
--     'Directors who died in 2010',
--     'Which people died from a heart attack?',
--     'Actors who died of cancer',
--     'Which series did AMC produce?',
--     'Show me Apple TV+ series',
--     'What is the TMDb movie 27205?',
--     'What is Wikidata item Q47703?'
--   ) AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');


-- ---------------------------------------------------------------------------
-- 4. Dropped, and why. These are findings, not bad questions.
-- ---------------------------------------------------------------------------
--
-- THE SERIE_GENRE / SERIE_TYPE OVERLAP, the most consequential of the four.
-- Documentary, News, Reality and Talk appear in BOTH vocabularies, so the same word
-- maps to two placeholders and therefore two different columns, and nothing in the
-- question decides which. Measured consequences:
--   'Show me documentary series' -> Serie_genre1, never Serie_type1
--   'Reality TV series'          -> Serie_genre1, never Serie_type1
--   'What talk shows are ...'    -> Serie_type1, stable, the opposite arbitration
-- The prompt cannot resolve this and no example will fix it: the ambiguity is in the
-- vocabulary, not in the wording. Worth deciding before the closed-vocabulary half
-- of the split is written, since that half will inherit the arbitration.
--
-- Which movies are planned but not released yet?
--   FR: Quels films sont planifiés mais pas encore sortis ?
--   observed EN: {"Status_name1": "Planned", "Status_name2": "Released"} | {"Status_name1": "Planned", "Status_name2": "Released"} | {"Status_name1": "Planned", "Status_name2": "Released"}
--   observed FR: {"Status_name1": "Planifiés"} | {"Status_name1": "Planifiés"} | {"Status_name1": "Planifiés"}
--
-- BBC documentaries
--   FR: Documentaires de la BBC
--   observed EN: {"Network_name1": "BBC"} | {"Network_name1": "BBC"} | {"Network_name1": "BBC"}
--   observed FR: {"Network_name1": "BBC"} | {"Network_name1": "BBC"} | {"Serie_type1": "Documentary", "Network_name1": "BBC"}
--
-- The two dropped for the Serie_genre/Serie_type overlap:
--   Show me documentary series   EN {"Serie_genre1": "Documentary"} | FR {"Serie_genre1": "Documentary"}
--   Reality TV series            EN {"Serie_genre1": "Reality"} | FR {"Serie_genre1": "Reality"}


-- ---------------------------------------------------------------------------
-- 5. Fallback, only if section 1 is rejected with error 1093
-- ---------------------------------------------------------------------------
-- Plain INSERT ... VALUES, no subquery on the target table and therefore no
-- restriction to worry about. It is NOT idempotent: running it twice creates 22
-- duplicates. Run section 0 first and only uncomment this if it returned zero rows.
--
-- INSERT INTO T_WC_T2S_EVALUATION
--   (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
--    DAT_CREAT, TIM_UPDATED, ASSERTIONS_ENTITY_EXTRACTION, LONG_DESC)
-- VALUES
--   ('Movies still in production', 'Films encore en production',
--    1, 0, 2, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Status_name1&quot;]) AND matches($.Status_name1, /^In Production$/i)',
--    'In Production, the status the bank never exercised on the movie side.'),
--   ('Movies in post-production', 'Films en post-production',
--    1, 0, 2, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Status_name1&quot;])',
--    'Post Production, a two-word canonical whose French alias is identical.'),
--   ('Canceled TV series', 'Séries télévisées annulées',
--    1, 0, 6, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Status_name1&quot;])',
--    'Canceled on the series side, where the French alias annule must map back to English.'),
--   ('List miniseries', 'Liste des mini-séries',
--    1, 0, 6, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Serie_type1&quot;])',
--    'Miniseries, whose French form carries a hyphen and an accent.'),
--   ('What talk shows are in the database?', 'Quels talk-shows sont dans la base ?',
--    1, 0, 6, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Serie_type1&quot;])',
--    'Talk Show, a two-word canonical written with and without a hyphen.'),
--   ('Which movies were nominated for the Academy Award for Best Picture?', 'Quels films ont été nommés à l''Oscar du meilleur film ?',
--    1, 0, 11, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Nomination_name1&quot;])',
--    'Nomination_name had zero coverage. The same label is also an Award_name, so this is the nomination-versus-award boundary, tested on the movie side.'),
--   ('Which actors were nominated for the Golden Globe?', 'Quels acteurs ont été nommés au Golden Globe ?',
--    1, 0, 49, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Nomination_name1&quot;]) AND matches($.Nomination_name1, /^Golden Globe$/i)',
--    'Same boundary on the person side.'),
--   ('TV series nominated for the Primetime Emmy Award', 'Séries nommées aux Primetime Emmy Awards',
--    1, 0, 46, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Nomination_name1&quot;])',
--    'Same boundary on the series side.'),
--   ('Movies tagged with Wikidata property P136', 'Films associés à la propriété Wikidata P136',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Wikidata_property_ID1&quot;]) AND matches($.Wikidata_property_ID1, /^P136$/i)',
--    'Wikidata_property_ID had zero coverage, and a P number must never be read as a Wikidata_ID.'),
--   ('What is Wikidata property P161?', 'Qu''est-ce que la propriété Wikidata P161 ?',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Wikidata_property_ID1&quot;]) AND matches($.Wikidata_property_ID1, /^P161$/i)',
--    'Same type, bare interrogative form.'),
--   ('What is Criterion spine number 100?', 'Quel est le film Criterion numéro 100 ?',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Criterion_spine_ID1&quot;]) AND matches($.Criterion_spine_ID1, /^100$/i)',
--    'A bare integer that only its context makes an identifier.'),
--   ('Criterion spine 42', 'Criterion numéro 42',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Criterion_spine_ID1&quot;]) AND matches($.Criterion_spine_ID1, /^42$/i)',
--    'Same, telegraphic form, where the context word is nearly absent.'),
--   ('Show me the person with IMDb ID nm0000233', 'Montre-moi la personne avec l''identifiant IMDb nm0000233',
--    1, 0, 25, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0000233$/i)',
--    'nm identifiers had two assertions against nine for the tt form.'),
--   ('Who is nm0000151?', 'Qui est nm0000151 ?',
--    1, 0, 25, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0000151$/i)',
--    'Bare nm identifier, no surrounding vocabulary at all.'),
--   ('Actresses born in 1934', 'Actrices nées en 1934',
--    1, 0, 35, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Birth_year1&quot;]) AND matches($.Birth_year1, /^1934$/i)',
--    'Birth_year fell out of coverage entirely once the unstable rows were withheld.'),
--   ('Directors who died in 2010', 'Réalisateurs morts en 2010',
--    1, 0, 35, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Death_year1&quot;,&quot;Department_name1&quot;]) AND matches($.Death_year1, /^2010$/i)',
--    'Death_year had a single assertion, alongside Department_name in the same question.'),
--   ('Which people died from a heart attack?', 'Quelles personnes sont mortes d''une crise cardiaque ?',
--    1, 0, 35, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Death_name1&quot;])',
--    'A medical cause of death, the Death_name side with only two assertions.'),
--   ('Actors who died of cancer', 'Acteurs morts d''un cancer',
--    1, 0, 35, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Death_name1&quot;]) AND matches($.Death_name1, /^cancer$/i)',
--    'A cause that is also a common topic word, so the boundary matters.'),
--   ('Which series did AMC produce?', 'Quelles séries AMC a-t-elle produites ?',
--    1, 0, 7, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Network_name1&quot;]) AND matches($.Network_name1, /^AMC$/i)',
--    'Network_name had a single assertion. AMC is also a cinema chain, so the domain matters.'),
--   ('Show me Apple TV+ series', 'Montre-moi les séries Apple TV+',
--    1, 0, 7, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Network_name1&quot;]) AND matches($.Network_name1, /^Apple TV\\+$/i)',
--    'A network whose name carries a plus sign, a surface form nothing else in the bank has.'),
--   ('What is the TMDb movie 27205?', 'Quel est le film TMDb 27205 ?',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^27205$/i)',
--    'A bare integer that only the word TMDb turns into an identifier.'),
--   ('What is Wikidata item Q47703?', 'Qu''est-ce que l''élément Wikidata Q47703 ?',
--    1, 0, 19, 0, CURDATE(), NOW(),
--    'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q47703$/i)',
--    'A Q number, to sit opposite the P numbers above.');
