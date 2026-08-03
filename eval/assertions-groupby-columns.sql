-- Aggregation assertions for the evaluation bank (FASTAPI-TEXT2SQL-191, and -186 with it).
--
-- WHY THIS FILE EXISTS
-- A ranking question ("which directors have the most films in X") answers with entity rows
-- plus a count. Two things can go wrong in the generated SQL, and the bank could catch
-- neither:
--   -191  the SELECT drops the image column (PROFILE_PATH / LOGO_PATH / POSTER_PATH) to
--         keep the GROUP BY short. The counts are right, the screen shows nameplates with
--         no faces. NO result assertion can see this: the rows are there, a column is not.
--   -186  the query emits COUNT() with NO GROUP BY. MariaDB then returns ONE aggregate row
--         and fills the other columns from an arbitrary record, which is how "the directors
--         with the most films" came back as a single name.
-- The bank holds 85 counting or ranking questions and exactly ONE carried an SQL assertion.
--
-- One regex covers both defects, because both are visible in the same place: the query must
-- COUNT, must GROUP BY, and must still project the entity id and its image column.
--
-- HOW TO RUN
--   mysql --user=<user> --password <db> < eval/assertions-groupby-columns.sql
-- Then re-run the evaluator so the JSON exports under eval/data/evaluation/ pick it up.
--
-- TWO TRAPS, THE SAME AS THE YEAR-BOUND BATCH
-- 1. Backslashes are doubled in every literal: MariaDB eats one level inside a string, so
--    '\\b' is what puts a real \b in the column.
-- 2. Each assertion is scored against BOTH the English and the French run. All five regexes
--    below were checked against the SQL generated for both question forms before being
--    written here (api 1.1.17 prompt + the -191 rule, gpt-4o).
--
-- NOT APPLIED YET as of 2026-08-03. The UPDATEs are idempotent; the INSERT is not.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 1. Existing ranking questions: assert the shape, not the names.
--    The names would need maintaining at every database refresh; the shape will not.
-- ---------------------------------------------------------------------------

-- 45 "List the movie directors with the most movies in the Criterion collection and tell how
--     many movies for each director" (keeps its ID_PERSON IN (...) result assertion)
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_PERSON\\b)(?=.*\\bPROFILE_PATH\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 45;

-- 413 "Liste the directors with the most movies in the Sight and Sound list"
--     This is act 5 of video #3, the question that produced ten faceless cards.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_PERSON\\b)(?=.*\\bPROFILE_PATH\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 413;

-- 446 "Who are the directors with the most movies in the Criterion Collection and give the
--      count of movies for each one"
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_PERSON\\b)(?=.*\\bPROFILE_PATH\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 446;

-- 352 "Quels sont les 10 realisateurs avec le plus de films dans la collection Criterion ?"
--     Named in the permanent rule of 2026-08-02 as the evaluation that stated the defect
--     word for word and could never fail, for want of an assertion. It can now.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_PERSON\\b)(?=.*\\bPROFILE_PATH\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 352;

-- 197 "Which cinematographers worked on the most Best Picture winners?"
--     Same shape on a different department and a different filter, so the rule is not
--     verified only on directors and on curated lists.
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_PERSON\\b)(?=.*\\bPROFILE_PATH\\b)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 197;

-- ---------------------------------------------------------------------------
-- 2. Two entities the bank never ranked: a company (LOGO_PATH) and a series
--    (POSTER_PATH). The contract has three image columns; testing one of them
--    only proves the rule for persons.
--    Category 7 = "Production Companies & Networks Queries", 40 = "TV Series - Complex Queries".
-- ---------------------------------------------------------------------------

INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
VALUES
  ('Which production companies produced the most movies with a budget over 200 million dollars?',
   'Quelles sociétés de production ont produit le plus de films avec un budget supérieur à 200 millions de dollars ?',
   1, 0, 7, 0, CURDATE(), NOW(),
   '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_COMPANY\\b)(?=.*\\bLOGO_PATH\\b)',
   'COUNT(*) > 0',
   'FASTAPI-TEXT2SQL-191. A ranking on companies, so the rule is verified on LOGO_PATH and not only on PROFILE_PATH. A company card with no logo is the same defect as a person card with no portrait.'),
  ('Which TV series won the most awards?',
   'Quelles séries télévisées ont remporté le plus de récompenses ?',
   1, 0, 40, 0, CURDATE(), NOW(),
   '(?is)(?=.*\\bCOUNT\\s*\\()(?=.*\\bGROUP\\s+BY\\b)(?=.*\\bID_SERIE\\b)(?=.*\\bPOSTER_PATH\\b)',
   'COUNT(*) > 0',
   'FASTAPI-TEXT2SQL-191. A ranking on series, for POSTER_PATH. Deliberately about awards and not about episode counts: NUMBER_OF_EPISODES is a column on the series row, so "the most episodes" needs no aggregation at all and would test nothing.');

-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 60) AS QUESTION, ASSERTIONS_SQL_QUERY
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (45, 197, 352, 413, 446)
   OR LONG_DESC LIKE 'FASTAPI-TEXT2SQL-191%'
ORDER BY ID_T2S_EVALUATION;
