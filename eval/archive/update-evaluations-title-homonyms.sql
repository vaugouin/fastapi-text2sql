-- ============================================================================
-- Thirteen title lookups: the assertion keeps only the films that carry the
-- title in BOTH languages (EVALUATIONS-020)
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-25.
--
-- THE PROBLEM. A title lookup ("Movie City Lights" / "Film Les lumieres de la
-- ville") carries one assertion for both languages, generated from the English
-- result, so it lists every English homonym: four films called "City Lights".
-- Only one of them, Chaplin's (901), is "Les Lumieres de la ville" in French. The
-- French answer is right and scores 0. In campaign 001.001.019 the thirteen
-- evaluations below pass in English and fail in French for that reason alone, and
-- all of them already failed in French in 1.1.18.
--
-- THE RULE. The new list is the intersection of the old list with the films the
-- French question returns, i.e. the films that carry the English title AND the
-- French title. City Lights keeps only Chaplin. Where several films share both
-- titles (The Jungle Book 1967, 1994 and 2016), they all stay. The films dropped
-- are homonyms under another French title: a French speaker asking for "Les
-- Lumieres de la ville" is not asking for the 2014 "City Lights".
--
-- TESTED OFFLINE on 2026-09-25 against the stored JSON_RESULT of 1.1.19, with
-- evaluate_dataframe_assertions() as text2sql-eval.py calls it: all thirteen pass
-- in ENGLISH and in FRENCH. The English side cannot regress: the new list is a
-- subset of the old one, and IN is coverage.
--
-- GUARDS. Each UPDATE is guarded on the exact current value (export of
-- 2026-09-24); a value edited since makes it a no-op, and a re-run changes
-- nothing. None of the thirteen carries an ASSERTION_REFRESH_SQL, so process 70
-- will not rewrite them.
--
-- Run: ~/docker/tools/runsqlvaugouindb.sh <this file>, then rescore BOTH
-- languages with Phase 20 (no API call): the thirteen French executions turn
-- green, the English ones stay green.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '0. Before' AS SECTION;
SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION, LEFT(QUESTION_FR, 45) AS QUESTION_FR,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL AS REFRESH_SQL_MUST_BE_NULL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (388, 618, 626, 754, 832, 890, 923, 1001, 1018, 1039, 1046, 1049, 1093);

-- ---------------------------------------------------------------------------
-- 1. THE CORRECTION, one UPDATE per evaluation.
-- ---------------------------------------------------------------------------

-- 388 · "Movie black narcissus" / "Film Le Narcisse noir"
--   keep: 16391 Black Narcissus (1947)
--   drop: 1316828 (1929)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (16391)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (16391); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 388
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (16391, 1316828)';

-- 618 · "Movie city lights" / "Film Les lumières de la ville"
--   keep: 901 City Lights (1931)
--   drop: 277223 (2014); 423278 (2016); 632091 (1972)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (901)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (901); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 618
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (901, 277223, 423278, 632091)';

-- 626 · "Movie The Beach" / "Le film La Plage"
--   keep: 228587 The Beach (1992); 1907 The Beach (2000); 451432 The Beach (1978)
--   drop: 546702 (1964); 1491582 (1973)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (228587, 1907, 451432)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (228587, 1907, 451432); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 626
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (228587, 1907, 546702, 451432, 1491582)';

-- 754 · "Movie the jungle book" / "Le film Le Livre de la jungle"
--   keep: 9325 The Jungle Book (1967); 278927 The Jungle Book (2016); 10714 The Jungle Book (1994)
--   drop: 431036 (1990); 1165601 (1992)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (9325, 278927, 10714)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (9325, 278927, 10714); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 754
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (9325, 431036, 278927, 10714, 1165601)';

-- 832 · "Movie the good the bad the ugly" / "Film Le bon, la brute et le truand"
--   keep: 429 The Good, the Bad and the Ugly (1966)
--   drop: 1122459 (2015)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (429)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (429); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 832
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (429, 1122459)';

-- 890 · "Movie the merchant of Venice" / "Le film Le Marchand de Venise"
--   keep: 11162 The Merchant of Venice (2004); 469590 The Merchant of Venice (1953)
--   drop: 261856 (2001); 374517 (1969); 405738 (1972); 119933 (1980); 109397 (1973); 247508 (1996); 429615 (1914); 1413020 (1916); 194034 (1911); 1004336 (1919)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (11162, 469590)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (11162, 469590); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 890
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (261856, 374517, 405738, 119933, 109397, 11162, 247508, 429615, 1413020, 194034, 469590, 1004336)';

-- 923 · "Movie Jubilee" / "Film Jubilé"
--   keep: 41426 Jubilee (1978)
--   drop: 794834 (2009); 881991 (1944); 454269 (1983); 291312 (2000); 1420089 (1963)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (41426)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (41426); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 923
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (794834, 881991, 454269, 41426, 291312, 1420089)';

-- 1001 · "Movie \r\n20,000 Leagues Under the Sea" / "Film  20 000 lieues sous les mers"
--   keep: 173 20,000 Leagues Under the Sea (1954); 577911 20,000 Leagues Under the Sea (1973); 30266 20,000 Leagues Under the Sea (1916); 79380 20,000 Leagues Under the Sea (1985)
--   drop: 662966 (1980); 119784 (2004); 114136 (1907); 2965 (1997)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (173, 577911, 30266, 79380)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (173, 577911, 30266, 79380); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1001
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (173, 577911, 662966, 30266, 79380, 119784, 114136, 2965)';

-- 1018 · "Movie some like it hot" / "Film Certains l'aiment chaud"
--   keep: 239 Some Like It Hot (1959)
--   drop: 160688 (1939); 496723 (1964); 433605 (2016)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (239)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (239); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1018
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (239, 160688, 496723, 433605)';

-- 1039 · "Movie stagecoach" / "Film La chevauchée fantastique"
--   keep: 995 Stagecoach (1939)
--   drop: 39287 (1966); 33410 (1986)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (995)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (995); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1039
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (995, 39287, 33410)';

-- 1046 · "Movie Alice Through the Looking Glass" / "Film Alice de l'autre côté du miroir"
--   keep: 198916 Alice Through the Looking Glass (1982); 241259 Alice Through the Looking Glass (2016); 1219178 Alice Through the Looking Glass (2003)
--   drop: 362241 (1973); 179721 (1966); 176462 (1987); 15162 (1998)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (198916, 241259, 1219178)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (198916, 241259, 1219178); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1046
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (198916, 362241, 241259, 179721, 176462, 15162, 1219178)';

-- 1049 · "Movie Brief Encounter" / "Film Brève rencontre"
--   keep: 851 Brief Encounter (1945); 115497 Brief Encounter (1976)
--   drop: 429532 (1988)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (851, 115497)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (851, 115497); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1049
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (851, 115497, 429532)';

-- 1093 · "Movie \\r\\n20,000 Leagues Under the Sea" / "Film \r\n20 000 lieues sous les mers"
--   keep: 173 20,000 Leagues Under the Sea (1954); 577911 20,000 Leagues Under the Sea (1973); 30266 20,000 Leagues Under the Sea (1916); 79380 20,000 Leagues Under the Sea (1985)
--   drop: 662966 (1980); 119784 (2004); 114136 (1907); 2965 (1997)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (173, 577911, 30266, 79380)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-25 (EVALUATIONS-020): assertion narrowed to the films that carry the title in both languages (173, 577911, 30266, 79380); the English homonyms under another French title are no longer required.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 1093
  AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (173, 577911, 662966, 30266, 79380, 119784, 114136, 2965)';

-- ---------------------------------------------------------------------------
-- 2. AFTER. Thirteen rows changed on a first run, zero on a re-run.
-- ---------------------------------------------------------------------------
SELECT '2. After' AS SECTION;
SELECT ID_T2S_EVALUATION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (388, 618, 626, 754, 832, 890, 923, 1001, 1018, 1039, 1046, 1049, 1093);
