-- Year-bound assertions for the evaluation bank (FASTAPI-TEXT2SQL-187).
--
-- ALREADY APPLIED on 2026-08-03. The 18 UPDATEs landed, and the INSERT created
-- evaluations 2444 ("List movie directors born in the fifties") and 2445 ("Which
-- actors died in the nineties?"). Kept in the repo as the record of what was
-- written and why.
-- DO NOT RE-RUN AS IS: the UPDATEs are idempotent, the INSERT is not. It carries
-- no guard, so a second run would create a duplicate pair of evaluations. To
-- replay only the assertions, run the file down to section 5 and stop there.
--
-- WHY THIS FILE EXISTS
-- The prompt used to widen every year by one on each side, so "the seventies"
-- generated RELEASE_YEAR BETWEEN 1969 AND 1980. The bank already held 29 questions
-- naming a decade, and not one of them could fail on it: their assertions were
-- either absent or of the form `ID_MOVIE IN (...)`, which only requires the listed
-- rows to be present and accepts extra ones. A widened bound adds rows, so that
-- form is blind to exactly this defect.
--
-- The instrument that catches it is ASSERTIONS_SQL_QUERY: a regex read against the
-- generated SQL, in the style already used by evaluation 2162. Each assertion below
-- states the bounds the question names, and nothing else, so it stays true after any
-- database refresh.
--
-- HOW TO RUN
--   mysql --user=<user> --password <db> < eval/assertions-year-bounds.sql
-- Then re-run the evaluator so the JSON exports under eval/data/evaluation/ pick the
-- new assertions up (the exporter rewrites a file whose content changed).
--
-- TWO TRAPS WORTH KNOWING
-- 1. Backslashes are doubled in every literal below. MariaDB treats a backslash as an
--    escape inside a string literal, so '\b' would be stored as a backspace and '\s'
--    as a plain 's'. Written '\\b' / '\\s', the column receives the regex intended.
-- 2. An assertion is scored against BOTH the English and the French run of the same
--    evaluation. Every regex below was checked against the SQL generated for both
--    question forms (api 1.1.17 prompt, gpt-4o) before being written here.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 1. Decades on movies: the bounds are the ten years named, nothing wider.
-- ---------------------------------------------------------------------------

-- 2195 "list drama movies from the Sight and Sound list that were released in the 70s"
-- The question of the video rehearsal that surfaced the defect.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1970\\s+AND\\s+1979\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2195;

-- 176 "Which movies in the Criterion Collection were released in the 1950s?"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 176;

-- 2165 "List Sci-Fi movies released in the fifties"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2165;

-- 2168 "Technicolor long feature movies released in the 50s"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2168;

-- 2255 "English language comedy films from the 1950s with IMDb rating > 7 and Criterion spine"
-- A decade bound that must hold while several other filters are stacked on it.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2255;

-- 326 "Films en technicolor realises dans les annees 50" (French original)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 326;

-- 390 "Films francais des annees 50" (French original)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 390;

-- 254 "Film italien en Technicolor sortis dans les annees 60" (French original)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1960\\s+AND\\s+1969\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 254;

-- 2339 "What color movies used Technicolor technology in the forties?"
-- Keeps the existing ID_TECHNICAL assertion untouched: it lives in the same column,
-- so both conditions are expressed as two lookaheads.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bID_TECHNICAL\\s*=\\s*4\\b)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1940\\s+AND\\s+1949\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2339;

-- 311 "Actors of The Big Sleep movie shot in the 40s"
-- A decade bound on a question whose answer entity is a person, not a movie.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1940\\s+AND\\s+1949\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 311;

-- 202 "What movies were produced by Warner Bros in the 1990s?"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+1990\\s+AND\\s+1999\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 202;

-- ---------------------------------------------------------------------------
-- 2. Decades on series: the same gesture, on FIRST_AIR_YEAR.
-- ---------------------------------------------------------------------------

-- 2383 "TV series from the 1990s"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bFIRST_AIR_YEAR\\s+BETWEEN\\s+1990\\s+AND\\s+1999\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2383;

-- 2384 "Best crime series from the 2010s"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bFIRST_AIR_YEAR\\s+BETWEEN\\s+2010\\s+AND\\s+2019\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2384;

-- 2282 "List French TV Series created in the sixties"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bFIRST_AIR_YEAR\\s+BETWEEN\\s+1960\\s+AND\\s+1969\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2282;

-- ---------------------------------------------------------------------------
-- 3. Open intervals: an inequality stays an inequality, with no margin added.
-- ---------------------------------------------------------------------------

-- 168 "Which movies starring Audrey Hepburn were released before 1965?"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s*<\\s*1965\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 168;

-- 2332 "List movies with Sharon Stone released before 1970"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s*<\\s*1970\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2332;

-- ---------------------------------------------------------------------------
-- 4. A year on a person: one birth date, one death date, never widened.
-- ---------------------------------------------------------------------------

-- 2250 "Which movie directors died in 2025?"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bDEATH_YEAR\\s*=\\s*2025\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2250;

-- ---------------------------------------------------------------------------
-- 5. Non-regression: the tolerance must survive where it is justified.
--    A title plus a year is a disambiguation, and a film can legitimately carry
--    three different dates (copyright, festival premiere, theatrical release).
-- ---------------------------------------------------------------------------

-- 2235 "Tommy (1975)" — keeps its ID_MOVIE == 11326 result assertion.
-- Two accepted forms: the model either folds the tolerance into literal bounds
-- (1974 / 1976) or leaves the arithmetic around the resolved placeholder
-- (BETWEEN 1975 - 1 AND 1975 + 1). Both express the same interval, so both pass.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bRELEASE_YEAR\\s+BETWEEN\\s+(?:1974\\s+AND\\s+1976|1975\\s*-\\s*1\\s+AND\\s+1975\\s*\\+\\s*1))',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2235;

-- ---------------------------------------------------------------------------
-- 6. Two questions the bank did not have at all: a decade on a person.
--    Category 35 = "Persons - Birth and Death Queries".
-- ---------------------------------------------------------------------------

INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
VALUES
  ('List movie directors born in the fifties',
   'Listez les réalisateurs de films nés dans les années 50',
   1, 0, 35, 0, CURDATE(), NOW(),
   '(?is)(?=.*\\bBIRTH_YEAR\\s+BETWEEN\\s+1950\\s+AND\\s+1959\\b)',
   'COUNT(*) > 0',
   'FASTAPI-TEXT2SQL-187. A decade on a birth year. The +-1 tolerance written for movie release years has no justification here: a person has one birth date, so a director born in 1949 or in 1960 is simply a wrong answer.'),
  ('Which actors died in the nineties?',
   'Quels acteurs sont morts dans les années 90 ?',
   1, 0, 35, 0, CURDATE(), NOW(),
   '(?is)(?=.*\\bDEATH_YEAR\\s+BETWEEN\\s+1990\\s+AND\\s+1999\\b)',
   'COUNT(*) > 0',
   'FASTAPI-TEXT2SQL-187. Same gesture on a death year, the other column the bank never measured under this angle.');

-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 60) AS QUESTION, ASSERTIONS_SQL_QUERY
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (168, 176, 202, 254, 311, 326, 390, 2165, 2168, 2195,
                            2235, 2250, 2255, 2282, 2332, 2339, 2383, 2384)
   OR LONG_DESC LIKE 'FASTAPI-TEXT2SQL-187%'
ORDER BY ID_T2S_EVALUATION;
