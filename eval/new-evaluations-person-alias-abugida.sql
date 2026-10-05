-- New evaluation closing TMDB-PERSON-PREPROCESS-008 (vowel signs in the normalized alias keys).
--
-- APPLIED 2026-10-05: ID_T2S_EVALUATION 2526. Written 2026-10-05. 1 evaluation, English and French,
-- category 43.
--
-- WHY THIS FILE EXISTS
-- The generated PERSON_NAME_NORM of the alias tables kept letters and digits only. In
-- Devanagari, Thai, Kannada and the other abugidas the vowels are combining marks (Unicode
-- category M), so each vowel became a space and the word fell apart: "हयाओ मियाज़ाकी"
-- (Hayao Miyazaki) was stored as "हय ओ म य ज क". normalize_name() did the same on the query
-- side, so an exact spelling still matched; what suffered was the fuzzy score of a NEAR
-- spelling, compared syllable by syllable. Fixed on 2026-10-05: p{M} in the class of both
-- alias tables (source migration, then Process 51), Unicode category M kept by
-- normalize_name() (cf8be65).
--
-- THE THREE ORDERED QUESTIONS, ASKED BEFORE WRITING THIS FILE
--   * Does a question in the bank cover the case? No. Category 43 (persons, non-Latin
--     queries) holds twelve names, one of them in Devanagari (2269, Priyanka Chopra), but
--     every one is spelled exactly as the alias is stored. `grep -l "मियाज\|हयाओ"` on the
--     shared_data export of 2026-10-05 returns nothing.
--   * Does it carry an assertion? Moot, there is no question.
--   * Would an existing assertion have caught THIS defect? No: an exact spelling matched
--     before the fix as well, through the equally mangled key. A bank that only ever asks
--     correctly cannot measure forgiveness (same lesson as new-evaluations-person-alias.sql).
--   So: write the evaluation, with its assertions.
--
-- THE QUESTION
-- "हयाओ मियाजाकी" is the stored alias "हयाओ मियाज़ाकी" without the nukta, the dot under ज
-- (U+093C, itself a combining mark) that writes the "z". A Hindi speaker typing on a plain
-- keyboard commonly leaves it out. Measured on 2026-10-05 on green 1.1.19, cache off:
-- resolved through T_WC_T2S_PERSON_ALSO_KNOWN_AS, fuzz_ratio 96.3 against a threshold of
-- 87.8, SQL on PERSON_NAME = 'Hayao Miyazaki', first rows Spirited Away, Princess Mononoke.
-- The name is identical in both languages on purpose: a misspelled proper noun must not be
-- translated, or phases 5 and 6 would repair the very thing under test.
--
-- WHAT THE ASSERTIONS PROTECT
--   ASSERTIONS_SQL_QUERY     (?i)(Hayao Miyazaki|ID_PERSON ?= ?608). The resolution itself:
--                            the SQL names the canonical person, by name (the form the API
--                            writes today) or by id. Applied to sql_query, after placeholder
--                            substitution. No backslash in the regex, so nothing to double.
--   ASSERTIONS_QUERY_RESULT  COUNT(*) &gt; 0 AND ID_MOVIE IN (129, 128). Floor, and the anchor
--                            on two stable TMDb ids (Spirited Away, Princess Mononoke), the
--                            two first rows of the default IMDB_RATING_WEIGHTED order.
-- No counter-example: the defect returns nothing or another person, which the floor and the
-- anchor already reject.
--
-- NO ASSERTION_REFRESH_SQL, ON PURPOSE
-- Process 70 would rewrite ASSERTIONS_QUERY_RESULT into a bare IN (...) and drop the floor.
-- A director's two best-known films are a fact, not a drifting ranking.
--
-- ASSERTIONS_ENTITY_EXTRACTION IS LEFT NULL
-- The house method for an extraction assertion is three passes in each language; this
-- question has been run once, in English.
--
-- RE-RUN GUARD
-- INSERT ... SELECT guarded by NOT EXISTS on the English question, inside a derived table
-- (MySQL error 1093). Validated for syntax only from this machine.
--
-- HOW TO RUN (VPS)
--   cd ~/docker/fastapi-text2sql-green      # or -blue, the clone of the live colour
--   git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-green/eval/new-evaluations-person-alias-abugida.sql
-- Then phase 31 to refresh the JSON export, and phases 11 + 20 to run and score it.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. Pre-flight. Must return zero rows; a row means the question is already in
--    the bank and the guard of section 2 will skip it.
-- ---------------------------------------------------------------------------
SELECT '0. Before insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Which movies did हयाओ मियाजाकी direct?';

-- ---------------------------------------------------------------------------
-- 1. The witnesses, to read BEFORE inserting.
--    a) The near spelling must NOT be a stored alias key (zero rows), or the
--       evaluation would test an exact match and not the fuzzy path.
--    b) The stored spelling is an alias of 608, key whole (marks kept).
--    c) 129 and 128 are directed by 608.
-- ---------------------------------------------------------------------------
SELECT '1a. Near spelling as a stored key (must be 0 rows)' AS SECTION;

SELECT ID_ROW, ID_PERSON, PERSON_NAME, PERSON_NAME_KEY
FROM T_WC_T2S_PERSON_ALSO_KNOWN_AS
WHERE PERSON_NAME_KEY = 'हयाओमियाजाकी';

SELECT '1b. Stored Devanagari alias of 608' AS SECTION;

SELECT ID_ROW, ID_PERSON, PERSON_NAME, LANGUAGE_FAMILY, PERSON_NAME_NORM, PERSON_NAME_KEY
FROM T_WC_T2S_PERSON_ALSO_KNOWN_AS
WHERE ID_PERSON = 608 AND LANGUAGE_FAMILY = 'Devanagari';

SELECT '1c. Anchors directed by 608' AS SECTION;

SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE
FROM T_WC_T2S_MOVIE
JOIN T_WC_T2S_PERSON_MOVIE ON T_WC_T2S_PERSON_MOVIE.ID_MOVIE = T_WC_T2S_MOVIE.ID_MOVIE
WHERE T_WC_T2S_PERSON_MOVIE.ID_PERSON = 608
  AND T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE = 'crew'
  AND T_WC_T2S_PERSON_MOVIE.CREW_DEPARTMENT = 'Directing'
  AND T_WC_T2S_MOVIE.ID_MOVIE IN (129, 128);

-- ---------------------------------------------------------------------------
-- 2. The evaluation. Category 43: Persons - Non-Latin queries.
-- ---------------------------------------------------------------------------
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which movies did हयाओ मियाजाकी direct?',
       'Quels films हयाओ मियाजाकी a-t-il réalisés ?',
       1, 0, 43, 0, CURDATE(), NOW(),
       '(?i)(Hayao Miyazaki|ID_PERSON ?= ?608)',
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (129, 128)',
       'Hayao Miyazaki in Devanagari, near spelling: the stored alias without the nukta under ja. Before TMDB-PERSON-PREPROCESS-008 the vowel signs of the abugidas turned into spaces in the normalized alias keys, so a near spelling was scored syllable by syllable. On 2026-10-05, after the fix, it resolves through T_WC_T2S_PERSON_ALSO_KNOWN_AS at fuzz_ratio 96.3 (threshold 87.8). The name is the same in both languages on purpose, it must not be translated.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which movies did हयाओ मियाजाकी direct?') AS existing);

-- ---------------------------------------------------------------------------
-- 3. After. Must return one row, category 43.
-- ---------------------------------------------------------------------------
SELECT '3. After insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, QUESTION, QUESTION_FR,
       ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Which movies did हयाओ मियाजाकी direct?';
