-- ============================================================================
-- Evaluations 291, 2151, 2155, 2156: rewrite the assertions still written against
-- the Wikidata item model, now that locations are a first-class entity
-- (EVALUATIONS-012)
-- ============================================================================
--
-- NOT YET APPLIED. Written 2026-09-24.
--
-- THE PROBLEM. Since FASTAPI-TEXT2SQL-247 the API answers location questions from
-- the locations read-model (T_WC_T2S_LOCATION, T_WC_T2S_MOVIE_LOCATION with
-- LOCATION_ROLE 'narrative' or 'filming'). Four evaluations still assert on the old
-- shape (T_WC_T2S_ITEM, ITEM_LABEL, ID_WIKIDATA, property P840) and fail on correct
-- answers. Campaign 001.001.019_en of 2026-09-23:
--
--   291   Movies happening in Naples              SQL regex wants ID_PROPERTY = 'P840'
--   2151  In which city ... Pulp Fiction ...       result wants column ITEM_LABEL
--   2155  Narrative locations of Pulp Fiction      result wants column ITEM_LABEL
--   2156  Where was 2001 A Space Odyssey shot?     result wants column ID_WIKIDATA
--
-- The answers were right: Los Angeles (ID_LOCATION 4) for Pulp Fiction, Namibia and
-- the studios for 2001, Naples films with LOCATION_ROLE = 'narrative'. All four were
-- green in 1.1.18 and count among the 44 regressions of the 1.1.19 analysis
-- (Nestor, projets/t2s-backlog/topics/eval-run-1-1-19-en-analysis.md, cause E).
--
-- THE NEW ASSERTIONS, two per evaluation:
--   (a) a result anchor on ID_LOCATION (or ID_MOVIE for 291). ID_LOCATION is stable
--       since TMDB-MOVIE-PREPROCESS-014 was fixed on 2026-09-13 (ID_WIKIDATA is the
--       unique business key, the integer id no longer moves on rebuild).
--   (b) a SQL regex on LOCATION_ROLE, which is what P840 used to check: "happening
--       in" and "narrative locations" are the narrative role (P840), "shot" is the
--       filming role (P915). A query that confuses the two roles fails (b) even when
--       the place happens to be right, which is the case for Los Angeles.
--
-- TESTED OFFLINE on 2026-09-24 against the stored JSON_RESULT of 1.1.19 EN, with
-- evaluate_dataframe_assertions() and re.search() exactly as text2sql-eval.py calls
-- them (html.unescape first): all four pass (a) and (b), and the opposite-role regex
-- matches none of the four queries. French not tested: no 1.1.19 FR run exists yet.
--
-- ESCAPING. Quotes are stored as &#039; and &quot;, as in the rest of the column;
-- the evaluator unescapes before parsing. Backslashes are doubled for MariaDB.
--
-- GUARDS. Every UPDATE withdraws itself if the value changed since the export of
-- 2026-09-23: result assertions are guarded on their exact current value (or on
-- being empty), SQL assertions on being empty, or on still naming P840 for 291.
-- Re-running the file is a no-op.
--
-- NO REFRESH SQL on these four, on purpose: the anchors are hand-chosen places and
-- films, and process 70 would replace them with a popularity list.
--
-- ⚠ COLLATION. Run with --force if a comparison returns ERROR 1267, as for
-- fix-44-criterion-spine-null.sql.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. BEFORE. The four current values, to compare with the guards of section 2.
-- ---------------------------------------------------------------------------
SELECT '0. Before' AS SECTION;

SELECT ID_T2S_EVALUATION,
       LEFT(QUESTION, 50)               AS QUESTION,
       ASSERTIONS_QUERY_RESULT,
       LEFT(ASSERTIONS_SQL_QUERY, 60)   AS ASSERTIONS_SQL_QUERY,
       ASSERTION_REFRESH_SQL            AS REFRESH_SQL_MUST_BE_NULL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (291, 2151, 2155, 2156);

-- ---------------------------------------------------------------------------
-- 1. CHECK THE ANCHORS against the data rather than trusting the run export.
--    1a must show ID_LOCATION 4 = Los Angeles as a NARRATIVE location of Pulp
--       Fiction (ID_MOVIE 680).
--    1b must show 697, 4957 and 5012 as FILMING locations of 2001: A Space Odyssey
--       (ID_MOVIE 62). The old assertion also named a fourth QID, Q2278256, which
--       the 1.1.19 answer did not return: 1c says whether it exists in the
--       read-model at all. If it exists, is not DELETED and is linked as filming,
--       add its ID_LOCATION to the 2156 list in section 2 before running it.
--    1d must show the three anchor films linked to Naples as NARRATIVE location.
-- ---------------------------------------------------------------------------
SELECT '1a. Pulp Fiction, narrative locations' AS SECTION;

SELECT ml.ID_MOVIE, ml.LOCATION_ROLE, l.ID_LOCATION, l.ID_WIKIDATA, l.LOCATION_NAME, l.LOCATION_TYPE, l.DELETED
FROM T_WC_T2S_MOVIE_LOCATION ml
JOIN T_WC_T2S_LOCATION l ON l.ID_LOCATION = ml.ID_LOCATION
WHERE ml.ID_MOVIE = 680
ORDER BY ml.LOCATION_ROLE, l.ID_LOCATION;

SELECT '1b. 2001: A Space Odyssey, filming locations' AS SECTION;

SELECT ml.ID_MOVIE, ml.LOCATION_ROLE, l.ID_LOCATION, l.ID_WIKIDATA, l.LOCATION_NAME, l.LOCATION_TYPE, l.DELETED
FROM T_WC_T2S_MOVIE_LOCATION ml
JOIN T_WC_T2S_LOCATION l ON l.ID_LOCATION = ml.ID_LOCATION
WHERE ml.ID_MOVIE = 62
ORDER BY ml.LOCATION_ROLE, l.ID_LOCATION;

SELECT '1c. The four QIDs of the old 2156 assertion' AS SECTION;

SELECT ID_LOCATION, ID_WIKIDATA, LOCATION_NAME, LOCATION_TYPE, DELETED
FROM T_WC_T2S_LOCATION
WHERE ID_WIKIDATA IN ('Q1030', 'Q192017', 'Q2278256', 'Q4739371');

SELECT '1d. Naples anchors, must be 3 rows with LOCATION_ROLE narrative' AS SECTION;

SELECT ml.ID_MOVIE, ml.LOCATION_ROLE, l.ID_LOCATION, l.ID_WIKIDATA, l.LOCATION_NAME
FROM T_WC_T2S_MOVIE_LOCATION ml
JOIN T_WC_T2S_LOCATION l ON l.ID_LOCATION = ml.ID_LOCATION
WHERE l.ID_WIKIDATA = 'Q2634'
  AND ml.ID_MOVIE IN (722778, 58383, 49687);

-- ---------------------------------------------------------------------------
-- 2. THE CORRECTION.
-- ---------------------------------------------------------------------------

-- 291 · Movies happening in Naples
--   result: three films set in Naples, from the 1.1.19 answer (The Hand of God,
--   Hands Over the City, Marriage Italian Style)
--   SQL:    the narrative role, replacing the P840 / ITEM_LABEL regex
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (722778, 58383, 49687)',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 291
  AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)\\bLOCATION_ROLE\\s*=\\s*[&#039;&quot;]narrative[&#039;&quot;]',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-24 (EVALUATIONS-012): assertions rewritten for the locations read-model. The SQL regex checks LOCATION_ROLE = narrative, which is what P840 used to check; the result anchors three films set in Naples.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 291
  AND ASSERTIONS_SQL_QUERY LIKE '%P840%';

-- 2151 · In which city the action of movie Pulp Fiction takes place?
--   result: Los Angeles, and every row is a city
--   SQL:    the narrative role, so that a filming location never passes for the setting
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_LOCATION IN (4) AND LOCATION_TYPE == &#039;city&#039;',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-24 (EVALUATIONS-012): assertions rewritten for the locations read-model. Result: ID_LOCATION 4 (Los Angeles) and every row a city. SQL: LOCATION_ROLE = narrative, since the setting of a film and the place it was shot are different questions.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2151
  AND ASSERTIONS_QUERY_RESULT = 'ITEM_LABEL == &#039;Los Angeles&#039;';

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)\\bLOCATION_ROLE\\s*=\\s*[&#039;&quot;]narrative[&#039;&quot;]',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2151
  AND (ASSERTIONS_SQL_QUERY IS NULL OR ASSERTIONS_SQL_QUERY = '');

-- 2155 · What are the narrative locations of the movie Pulp Fiction?
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_LOCATION IN (4)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-24 (EVALUATIONS-012): assertions rewritten for the locations read-model. Result: ID_LOCATION 4 (Los Angeles). SQL: LOCATION_ROLE = narrative.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2155
  AND ASSERTIONS_QUERY_RESULT = 'ITEM_LABEL == &#039;Los Angeles&#039;';

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)\\bLOCATION_ROLE\\s*=\\s*[&#039;&quot;]narrative[&#039;&quot;]',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2155
  AND (ASSERTIONS_SQL_QUERY IS NULL OR ASSERTIONS_SQL_QUERY = '');

-- 2156 · Where was shot the movie 2001 A Space Odyssey?
--   result: Namibia and the two studios returned in 1.1.19 (see 1b and 1c)
--   SQL:    the filming role
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_LOCATION IN (697, 4957, 5012)',
    LONG_DESC = CONCAT(COALESCE(LONG_DESC, ''), ' 2026-09-24 (EVALUATIONS-012): assertions rewritten for the locations read-model. Result: ID_LOCATION 697, 4957, 5012 (Namibia and two studios), replacing four QIDs. SQL: LOCATION_ROLE = filming.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2156
  AND ASSERTIONS_QUERY_RESULT = 'ID_WIKIDATA IN (&#039;Q1030&#039;, &#039;Q192017&#039;, &#039;Q2278256&#039;, &#039;Q4739371&#039;)';

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_SQL_QUERY = '(?is)\\bLOCATION_ROLE\\s*=\\s*[&#039;&quot;]filming[&#039;&quot;]',
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2156
  AND (ASSERTIONS_SQL_QUERY IS NULL OR ASSERTIONS_SQL_QUERY = '');

-- ---------------------------------------------------------------------------
-- 3. AFTER. Eight UPDATE statements, eight rows changed on a first run, zero on a
--    re-run. Expect every ASSERTIONS_QUERY_RESULT on ID_LOCATION or ID_MOVIE,
--    and every ASSERTIONS_SQL_QUERY on LOCATION_ROLE. If one still shows ITEM_LABEL,
--    P840 or a QID, its guard withdrew: compare with section 0.
-- ---------------------------------------------------------------------------
SELECT '3. After' AS SECTION;

SELECT ID_T2S_EVALUATION,
       ASSERTIONS_QUERY_RESULT,
       ASSERTIONS_SQL_QUERY,
       ASSERTION_REFRESH_SQL AS MUST_STAY_NULL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (291, 2151, 2155, 2156);

-- ---------------------------------------------------------------------------
-- 4. RESCORE. Re-run Phase 20 alone: scoring is offline against the stored
--    JSON_RESULT, no API call, no token. The four 1.1.19 EN executions must turn
--    green. Then run the export (phase 31) so eval/data/evaluation/ carries the new
--    assertions.
-- ---------------------------------------------------------------------------
