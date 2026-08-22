-- Result-set assertions for the 22 entity-type evaluations (2449-2470).
--
-- NOT YET APPLIED. Generated 2026-08-22.
--
-- WHY THIS FILE EXISTS
-- The 22 evaluations added on 2026-08-21 carried ASSERTIONS_ENTITY_EXTRACTION and nothing
-- else. Twenty-one of them scored 1.0 on extraction in campaign 1.1.18, and the bank called
-- them green. What they actually returned:
--   #2458 #2459 #2460 #2462  zero rows, both languages
--   #2452                    100 rows in English, zero in French
--   #2469                    one series nominated for the Primetime Emmy Award
--   #2470                    two actors nominated for a Golden Globe
--   #2468                    one actor dead of cancer, and it is Richard Feynman
--   #2465                    "actresses born in 1934" containing Jiro Sakagami
--   #2454                    75 AMC series in English, 6 in French
-- An extraction assertion measures the first stage of the pipeline. It is an obligation of
-- means. None of the failures above touch it, so none of them were caught. This file adds
-- the obligation of result.
--
-- THE THREE LEVELS
--   Level 1, the floor      COUNT(*) > 0, or a higher bound where the true cardinality is
--                           known to be large. Catches the empty result set.
--   Level 2, the anchor     ID_x IN (...) on one or two entities that must be present.
--                           IN is coverage, not equality: extra rows never break it. Anchors
--                           are taken from the top rows of the observed English run so they
--                           survive ORDER BY ... LIMIT 100 in either language.
--   Level 3, the counter-   ID_x NOT IN (...) on an entity that must NOT appear. This is the
--            example        only level that catches a query returning too much, which is the
--                           failure mode an anchor alone will always call a success.
--
-- IDs are TMDb identifiers, the same space the bank already uses (27205 = Inception).
-- The > sign is stored HTML-escaped as &gt;, matching what is already in the column;
-- evaluate_dataframe_assertions() calls html.unescape() before parsing.
--
-- NOTHING HERE OVERWRITES A HAND-WRITTEN VALUE
-- Checked against the full export of 2026-08-22, once phase 31 started carrying every
-- column. Every statement is guarded so that it withdraws itself rather than clobbering:
--   SECTION A  guarded on an empty ASSERTIONS_QUERY_RESULT
--   SECTION B  guarded on the EXACT current value, so an edit made since makes it a no-op
--   SECTION C  guarded on an empty ASSERTION_REFRESH_SQL
--   the three counter-examples (#2456, #2465, #2468) additionally refuse to write onto a row
--   that carries a refresh SQL, because process 70 would destroy them at its next pass
-- State observed on 2026-08-22 across 2449-2470: eight hand-written result assertions
-- (#2452, #2458, #2459, #2460, #2461, #2462, #2464, #2468) and no refresh SQL at all. The
-- one refresh SQL in the neighbourhood is #2471, which this file does not touch.
--
-- HOW TO RUN
--   mysql <db> < eval/assertions-query-result-24xx.sql
-- then re-run phase 20 only. Scoring is offline against the stored JSON_RESULT, so no API
-- call and no LLM token is spent re-scoring the existing campaign.


-- =====================================================================================
-- SECTION A. The fourteen evaluations with no result assertion at all.
-- Guarded on an empty column: idempotent, and never overwrites a hand-written assertion.
-- =====================================================================================

-- #2449 Movies still in production. Cardinality drifts with every TMDb sync, so the floor
-- is all that can be asserted. It still catches a broken status filter.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0'
  WHERE ID_T2S_EVALUATION = 2449
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2450 Movies in post-production. Same reasoning.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0'
  WHERE ID_T2S_EVALUATION = 2450
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2451 Canceled TV series. Firefly is the canonical cancelled series and will not leave
-- the set.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_SERIE IN (1437)'
  WHERE ID_T2S_EVALUATION = 2451
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2453 Talk shows. Last Week Tonight, first row of the observed run.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_SERIE IN (60694)'
  WHERE ID_T2S_EVALUATION = 2453
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2454 Series produced by AMC. English returned 75 rows, French 6. The floor at 20 is what
-- turns that gap into a failing score instead of an invisible one.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 20 AND ID_SERIE IN (1396, 60059)'
  WHERE ID_T2S_EVALUATION = 2454
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2455 Apple TV+ series. Ted Lasso and Severance are the two flagships.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_SERIE IN (97546, 95396)'
  WHERE ID_T2S_EVALUATION = 2455
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2456 Academy Award for Best Picture nominees. Verified: the query does filter on
-- NOMINATION_NAME and The Dark Knight is correctly absent. The NOT IN encodes the 2009 snub
-- and is the guard that would catch the filter being dropped in favour of a rating ranking,
-- which is exactly what the first ten rows look like at a glance.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_MOVIE IN (278, 238) AND ID_MOVIE NOT IN (155)'
  WHERE ID_T2S_EVALUATION = 2456
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '')
    -- A counter-example cannot survive a living refresh: process 70 replaces the whole
    -- assertion. Refuse to write one onto a row that already carries a refresh SQL.
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');

-- #2457 Movies tagged with Wikidata property P136. P136 is "genre", which nearly every movie
-- carries, so no anchor discriminates anything. Floor only. See SECTION D: this question
-- should be replaced rather than asserted.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0'
  WHERE ID_T2S_EVALUATION = 2457
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2463 Person with IMDb ID nm0000233. Deterministic: exactly one row, Quentin Tarantino.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND ID_PERSON IN (138)'
  WHERE ID_T2S_EVALUATION = 2463
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2465 Actresses born in 1934. The query filters KNOWN_FOR_DEPARTMENT = 'Acting' and never
-- touches GENDER (1 = female, 2 = male), so men come through. Jiro Sakagami was row 2 of the
-- observed run and is the counter-example. A positive assertion on GENDER is impossible for
-- now because the SELECT does not return that column.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_PERSON NOT IN (1179099)'
  WHERE ID_T2S_EVALUATION = 2465
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '')
    -- A counter-example cannot survive a living refresh: process 70 replaces the whole
    -- assertion. Refuse to write one onto a row that already carries a refresh SQL.
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');

-- #2466 Directors who died in 2010. Membership drifts as death data is enriched; floor only.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0'
  WHERE ID_T2S_EVALUATION = 2466
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2467 People who died from a heart attack. DEATH_NAME = 'heart attack' returns 9 rows in
-- English and 7 in French. The floor at 5 passes today and catches a narrower resolution
-- tomorrow, the way 'abdominal cancer' broke #2468.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 5'
  WHERE ID_T2S_EVALUATION = 2467
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2469 Series nominated for the Primetime Emmy Award. The query filters
-- NOMINATION_NAME = 'Primetime Emmy Award' by strict equality, while the real rows are named
-- 'Primetime Emmy Award for Outstanding Drama Series' and the like. One row comes back.
-- No anchor is possible while the query is broken; the floor is what reports it.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 20'
  WHERE ID_T2S_EVALUATION = 2469
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');

-- #2470 Actors nominated for the Golden Globe. The mirror defect: the generic question was
-- resolved to the over-specific 'Golden Globe for Best Actor in a Television Series'.
-- Two rows come back.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 20'
  WHERE ID_T2S_EVALUATION = 2470
    AND (ASSERTIONS_QUERY_RESULT IS NULL OR ASSERTIONS_QUERY_RESULT = '');


-- =====================================================================================
-- SECTION B. Enrichment of the four assertions already written by hand.
-- Each UPDATE is guarded on the EXACT current value, so it applies once, is idempotent on
-- re-run, and silently does nothing if the value has been changed since. That is deliberate:
-- a hand-written assertion is never clobbered by this file.
-- =====================================================================================

-- #2452 List miniseries. The existing floor already catches the French zero. The anchors add
-- the other half: a non-empty result that no longer contains Band of Brothers or Chernobyl
-- is a different failure, and the floor alone would call it a success.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 0 AND ID_SERIE IN (4613, 87108)'
  WHERE ID_T2S_EVALUATION = 2452
    AND ASSERTIONS_QUERY_RESULT = 'COUNT(*)&gt;0';

-- #2461 TMDb movie 27205. An identifier lookup must return exactly one row. Without the
-- count, a query that ignored the identifier and returned 100 movies including Inception
-- would still pass.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND ID_MOVIE IN (27205)'
  WHERE ID_T2S_EVALUATION = 2461
    AND ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (27205)';

-- #2464 Bare nm identifier. Same reasoning, person side.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) == 1 AND ID_PERSON IN (192)'
  WHERE ID_T2S_EVALUATION = 2464
    AND ASSERTIONS_QUERY_RESULT = 'ID_PERSON IN (192)';

-- #2468 Actors who died of cancer. The existing floor already fails on the single row
-- returned. The counter-example names the row: Richard Feynman, a physicist who died of
-- abdominal cancer, surfaced because the resolution collapsed the family "cancer" onto one
-- member of it. When the query is fixed the count will pass; the NOT IN keeps the specific
-- regression from coming back unnoticed.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'COUNT(*) &gt; 10 AND ID_PERSON NOT IN (127293)'
  WHERE ID_T2S_EVALUATION = 2468
    AND ASSERTIONS_QUERY_RESULT = 'COUNT(*)&gt;10'
    -- A counter-example cannot survive a living refresh: process 70 replaces the whole
    -- assertion. Refuse to write one onto a row that already carries a refresh SQL.
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');


-- =====================================================================================
-- SECTION C. Living assertions, via the existing ASSERTION_REFRESH_SQL column.
--
-- The column exists and the machinery is already built. Note the singular: the column is
-- ASSERTION_REFRESH_SQL, not ASSERTIONS_*, and it sits beside ASSERTION_REFRESH_LAST. It
-- does not appear in the phase 31 JSON export, which is the only reason it can look absent
-- from the repo side; the admin form writes it and #2471 already carries one.
--
-- WHO CONSUMES IT
-- tmdb-movie-preprocess, process index 70 (AES-05 / TMDB-MOVIE-PREPROCESS-026). It runs LAST
-- in that pipeline, after POPULARITY is refreshed, re-executes the stored SELECT and
-- REWRITES ASSERTIONS_QUERY_RESULT as "<ID_COL> IN (...)", stamping ASSERTION_REFRESH_LAST.
--
-- CONSEQUENCE THAT MATTERS HERE
-- The rewrite REPLACES the whole assertion. Any floor or counter-example written by hand on
-- an evaluation that also carries a refresh SQL is discarded at the next preprocess run.
-- That is acceptable for #2449 and #2450 because "ID_MOVIE IN (...)" strictly subsumes
-- "COUNT(*) > 0" (an empty DataFrame only ever satisfies COUNT(*) == 0), so the floor set in
-- SECTION A scores the current campaign and is then upgraded, not lost. It would NOT be
-- acceptable on an evaluation whose value is its NOT IN, so never give a refresh SQL to one.
--
-- THE GUARDRAILS THE PROCESS APPLIES (a query failing any of these is skipped, not run)
--   single read-only SELECT, no interior semicolon, no INTO OUTFILE / INTO DUMPFILE
--   exactly one returned column, whose name starts with ID_
--   at least one usable integer id, and at most 50 (the cap that catches a missing LIMIT)
--   max_statement_time = 15 seconds
-- Counts land in the server variables strtmdbmoviepreprocessassertionrefreshcount and
-- ...refreshskipped. HTML entities are unescaped before execution, so a value stored by the
-- admin form as &gt; still runs.
-- =====================================================================================

-- THE ALIGNMENT RULE, learned from the 2026-08-22 export
-- A refresh SQL must mirror the ORDER BY and the joins of the query being evaluated, not
-- merely name a plausible ranking. The evaluated query is capped at LIMIT 100; if the two
-- rankings differ, the generated top-8 can sit entirely outside the first 100 rows and the
-- assertion fails on a query that is correct.
--
-- There is NO single default sort to copy. It depends on the entity and on the question, and
-- the canonical rule is the "Default Sorting" section of data/text_to_sql.md: movies and
-- series rank by IMDB_RATING_WEIGHTED, persons by POPULARITY, anything trending or popular
-- overrides both with POPULARITY, entities within a topic / list / collection / award /
-- nomination use that junction's DISPLAY_ORDER, technicals use MOVIE_COUNT, and an aggregate
-- ranking uses its own aggregate. The bank bears this out: of its 98 refresh queries, the 34
-- asked in a trending or popular phrasing use POPULARITY without exception, while the other
-- 64 spread across seven different sorts.
--
-- The three below were checked one by one against their 1.1.18 execution and all three do
-- rank by IMDB_RATING_WEIGHTED DESC, which is the movie/series default and not a general
-- rule. Read the sort from data/text_to_sql.md, then confirm it against a real execution,
-- before storing any new refresh SQL.
--
-- Style follows the 98 refresh queries already in the bank: SELECT DISTINCT, table-qualified
-- columns, LIMIT 8 (96 of the 98 use exactly that), the same joins as the evaluated query.

-- #2449 and #2450: "in production" and "post-production" are moving targets by definition,
-- exactly the case the column exists for. The COUNT(*) floor written in SECTION A scores
-- until process 70 next runs, then gives way to the generated ID list, which subsumes it.
UPDATE T_WC_T2S_EVALUATION SET ASSERTION_REFRESH_SQL =
  'SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE FROM T_WC_T2S_MOVIE WHERE T_WC_T2S_MOVIE.STATUS = ''In Production'' ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC LIMIT 8'
  WHERE ID_T2S_EVALUATION = 2449
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');

UPDATE T_WC_T2S_EVALUATION SET ASSERTION_REFRESH_SQL =
  'SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE FROM T_WC_T2S_MOVIE WHERE T_WC_T2S_MOVIE.STATUS = ''Post Production'' ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC LIMIT 8'
  WHERE ID_T2S_EVALUATION = 2450
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');

-- #2453 "What talk shows are in the database?". The evaluated query does not filter on
-- SERIE_TYPE but joins T_WC_T2S_SERIE_GENRE on ID_GENRE = 10767, so the refresh joins the
-- same way. Eight ranked anchors are worth more here than the single ID_SERIE IN (60694)
-- from SECTION A, and they maintain themselves.
UPDATE T_WC_T2S_EVALUATION SET ASSERTION_REFRESH_SQL =
  'SELECT DISTINCT T_WC_T2S_SERIE.ID_SERIE FROM T_WC_T2S_SERIE JOIN T_WC_T2S_SERIE_GENRE ON T_WC_T2S_SERIE.ID_SERIE = T_WC_T2S_SERIE_GENRE.ID_SERIE WHERE T_WC_T2S_SERIE_GENRE.ID_GENRE = 10767 ORDER BY T_WC_T2S_SERIE.IMDB_RATING_WEIGHTED DESC LIMIT 8'
  WHERE ID_T2S_EVALUATION = 2453
    AND (ASSERTION_REFRESH_SQL IS NULL OR TRIM(ASSERTION_REFRESH_SQL) = '');

-- #2451 "Canceled TV series" deliberately gets NO refresh SQL, though it is nominally a
-- moving target. Firefly (1437) is the canonical cancelled series and makes a permanent
-- anchor; a popularity-ranked top-8 of cancellations would drift toward recent ones and
-- could drop it. A certain anchor beats a self-maintaining but uncertain list.


-- =====================================================================================
-- SECTION D. Four cases deliberately left untouched, and why. Nothing below runs.
-- =====================================================================================
--
-- #2458 "What is Wikidata property P161?" and #2462 "What is Wikidata item Q47703?"
--   Both ask for the DEFINITION of a Wikidata entity. The schema stores usages
--   (T_WC_T2S_ITEM, T_WC_WIKIDATA_ITEM_PROPERTY) and never definitions, so no SQL answers
--   them as phrased. Their current assertions will stay red for as long as they exist.
--   Two ways out, both yours to pick:
--     retire them        UPDATE T_WC_T2S_EVALUATION SET IS_EVAL = 0 WHERE ID_T2S_EVALUATION IN (2458, 2462);
--     or rephrase them   "Which movies carry the Wikidata property P161?" is answerable and
--                        keeps the extraction coverage that motivated the pair.
--
-- #2459 "Criterion spine number 100" and #2460 "Criterion spine 42"
--   The generated SQL is CORRECT: it filters T_WC_T2S_MOVIE.ID_CRITERION_SPINE, which exists
--   in the schema. Zero rows means the column is not populated, not that the query is wrong.
--   This is a data gap in the crawler, and leaving these two red is the honest way to keep it
--   visible. Nothing to change here.
--   One thing does look like a slip: #2460 asserts ID_SERIE IN (61820) on a question about a
--   Criterion spine, which is a movie identifier. Probable copy-paste, but I have not touched
--   it because you may have meant something I cannot see. If it is a slip, the shape is:
--     UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (<id>)' WHERE ID_T2S_EVALUATION = 2460;
--
-- #2457 "Movies tagged with Wikidata property P136"
--   P136 is "genre". Nearly every movie carries it, so the question cannot discriminate a
--   working query from a broken one. The text_to_sql prompt documents two properties that
--   would: P840 (narrative location) and P915 (filming location). Replacing the question
--   keeps the Wikidata_property_ID coverage and makes the assertion meaningful.
