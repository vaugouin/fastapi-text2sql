-- ============================================================================
-- Fifteen evaluations whose French column holds a refusal of the translation
-- model, and two whose title was translated (EVALUATIONS-019)
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-25. Texts to be validated by Philippe before
-- running: edit section 2 if a wording does not suit, the guards do not depend
-- on it.
--
-- WHAT HAPPENED. Phase 5 of the evaluator translates QUESTION into QUESTION_FR
-- when QUESTION_FR is empty. In thirteen rows QUESTION already held a FRENCH
-- question (typed in French into the English column); asked to translate French
-- into French, the model answered with a refusal, and the refusal was stored as
-- the French question: "Je suis desole, je ne peux pas vous aider avec ca.", "Des
-- questions d'evaluation en anglais sont necessaires...". In two more rows (201,
-- 2359) the English question was fine and the model refused anyway. And the 2025
-- film "Sorry, Baby" was translated as a phrase (897, 898).
--
-- THE FIX.
--   Thirteen rows (French text in QUESTION): the French original moves to
--   QUESTION_FR VERBATIM, copied inside the database so no character is re-typed,
--   typos included (they are part of what the question tests); QUESTION receives
--   an English translation.
--   201, 2359: QUESTION stays, QUESTION_FR receives a French translation.
--   897, 898: QUESTION_FR keeps the title untranslated.
--
-- WHICH EXECUTIONS ARE AFFECTED. Only 2359 has an assertion and ran in campaign
-- 001.001.019: its French execution asked the API the refusal sentence. Section 4
-- soft-deletes that ONE execution so the next French run re-asks it (one API
-- call). The fourteen others have no assertion and never ran.
--
-- GUARDS. Section 1 fires only while QUESTION_FR is still a refusal; section 2
-- only while QUESTION_FR equals QUESTION (just after the copy); section 3 on the
-- exact current value. A re-run changes nothing.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '0. Before' AS SECTION;
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 70) AS QUESTION, LEFT(QUESTION_FR, 70) AS QUESTION_FR
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (91, 110, 144, 201, 251, 304, 379, 395, 461, 464, 527, 569, 570, 875, 2359, 897, 898);

-- ---------------------------------------------------------------------------
-- 1. The thirteen French originals move to QUESTION_FR, verbatim.
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET QUESTION_FR = QUESTION,
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION IN (91, 110, 144, 251, 304, 379, 395, 461, 464, 527, 569, 570, 875)
  AND (QUESTION_FR LIKE 'Je suis d%' OR QUESTION_FR LIKE 'Des questions d%');

-- ---------------------------------------------------------------------------
-- 2. Their English translations, only right after the copy of section 1.
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Give me the 50 English-language feature-length comedies from the 50s with the best IMDb ratings', TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 91  AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'All French-language movies released in 1967',                                                  TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 110 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Movies by Louis malle',                                                                        TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 144 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Robert De Niro pictures',                                                                      TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 251 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'All French-language movies released in 1969',                                                  TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 304 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Movies by Agnes varda',                                                                        TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 379 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'I want the French posters of the movies starring Louis de Funès',                              TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 395 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'What are all the movies in the Criterion Collection?',                                        TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 461 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Sound movies with Charlie Chaplin',                                                            TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 464 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Show the pictures of bogart',                                                                  TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 527 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Movies directed by jess franco',                                                               TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 569 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'Give me 10 color movies with Humphrey Bogart',                                                 TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 570 AND QUESTION = QUESTION_FR;
UPDATE T_WC_T2S_EVALUATION SET QUESTION = 'I want to know all the movies and series that Alfred Hitchcock directed',                     TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 875 AND QUESTION = QUESTION_FR;

-- ---------------------------------------------------------------------------
-- 3. French translations for the two English originals, and the untranslated
--    title of "Sorry, Baby" (2025).
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION SET QUESTION_FR = 'Liste toutes les mini-séries HBO',  TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 201  AND QUESTION_FR LIKE 'Je suis d%';
UPDATE T_WC_T2S_EVALUATION SET QUESTION_FR = 'Montre des photos de Zendaya',      TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 2359 AND QUESTION_FR LIKE 'Je suis d%';
UPDATE T_WC_T2S_EVALUATION SET QUESTION_FR = 'Film sorry baby',                   TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 897  AND QUESTION_FR = 'Film désolé bébé';
UPDATE T_WC_T2S_EVALUATION SET QUESTION_FR = 'Film sorry, baby',                  TIM_UPDATED = NOW() WHERE ID_T2S_EVALUATION = 898  AND QUESTION_FR = 'Film désolé, bébé';

-- ---------------------------------------------------------------------------
-- 4. Re-ask 2359 in French: soft-delete its 1.1.19 French execution. Phase 10
--    of the next French run hard-deletes it, phase 11 re-asks it (one call).
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION_EXECUTION
SET DELETED = 1
WHERE ID_T2S_EVALUATION = 2359
  AND LANG = 'fr'
  AND API_VERSION = '001.001.019'
  AND ENTITY_EXTRACTION_MODEL = 'gpt-4o' AND TEXT2SQL_MODEL = 'gpt-4o' AND COMPLEX_MODEL = 'gpt-4o';

-- ---------------------------------------------------------------------------
-- 5. AFTER. No QUESTION_FR may still start with "Je suis d" or "Des questions d",
--    no QUESTION may still be in French for these rows, and 2359 fr must show
--    DELETED = 1.
-- ---------------------------------------------------------------------------
SELECT '5. After' AS SECTION;
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 70) AS QUESTION, LEFT(QUESTION_FR, 70) AS QUESTION_FR
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (91, 110, 144, 201, 251, 304, 379, 395, 461, 464, 527, 569, 570, 875, 2359, 897, 898);

SELECT ID_T2S_EVALUATION, LANG, API_VERSION, DELETED
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE ID_T2S_EVALUATION = 2359 AND API_VERSION = '001.001.019';

SELECT COUNT(*) AS REFUSALS_LEFT_IN_THE_BANK
FROM T_WC_T2S_EVALUATION
WHERE QUESTION_FR LIKE 'Je suis désolé%' OR QUESTION_FR LIKE 'Des questions d''évaluation%'
   OR QUESTION LIKE 'I''m sorry%';
