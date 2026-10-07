-- ============================================================================
-- Characters are never topics: fix the evaluations that still expect a Topic_name
-- ============================================================================
--
-- WHY. "Movies having a Philip Marlowe character" was taught as a Topic_name (prompt
-- example in data/entity_extraction.md, "Character-based Collections" in
-- data/text_to_sql.md), a leftover from the time topics covered recurring characters.
-- Philippe, 2026-10-07: characters are no longer handled by topics. Measured the same
-- day (tmdb-movie-preprocess, test-055-topics-and-cached-characters): there is NO
-- T2S topic and NO TMDb keyword named Marlowe, so the Topic_name road could not even
-- resolve. Meanwhile eval 2293 (Charlotte Corday) already expects Character_name1:
-- same question shape, two entity types.
--
-- The prompt is fixed in the same commit: Character_name for every character,
-- recurring or real, never Topic_name.
--
-- WHICH EVALUATIONS. Not by id: Philippe created a Marlowe evaluation on 2026-10-06
-- that the local copy of the bank does not hold. Selected by content instead:
--   - every evaluation whose question (EN or FR) names Marlowe,
--   - every evaluation of category 15 (character queries),
-- and whose entity-extraction assertion mentions Topic_name.
-- Known in the local bank: 17 ("List all movies with the private investigator Philip
-- Marlowe") and 32 ("Movies having a Philip Marlowe character").
--
-- ORDER. Run the file once the prompt fix is deployed: parts A and B only read, part C
-- rewrites, and the runner executes them in one go. Part B says whether the
-- query_result assertion of the Marlowe evaluations survives the change of road; if it
-- does not, that assertion is rewritten in a follow-up file, not guessed here.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- A. The evaluations concerned, as they are now (read only)
-- ---------------------------------------------------------------------------
SELECT 'A1. Evaluations naming Marlowe, or in category 15, with their assertions' AS SECTION;

SELECT e.ID_T2S_EVALUATION, e.ID_T2S_EVALUATION_CATEGORY AS CAT, e.DAT_CREAT,
       LEFT(e.QUESTION, 80) AS QUESTION, LEFT(e.QUESTION_FR, 60) AS QUESTION_FR,
       e.ASSERTIONS_ENTITY_EXTRACTION, LEFT(e.ASSERTIONS_QUERY_RESULT, 120) AS ASSERTIONS_QUERY_RESULT,
       e.ASSERTION_REFRESH_SQL IS NOT NULL AS HAS_REFRESH_SQL
FROM T_WC_T2S_EVALUATION e
WHERE COALESCE(e.DELETED, 0) = 0
  AND (e.QUESTION LIKE '%Marlowe%' OR e.QUESTION_FR LIKE '%Marlowe%' OR e.ID_T2S_EVALUATION_CATEGORY = 15)
ORDER BY e.ID_T2S_EVALUATION;

-- Any other evaluation, in any category, that expects a Topic_name: read the list by eye
-- for characters hiding elsewhere (themes such as "World War II" are legitimate topics).
SELECT 'A2. Every evaluation expecting a Topic_name, all categories' AS SECTION;

SELECT e.ID_T2S_EVALUATION, e.ID_T2S_EVALUATION_CATEGORY AS CAT, LEFT(e.QUESTION, 90) AS QUESTION,
       e.ASSERTIONS_ENTITY_EXTRACTION
FROM T_WC_T2S_EVALUATION e
WHERE COALESCE(e.DELETED, 0) = 0
  AND e.ASSERTIONS_ENTITY_EXTRACTION LIKE '%Topic_name%'
ORDER BY e.ID_T2S_EVALUATION;

-- ---------------------------------------------------------------------------
-- B. Does the character road find the films the topic road was asserted on? (read only)
--
-- The 13 films of the query_result assertion of evals 17 and 32, against the films
-- whose cast credits name Philip Marlowe (Character_name falls through to a search in
-- CAST_CHARACTER, there is no character entity yet: TMDB-MOVIE-PREPROCESS-012).
-- ---------------------------------------------------------------------------
SELECT 'B1. Expected films and the character road' AS SECTION;

SELECT m.ID_MOVIE, m.MOVIE_TITLE, m.RELEASE_YEAR,
       m.ID_MOVIE IN (1834, 910, 1841, 1840, 1846, 1847, 1835, 1815, 1848, 130715, 213655, 844417, 651175) AS IN_ASSERTION,
       EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_MOVIE pm
               WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'cast'
                 AND pm.CAST_CHARACTER LIKE '%Philip Marlowe%') AS CAST_FULL_NAME,
       EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_MOVIE pm
               WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'cast'
                 AND pm.CAST_CHARACTER LIKE '%Marlowe%') AS CAST_SURNAME,
       (SELECT GROUP_CONCAT(DISTINCT pm.CAST_CHARACTER SEPARATOR ' | ') FROM T_WC_T2S_PERSON_MOVIE pm
        WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'cast' AND pm.CAST_CHARACTER LIKE '%Marlowe%') AS CAST_CHARACTER
FROM T_WC_T2S_MOVIE m
WHERE m.ID_MOVIE IN (1834, 910, 1841, 1840, 1846, 1847, 1835, 1815, 1848, 130715, 213655, 844417, 651175)
   OR EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_MOVIE pm
              WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'cast'
                AND pm.CAST_CHARACTER LIKE '%Marlowe%')
ORDER BY IN_ASSERTION DESC, m.RELEASE_YEAR;

-- ---------------------------------------------------------------------------
-- C. Rewrite the entity-extraction assertions: Topic_name1 becomes Character_name1
--
-- Guarded: only rows still expecting a Topic_name, so a second run changes nothing.
-- The value check (matches(..., /^Philip Marlowe$/i)) is kept as it is, only the key
-- changes. A2 tells whether another evaluation needs the same treatment by hand.
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_ENTITY_EXTRACTION = REPLACE(ASSERTIONS_ENTITY_EXTRACTION, 'Topic_name', 'Character_name'),
    TIM_UPDATED = NOW()
WHERE COALESCE(DELETED, 0) = 0
  AND (QUESTION LIKE '%Marlowe%' OR QUESTION_FR LIKE '%Marlowe%' OR ID_T2S_EVALUATION_CATEGORY = 15)
  AND ASSERTIONS_ENTITY_EXTRACTION LIKE '%Topic_name%';

SELECT 'C1. After the rewrite' AS SECTION;

SELECT e.ID_T2S_EVALUATION, LEFT(e.QUESTION, 80) AS QUESTION, e.ASSERTIONS_ENTITY_EXTRACTION
FROM T_WC_T2S_EVALUATION e
WHERE COALESCE(e.DELETED, 0) = 0
  AND (e.QUESTION LIKE '%Marlowe%' OR e.QUESTION_FR LIKE '%Marlowe%' OR e.ID_T2S_EVALUATION_CATEGORY = 15)
ORDER BY e.ID_T2S_EVALUATION;
