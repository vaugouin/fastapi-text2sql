-- Entity-extraction assertions for the evaluation bank.
--
-- NOT YET APPLIED. Generated 2026-08-20: 323 UPDATEs across 24 categories.
-- Every UPDATE is guarded on an empty column, so the file is idempotent. Re-running it
-- changes nothing, and it never overwrites an assertion written by hand.
--
-- WHY THIS FILE EXISTS
-- ASSERTIONS_ENTITY_EXTRACTION was set on exactly one evaluation out of 1424, so the bank
-- scored the end of the pipeline and nothing before it. That is how a real regression went
-- unnoticed for three months. Between 2026-05-02 and 2026-05-09 the extraction prompt grew
-- from 442 to 771 lines as four closed vocabularies landed with their "do not extract as X"
-- boundary sections, and the accumulated weight of those negative rules pushed gpt-4o onto
-- the "if uncertain, do not extract" escape hatch. Bare and misspelled titles stopped being
-- extracted ("Les bas fonds", "the big lebovski"), Character_name drifted to Topic_name, and
-- every query_result assertion kept passing, because the SQL still ran and still returned
-- rows for the questions the bank happened to cover.
--
-- WHAT THESE ASSERTIONS CHECK
-- Layer 1 of the harness already enforces placeholder/key consistency and non-empty values,
-- so these expressions do not repeat it.
--   Tier 1, always present: seteq(entity_keys($), [...]) pins WHICH placeholders come out.
--     This is the net. Zero keys, or the wrong type, fails. Replayed against the pre-fix
--     prompt, 14 of these fail on questions that returned no entity at all.
--   Tier 2, only where both languages yield the same value: matches($.Key, /^value$/i) pins
--     the value too, case-insensitively. It also catches the introductory word being
--     swallowed, Movie_title1 = "Movie Bonjour" instead of "Bonjour".
-- Where the title is translated (The Big Sleep / Le grand sommeil) only tier 1 applies: the
-- column is single and the harness replays it in both languages.
--
-- ESCAPING, READ BEFORE EDITING
-- The column stores HTML-escaped text and the harness unescapes on read
-- (eval/text2sql-eval.py:781). Quotes are &quot; and must stay that way. Plain double quotes
-- would still parse in the DSL, which is worse than failing: the row would diverge silently
-- from every other row in the table.
--
-- PROVENANCE
-- The expected key sets are measured, not guessed: gpt-4o at temperature 0 over these same
-- questions, against the extraction prompt as of 2026-08-20, introductory-word clause
-- included (that clause is applied, not pending). An evaluation is skipped rather than
-- guessed whenever the two languages disagree, whenever the extraction came back empty, or
-- whenever the row already carries an assertion. Those cases are listed at the end of this
-- file and want a human decision.
--
-- REPRODUCIBILITY
-- The 70 evaluations whose assertion carries a value clause on a "Movie X" / "Film X"
-- question were replayed twice more against the deployed prompt: 137 of 140 checks agree
-- across runs. The three that do not are deliberately weakened or withheld here, and they
-- are real findings rather than test defects, worth a look:
--   #279  "Film qui est a la fois drame et western" returns Movie_genre1 = Drama on one run
--         and Drame on the next. The prompt asks for the exact canonical English name, so
--         the French form is a defect. Tier 1 kept, tier 2 dropped.
--   #2146 "Film Indiscretions" keeps the leading Film in the value on some runs. The
--         introductory-word clause is not deterministic on foreign titles. Tier 2 dropped.
--   #855  "Movie with title nouvelle vague" alternates between Movement_name1 and
--         Movie_title1. Even the type is unstable, so nothing is asserted at all. The
--         question says "with title", which argues for Movie_title1.
--
-- Placeholder types covered: Movie_title (98), Person_name (70), Collection_name (31), Movie_genre (22), Award_name (15), Technical_format (14), Serie_genre (14), List_name (10), IMDb_ID (9), Topic_name (9), Movement_name (8), Department_name (7), Character_name (7), Group_name (7), Company_name (6), Location_name (6), Serie_title (6), Wikidata_ID (4), TMDb_ID (4), Release_year (4), IMDb_person_ID (2), Death_name (2), Criterion_spine_ID (1), Death_year (1), Serie_type (1), Network_name (1)


-- ===== category 3: Movies - Technical & Format (15 evaluations) =====
-- Which movies were filmed in 70mm format?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;])'
  WHERE ID_T2S_EVALUATION = 3
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List all movies shot in CinemaScope
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^CinemaScope$/i)'
  WHERE ID_T2S_EVALUATION = 4
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What color movies used Technicolor technology?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^Technicolor$/i)'
  WHERE ID_T2S_EVALUATION = 5
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which films have a 2.39:1 aspect ratio?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;])'
  WHERE ID_T2S_EVALUATION = 6
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movies were shot using Franscope technology?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^Franscope$/i)'
  WHERE ID_T2S_EVALUATION = 7
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies with English primary language and shot in 4/3 aspect ratio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^4\\/3$/i)'
  WHERE ID_T2S_EVALUATION = 50
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Give me 10 color films in which Humphrey Bogart plays a role
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Technical_format1&quot;]) AND matches($.Person_name1, /^Humphrey Bogart$/i)'
  WHERE ID_T2S_EVALUATION = 90
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- CinemaScope films
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;])'
  WHERE ID_T2S_EVALUATION = 105
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- color films with Humphrey Bogart
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Humphrey Bogart$/i)'
  WHERE ID_T2S_EVALUATION = 121
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Show me color movies with Cary Grant
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Technical_format1&quot;]) AND matches($.Person_name1, /^Cary Grant$/i)'
  WHERE ID_T2S_EVALUATION = 480
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List color movies with clark gable
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Technical_format1&quot;]) AND matches($.Person_name1, /^clark gable$/i)'
  WHERE ID_T2S_EVALUATION = 505
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Quels sont films en couleurs avec Humphrey Bogart ?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Technical_format1&quot;]) AND matches($.Person_name1, /^Humphrey Bogart$/i)'
  WHERE ID_T2S_EVALUATION = 884
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies shot with Vistavision, display the more recent first
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^Vistavision$/i)'
  WHERE ID_T2S_EVALUATION = 2225
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movies used the rotoscoping animation technique?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;])'
  WHERE ID_T2S_EVALUATION = 2238
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What color movies used Technicolor technology in the forties?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Technical_format1&quot;]) AND matches($.Technical_format1, /^Technicolor$/i)'
  WHERE ID_T2S_EVALUATION = 2339
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 7: Companies & Networks (7 evaluations) =====
-- Production company Pixar
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^Pixar$/i)'
  WHERE ID_T2S_EVALUATION = 24
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Network Netflix
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Network_name1&quot;]) AND matches($.Network_name1, /^Netflix$/i)'
  WHERE ID_T2S_EVALUATION = 25
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies produced by lucasfilm?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^lucasfilm$/i)'
  WHERE ID_T2S_EVALUATION = 37
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film New Line Cinema
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^New Line Cinema$/i)'
  WHERE ID_T2S_EVALUATION = 120
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What movies were produced by the Pixar production company?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^Pixar$/i)'
  WHERE ID_T2S_EVALUATION = 416
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Company silver pictures
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^silver pictures$/i)'
  WHERE ID_T2S_EVALUATION = 841
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Company a24
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Company_name1&quot;]) AND matches($.Company_name1, /^a24$/i)'
  WHERE ID_T2S_EVALUATION = 1129
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 8: Movies - Geography & Language (11 evaluations) =====
-- Movies happening in Naples
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;]) AND matches($.Location_name1, /^Naples$/i)'
  WHERE ID_T2S_EVALUATION = 291
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Japanese movie named « en boucle »
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^en boucle$/i)'
  WHERE ID_T2S_EVALUATION = 454
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies happening in San Francisco
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;]) AND matches($.Location_name1, /^San Francisco$/i)'
  WHERE ID_T2S_EVALUATION = 2147
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies happening on the Moon
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2149
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies shot in Namibia
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2150
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- In which city the action of movie Pulp Fiction takes place?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Pulp Fiction$/i)'
  WHERE ID_T2S_EVALUATION = 2151
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the narrative locations of the movie Pulp Fiction?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Pulp Fiction$/i)'
  WHERE ID_T2S_EVALUATION = 2155
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Where was shot the movie 2001 A Space Odyssey?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 2156
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List popular movies happening in Paris
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;]) AND matches($.Location_name1, /^Paris$/i)'
  WHERE ID_T2S_EVALUATION = 2428
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies shot in Tokyo
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Location_name1&quot;]) AND matches($.Location_name1, /^Tokyo$/i)'
  WHERE ID_T2S_EVALUATION = 2429
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the narrative locations of the movie 2001 A space odyssey?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 2434
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 9: Movies - Genres, Topics, Universes (12 evaluations) =====
-- Adventure movie with Harrison Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Person_name1&quot;]) AND matches($.Movie_genre1, /^Adventure$/i) AND matches($.Person_name1, /^Harrison Ford$/i)'
  WHERE ID_T2S_EVALUATION = 26
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Show me all World War II movies directed by John Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Topic_name1&quot;]) AND matches($.Person_name1, /^John Ford$/i)'
  WHERE ID_T2S_EVALUATION = 30
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Star Wars movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i)'
  WHERE ID_T2S_EVALUATION = 33
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Vietnam war movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 34
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies about time travel
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 71
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie about the vietnam war starring Marlon Brando
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Topic_name1&quot;]) AND matches($.Person_name1, /^Marlon Brando$/i)'
  WHERE ID_T2S_EVALUATION = 118
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie which is both a drama and a western
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Movie_genre2&quot;])'
  WHERE ID_T2S_EVALUATION = 279
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies about the Vietnam war
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 501
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Star Wars universe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i)'
  WHERE ID_T2S_EVALUATION = 511
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies about spaghetti western
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 747
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List topics of the movie Apocalypse Now
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Apocalypse Now$/i)'
  WHERE ID_T2S_EVALUATION = 2152
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List popular movies about double identity
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2430
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 11: Movies - Awards (14 evaluations) =====
-- Movies who got an Academy award
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 39
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies who won the Palme d'Or
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;]) AND matches($.Award_name1, /^Palme d''Or$/i)'
  WHERE ID_T2S_EVALUATION = 65
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies who won a Cesar du meilleur film award
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 75
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which Martin Scorcese movie won the Palme D’or ?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;,&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2278
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List bafta awards for movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2289
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies awarded the bafta
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;]) AND matches($.Award_name1, /^bafta$/i)'
  WHERE ID_T2S_EVALUATION = 2289
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List drama movies that were awarded the Golden Globe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;,&quot;Movie_genre1&quot;]) AND matches($.Award_name1, /^Golden Globe$/i) AND matches($.Movie_genre1, /^Drama$/i)'
  WHERE ID_T2S_EVALUATION = 2291
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies rewarded at the 84th Academy Awards
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2305
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movies did win at the 1st academy awards?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2311
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List the films that have received the Louis Delluc Prize
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2336
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movies received the Jean Vigo award?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2337
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movies did earn a “raspberry award for worst movie”?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2343
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List recent movies who won the Palme d'or
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;]) AND matches($.Award_name1, /^Palme d''or$/i)'
  WHERE ID_T2S_EVALUATION = 2424
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List recent movies who won an academy award for best picture
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2425
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 15: Movies - Character (12 evaluations) =====
-- What character did Harrison Ford play in Star Wars?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i) AND matches($.Person_name1, /^Harrison Ford$/i)'
  WHERE ID_T2S_EVALUATION = 11
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List all movies in the Batman universe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 16
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List all movies with the private investigator Philip Marlowe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;]) AND matches($.Topic_name1, /^Philip Marlowe$/i)'
  WHERE ID_T2S_EVALUATION = 17
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies having a Philip Marlowe character
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;]) AND matches($.Topic_name1, /^Philip Marlowe$/i)'
  WHERE ID_T2S_EVALUATION = 32
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Films with a character named Antoine Doinel.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Antoine Doinel$/i)'
  WHERE ID_T2S_EVALUATION = 109
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Character name for Harrison Ford in the Star Wars movie
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i) AND matches($.Person_name1, /^Harrison Ford$/i)'
  WHERE ID_T2S_EVALUATION = 222
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What is the name of Carrie Fisher's character in the movie Star Wars?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i) AND matches($.Person_name1, /^Carrie Fisher$/i)'
  WHERE ID_T2S_EVALUATION = 262
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List all movies with the R2-D2 character
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^R2\\-D2$/i)'
  WHERE ID_T2S_EVALUATION = 2148
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies with the Charlotte Corday character
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Charlotte Corday$/i)'
  WHERE ID_T2S_EVALUATION = 2293
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies where there is a character named Philippe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Philippe$/i)'
  WHERE ID_T2S_EVALUATION = 2294
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies with the Marco Polo character
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Marco Polo$/i)'
  WHERE ID_T2S_EVALUATION = 2348
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which actors have played the character of Tom Ripley in films?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Tom Ripley$/i)'
  WHERE ID_T2S_EVALUATION = 2443
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 19: Movies - ID (11 evaluations) =====
-- Movie with IMDb id tt0033467
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0033467$/i)'
  WHERE ID_T2S_EVALUATION = 79
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with Wikidata id Q24815
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q24815$/i)'
  WHERE ID_T2S_EVALUATION = 80
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with imdb id tt0297289
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0297289$/i)'
  WHERE ID_T2S_EVALUATION = 1034
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with IMDb ID tt5421006
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt5421006$/i)'
  WHERE ID_T2S_EVALUATION = 1085
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie tt5421006
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt5421006$/i)'
  WHERE ID_T2S_EVALUATION = 1092
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie tt32159989
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt32159989$/i)'
  WHERE ID_T2S_EVALUATION = 1102
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with Spine n°1
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Criterion_spine_ID1&quot;]) AND matches($.Criterion_spine_ID1, /^1$/i)'
  WHERE ID_T2S_EVALUATION = 2173
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie tt0057427
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0057427$/i)'
  WHERE ID_T2S_EVALUATION = 2188
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with The Movie Database ID 490
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^490$/i)'
  WHERE ID_T2S_EVALUATION = 2189
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie with TMDb ID 68
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^68$/i)'
  WHERE ID_T2S_EVALUATION = 2190
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- tt0033467
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0033467$/i)'
  WHERE ID_T2S_EVALUATION = 2201
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 20: Movies - Non English (74 evaluations) =====
-- Film The Condition
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 84
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- The Big Sleep
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 116
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie fabuleux destin d amélie poulain
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 300
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Roma città aperta
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Roma città aperta$/i)'
  WHERE ID_T2S_EVALUATION = 301
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Désert rouge
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Désert rouge$/i)'
  WHERE ID_T2S_EVALUATION = 321
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie peppermint frappe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 350
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Le Schpountz
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Le Schpountz$/i)'
  WHERE ID_T2S_EVALUATION = 473
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Bell' Antonio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 475
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Le crabe tambour
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Le crabe tambour$/i)'
  WHERE ID_T2S_EVALUATION = 476
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Bell' Antonio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 477
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie The big sleep
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 499
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Le crabe tambour
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Le crabe tambour$/i)'
  WHERE ID_T2S_EVALUATION = 503
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la disparition de mengele
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la disparition de mengele$/i)'
  WHERE ID_T2S_EVALUATION = 522
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Il Bell' Antonio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 533
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie il bell antonio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 534
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie les amants
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^les amants$/i)'
  WHERE ID_T2S_EVALUATION = 537
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le bel antonio
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le bel antonio$/i)'
  WHERE ID_T2S_EVALUATION = 543
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie les saisons du plaisir
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^les saisons du plaisir$/i)'
  WHERE ID_T2S_EVALUATION = 550
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'insoutenable légèreté de l'être
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''insoutenable légèreté de l''être$/i)'
  WHERE ID_T2S_EVALUATION = 577
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Agence tout risque
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Agence tout risque$/i)'
  WHERE ID_T2S_EVALUATION = 595
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie classe tout risque
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 597
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le fantôme de la liberté
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le fantôme de la liberté$/i)'
  WHERE ID_T2S_EVALUATION = 600
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'empire
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''empire$/i)'
  WHERE ID_T2S_EVALUATION = 606
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le bonheur
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le bonheur$/i)'
  WHERE ID_T2S_EVALUATION = 613
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'amour l'après-midi
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''amour l''après\\-midi$/i)'
  WHERE ID_T2S_EVALUATION = 628
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie L'entente cordiale
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^L''entente cordiale$/i)'
  WHERE ID_T2S_EVALUATION = 632
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Céline et Julie vont en bateau
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Céline et Julie vont en bateau$/i)'
  WHERE ID_T2S_EVALUATION = 649
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Le rayon vert
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Le rayon vert$/i)'
  WHERE ID_T2S_EVALUATION = 653
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Pauline à la plage
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Pauline à la plage$/i)'
  WHERE ID_T2S_EVALUATION = 697
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la belle noiseuse
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la belle noiseuse$/i)'
  WHERE ID_T2S_EVALUATION = 698
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la jetée
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la jetée$/i)'
  WHERE ID_T2S_EVALUATION = 717
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'échiquier du vent
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''échiquier du vent$/i)'
  WHERE ID_T2S_EVALUATION = 736
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie 絞死刑
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^絞死刑$/i)'
  WHERE ID_T2S_EVALUATION = 740
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie les rendez-vous d'anna
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^les rendez\\-vous d''anna$/i)'
  WHERE ID_T2S_EVALUATION = 743
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le viol
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le viol$/i)'
  WHERE ID_T2S_EVALUATION = 788
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le gendarme de saint tropez
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 826
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Poor things
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 924
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'attachement
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''attachement$/i)'
  WHERE ID_T2S_EVALUATION = 926
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Association criminelle
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Association criminelle$/i)'
  WHERE ID_T2S_EVALUATION = 928
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la voie du serpent
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la voie du serpent$/i)'
  WHERE ID_T2S_EVALUATION = 932
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie peur sur la ville
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^peur sur la ville$/i)'
  WHERE ID_T2S_EVALUATION = 940
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie named valeur sentimentale
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^valeur sentimentale$/i)'
  WHERE ID_T2S_EVALUATION = 954
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le feu follet
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le feu follet$/i)'
  WHERE ID_T2S_EVALUATION = 955
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la voie lactée
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la voie lactée$/i)'
  WHERE ID_T2S_EVALUATION = 963
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie pars vite et reviens tard
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 964
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'odyssée
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''odyssée$/i)'
  WHERE ID_T2S_EVALUATION = 983
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie The Seventh Continent
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 990
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie poil de carotte
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^poil de carotte$/i)'
  WHERE ID_T2S_EVALUATION = 1011
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la cache
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la cache$/i)'
  WHERE ID_T2S_EVALUATION = 1015
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- movie hausfrauen report
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^hausfrauen report$/i)'
  WHERE ID_T2S_EVALUATION = 1021
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie It Was Just an Accident
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 1023
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie la machine à découdre
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^la machine à découdre$/i)'
  WHERE ID_T2S_EVALUATION = 1029
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'ibis rouge
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''ibis rouge$/i)'
  WHERE ID_T2S_EVALUATION = 1030
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie 新・男はつらいよ
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^新・男はつらいよ$/i)'
  WHERE ID_T2S_EVALUATION = 1044
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie The Housemaid
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 1054
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie le gitan
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^le gitan$/i)'
  WHERE ID_T2S_EVALUATION = 1076
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Vincent Francois Paul et les autres
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 1090
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film nous irons tous au paradis
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^nous irons tous au paradis$/i)'
  WHERE ID_T2S_EVALUATION = 1114
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie un elephant ca trompe énormément
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 1117
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Indiscretions
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 2146
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Der siebente Kontinent
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Der siebente Kontinent$/i)'
  WHERE ID_T2S_EVALUATION = 2174
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Todo sobre mi madre
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Todo sobre mi madre$/i)'
  WHERE ID_T2S_EVALUATION = 2175
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Броненосец Потёмкин
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Броненосец Потёмкин$/i)'
  WHERE ID_T2S_EVALUATION = 2176
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie 花樣年華
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^花樣年華$/i)'
  WHERE ID_T2S_EVALUATION = 2177
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie 친절한 금자씨
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^친절한 금자씨$/i)'
  WHERE ID_T2S_EVALUATION = 2178
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie کلوزآپ ، نمای نزدیک
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^کلوزآپ ، نمای نزدیک$/i)'
  WHERE ID_T2S_EVALUATION = 2179
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Kauas pilvet karkaavat
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Kauas pilvet karkaavat$/i)'
  WHERE ID_T2S_EVALUATION = 2180
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Spelfilm Fanny och Alexander
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Fanny och Alexander$/i)'
  WHERE ID_T2S_EVALUATION = 2181
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film অপুর সংসার
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^অপুর সংসার$/i)'
  WHERE ID_T2S_EVALUATION = 2182
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Película Los olvidados
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Los olvidados$/i)'
  WHERE ID_T2S_EVALUATION = 2183
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film Spoorloos
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Spoorloos$/i)'
  WHERE ID_T2S_EVALUATION = 2184
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film Vredens dag
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Vredens dag$/i)'
  WHERE ID_T2S_EVALUATION = 2185
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film Hoří, má panenko
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Hoří, má panenko$/i)'
  WHERE ID_T2S_EVALUATION = 2186
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Film Affeksjonsverdi
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Affeksjonsverdi$/i)'
  WHERE ID_T2S_EVALUATION = 2187
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 25: Persons - ID (5 evaluations) =====
-- Person with IMDb id nm0000003
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0000003$/i)'
  WHERE ID_T2S_EVALUATION = 81
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Person with wikidata id Q1668173
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q1668173$/i)'
  WHERE ID_T2S_EVALUATION = 1066
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- nm0806041
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_person_ID1&quot;]) AND matches($.IMDb_person_ID1, /^nm0806041$/i)'
  WHERE ID_T2S_EVALUATION = 2202
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Person with wikidata id Q30875
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q30875$/i)'
  WHERE ID_T2S_EVALUATION = 2206
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Person with TMDb id 1
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^1$/i)'
  WHERE ID_T2S_EVALUATION = 2207
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 26: TV Series - ID (4 evaluations) =====
-- tt0944947
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0944947$/i)'
  WHERE ID_T2S_EVALUATION = 2203
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- TV serie whose Wikidata id is Q1079
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Wikidata_ID1&quot;]) AND matches($.Wikidata_ID1, /^Q1079$/i)'
  WHERE ID_T2S_EVALUATION = 2210
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Serie with TMDb ID 2473
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;TMDb_ID1&quot;]) AND matches($.TMDb_ID1, /^2473$/i)'
  WHERE ID_T2S_EVALUATION = 2212
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- tt0903747
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;IMDb_ID1&quot;]) AND matches($.IMDb_ID1, /^tt0903747$/i)'
  WHERE ID_T2S_EVALUATION = 2404
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 27: Persons - Cast & Crew (16 evaluations) =====
-- Actress Sharon tate
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Sharon tate$/i)'
  WHERE ID_T2S_EVALUATION = 36
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Composer Frederic Chopin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 67
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List of Japanese directors
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 101
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Actor Vincent Perez
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Vincent Perez$/i)'
  WHERE ID_T2S_EVALUATION = 672
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Actor Steve McQueen
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Steve McQueen$/i)'
  WHERE ID_T2S_EVALUATION = 673
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie actor Steve McQueen
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Steve McQueen$/i)'
  WHERE ID_T2S_EVALUATION = 675
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List French cinematographers
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 703
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Author Mary Shelley
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Mary Shelley$/i)'
  WHERE ID_T2S_EVALUATION = 773
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Writer oscar wilde
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^oscar wilde$/i)'
  WHERE ID_T2S_EVALUATION = 780
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Actress sigourney weaver
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^sigourney weaver$/i)'
  WHERE ID_T2S_EVALUATION = 794
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Writer pietro germi
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^pietro germi$/i)'
  WHERE ID_T2S_EVALUATION = 967
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Comédienne qui joue dans les films suivants : - Le mépris - Et dieu créa la femme
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Movie_title2&quot;]) AND matches($.Movie_title1, /^Le mépris$/i) AND matches($.Movie_title2, /^Et dieu créa la femme$/i)'
  WHERE ID_T2S_EVALUATION = 1112
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Composer Frederic Chopin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 1121
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Quelle actrice a joué à la fois dans les films suivants : - Le mépris - Et dieu... créa la femme
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Movie_title2&quot;]) AND matches($.Movie_title1, /^Le mépris$/i) AND matches($.Movie_title2, /^Et dieu\\.\\.\\. créa la femme$/i)'
  WHERE ID_T2S_EVALUATION = 2139
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which actor is playing in both movies: - The Big Lebowski - Tron
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Movie_title2&quot;]) AND matches($.Movie_title1, /^The Big Lebowski$/i) AND matches($.Movie_title2, /^Tron$/i)'
  WHERE ID_T2S_EVALUATION = 2143
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which actors are playing in both movies: - La grande vadrouille - Le corniaud
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Movie_title2&quot;]) AND matches($.Movie_title1, /^La grande vadrouille$/i) AND matches($.Movie_title2, /^Le corniaud$/i)'
  WHERE ID_T2S_EVALUATION = 2144
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 29: Movies - Movie title (8 evaluations) =====
-- The big Lebowski
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^The big Lebowski$/i)'
  WHERE ID_T2S_EVALUATION = 114
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- The Big Sleep
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 117
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie l'homme qui rétrécit
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^l''homme qui rétrécit$/i)'
  WHERE ID_T2S_EVALUATION = 519
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie Bonjour
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Bonjour$/i)'
  WHERE ID_T2S_EVALUATION = 536
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- 2001: A SPACE ODYSSEY
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 2213
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Everything You Always Wanted to Know About Sex *But Were Afraid to Ask (1972)
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Release_year1&quot;]) AND matches($.Release_year1, /^1972$/i)'
  WHERE ID_T2S_EVALUATION = 2217
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Manhattan (1979)
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Release_year1&quot;]) AND matches($.Movie_title1, /^Manhattan$/i) AND matches($.Release_year1, /^1979$/i)'
  WHERE ID_T2S_EVALUATION = 2222
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Diary of a chambermaid (1946)
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;,&quot;Release_year1&quot;]) AND matches($.Release_year1, /^1946$/i)'
  WHERE ID_T2S_EVALUATION = 2296
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 30: Persons - Person name (34 evaluations) =====
-- John Wayne
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^John Wayne$/i)'
  WHERE ID_T2S_EVALUATION = 273
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- J. K. Rowling
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^J\\. K\\. Rowling$/i)'
  WHERE ID_T2S_EVALUATION = 274
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Andre Previn
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Andre Previn$/i)'
  WHERE ID_T2S_EVALUATION = 829
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Jean Pierre mocky
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Jean Pierre mocky$/i)'
  WHERE ID_T2S_EVALUATION = 992
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Fabrice Luchini
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Fabrice Luchini$/i)'
  WHERE ID_T2S_EVALUATION = 993
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Gerard Rinaldi
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Gerard Rinaldi$/i)'
  WHERE ID_T2S_EVALUATION = 999
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Louis lumière
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Louis lumière$/i)'
  WHERE ID_T2S_EVALUATION = 1017
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Sydney Sweeney
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Sydney Sweeney$/i)'
  WHERE ID_T2S_EVALUATION = 1024
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Steve coogan
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Steve coogan$/i)'
  WHERE ID_T2S_EVALUATION = 1041
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Pedro pascal
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Pedro pascal$/i)'
  WHERE ID_T2S_EVALUATION = 1050
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Michel Blanc
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Michel Blanc$/i)'
  WHERE ID_T2S_EVALUATION = 1052
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Ethan coen
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Ethan coen$/i)'
  WHERE ID_T2S_EVALUATION = 1053
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- john frankheimer
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^john frankheimer$/i)'
  WHERE ID_T2S_EVALUATION = 1060
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Richard Pryor
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Richard Pryor$/i)'
  WHERE ID_T2S_EVALUATION = 1062
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- John lennon
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^John lennon$/i)'
  WHERE ID_T2S_EVALUATION = 1069
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Catherine allegret
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 1074
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Diane Keaton
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Diane Keaton$/i)'
  WHERE ID_T2S_EVALUATION = 1080
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Jean-loup dabadie
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Jean\\-loup dabadie$/i)'
  WHERE ID_T2S_EVALUATION = 1099
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Brigitte bardot
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Brigitte bardot$/i)'
  WHERE ID_T2S_EVALUATION = 1103
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Michel Legrand
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Michel Legrand$/i)'
  WHERE ID_T2S_EVALUATION = 1104
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- David Benioff
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^David Benioff$/i)'
  WHERE ID_T2S_EVALUATION = 1106
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Jean Dujardin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Jean Dujardin$/i)'
  WHERE ID_T2S_EVALUATION = 1107
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- david gauque
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^david gauque$/i)'
  WHERE ID_T2S_EVALUATION = 1108
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Anny duperey
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Anny duperey$/i)'
  WHERE ID_T2S_EVALUATION = 1109
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Charlie Chaplin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Charlie Chaplin$/i)'
  WHERE ID_T2S_EVALUATION = 1120
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Frederic Chopin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 1122
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Golshifteh
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Golshifteh$/i)'
  WHERE ID_T2S_EVALUATION = 1130
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- André de Toth
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^André de Toth$/i)'
  WHERE ID_T2S_EVALUATION = 2153
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Arnaud Depleschin
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2227
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Bruce Lee
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Bruce Lee$/i)'
  WHERE ID_T2S_EVALUATION = 2271
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Sid Vicious
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Sid Vicious$/i)'
  WHERE ID_T2S_EVALUATION = 2272
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Hillary Swank
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Hillary Swank$/i)'
  WHERE ID_T2S_EVALUATION = 2328
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Katherine Hepburn
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Katherine Hepburn$/i)'
  WHERE ID_T2S_EVALUATION = 2329
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- RICARDO FREDA
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^RICARDO FREDA$/i)'
  WHERE ID_T2S_EVALUATION = 2330
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 31: TV Series - Serie title (6 evaluations) =====
-- Game of Thrones
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Game of Thrones$/i)'
  WHERE ID_T2S_EVALUATION = 2157
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Severance
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Severance$/i)'
  WHERE ID_T2S_EVALUATION = 2209
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Black Mirror
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Black Mirror$/i)'
  WHERE ID_T2S_EVALUATION = 2211
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- The TV series Breaking Bad
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Breaking Bad$/i)'
  WHERE ID_T2S_EVALUATION = 2401
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- The TV series Game of Thrones
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Game of Thrones$/i)'
  WHERE ID_T2S_EVALUATION = 2402
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- The TV series Friends
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_title1&quot;]) AND matches($.Serie_title1, /^Friends$/i)'
  WHERE ID_T2S_EVALUATION = 2403
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 32: Persons - Character (1 evaluations) =====
-- List all actors that played the role of Sherlock Holmes in series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Sherlock Holmes$/i)'
  WHERE ID_T2S_EVALUATION = 2218
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 34: Persons - Group (7 evaluations) =====
-- Who are the members of The Beatles?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2226
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List the members of The Monty Python
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2232
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which actors are members of the Royal Shakespeare Company?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;]) AND matches($.Group_name1, /^Royal Shakespeare Company$/i)'
  WHERE ID_T2S_EVALUATION = 2233
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Who were the Marx Brothers?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;]) AND matches($.Group_name1, /^Marx Brothers$/i)'
  WHERE ID_T2S_EVALUATION = 2234
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List persons member of Les Cahiers du Cinéma
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2295
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List members of the Dziga Vertov Group
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2298
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List members of the Royal Shakespeare Company
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Group_name1&quot;]) AND matches($.Group_name1, /^Royal Shakespeare Company$/i)'
  WHERE ID_T2S_EVALUATION = 2299
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 35: Persons - Birth and Death (5 evaluations) =====
-- List actors who died in a car accident
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Death_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2236
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Which movie directors died in 2025?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Death_year1&quot;,&quot;Department_name1&quot;]) AND matches($.Death_year1, /^2025$/i)'
  WHERE ID_T2S_EVALUATION = 2250
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movie directors that were born in the nineteenth century
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2251
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List directors that were born before the 20th century
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2252
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List person who died in a car accident
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Death_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2436
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 38: TV Series - Genres (14 evaluations) =====
-- List English TV Series of genre "Action & Adventure"
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;])'
  WHERE ID_T2S_EVALUATION = 2281
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List trending reality series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Reality$/i)'
  WHERE ID_T2S_EVALUATION = 2355
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending crime series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Crime$/i)'
  WHERE ID_T2S_EVALUATION = 2356
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending crime series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Crime$/i)'
  WHERE ID_T2S_EVALUATION = 2368
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Reality shows everyone's watching
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Reality$/i)'
  WHERE ID_T2S_EVALUATION = 2369
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending sci-fi and fantasy shows
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Sci\\-Fi \\&amp; Fantasy$/i)'
  WHERE ID_T2S_EVALUATION = 2370
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Popular comedy series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Comedy$/i)'
  WHERE ID_T2S_EVALUATION = 2371
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending drama series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Drama$/i)'
  WHERE ID_T2S_EVALUATION = 2372
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Best crime TV series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Crime$/i)'
  WHERE ID_T2S_EVALUATION = 2375
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Best comedy TV series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Comedy$/i)'
  WHERE ID_T2S_EVALUATION = 2376
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Best drama TV series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Drama$/i)'
  WHERE ID_T2S_EVALUATION = 2377
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Best documentary TV series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_type1&quot;]) AND matches($.Serie_type1, /^Documentary$/i)'
  WHERE ID_T2S_EVALUATION = 2378
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Best animated TV series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Animation$/i)'
  WHERE ID_T2S_EVALUATION = 2379
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Popular crime series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Crime$/i)'
  WHERE ID_T2S_EVALUATION = 2410
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 45: Recognition & Famous Lists (11 evaluations) =====
-- List movies in the Sight and Sound list
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 40
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Films in top 250 IMDb
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;]) AND matches($.List_name1, /^top 250 IMDb$/i)'
  WHERE ID_T2S_EVALUATION = 59
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Tous les films Sight and Sound 2022
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;]) AND matches($.List_name1, /^Sight and Sound 2022$/i)'
  WHERE ID_T2S_EVALUATION = 380
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Liste the directors with the most movies in the Sight and Sound list
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;,&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 413
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Who are the directors with the most movies in the Criterion Collection and give the count of mov
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Department_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 446
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies in the Sight & Sound list?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 989
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies in the Sight & Sound list?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 1095
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the National Film Registry
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;]) AND matches($.List_name1, /^National Film Registry$/i)'
  WHERE ID_T2S_EVALUATION = 2274
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Vatican's list of films
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2275
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- In which important lists is the movie Apocalypse Now?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;]) AND matches($.Movie_title1, /^Apocalypse Now$/i)'
  WHERE ID_T2S_EVALUATION = 2308
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List the most recent movies included in the National Film Registry
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2432
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 46: TV Series - Awards (3 evaluations) =====
-- List series that received an Emmy Award
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Award_name1&quot;]) AND matches($.Award_name1, /^Emmy Award$/i)'
  WHERE ID_T2S_EVALUATION = 2283
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List series in the IMDb Top 250 TV show
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;List_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2290
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Award-winning drama series
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Serie_genre1&quot;]) AND matches($.Serie_genre1, /^Drama$/i)'
  WHERE ID_T2S_EVALUATION = 2400
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 47: Movies - Collections (26 evaluations) =====
-- List movies in the flamenco trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 19
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Star Wars movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i)'
  WHERE ID_T2S_EVALUATION = 33
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Die Hard movie collection
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 46
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- John Ford's movies in the cavalry trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^John Ford$/i)'
  WHERE ID_T2S_EVALUATION = 60
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the musashi samurai trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 72
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List the movies from Yasujirō Ozu's Noriko trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Yasujirō Ozu$/i)'
  WHERE ID_T2S_EVALUATION = 96
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies in the Noriko trilogy?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 129
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the Noriko trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 290
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the Time Trilogy by Sergio Leone
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Sergio Leone$/i)'
  WHERE ID_T2S_EVALUATION = 292
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the Cavalry trilogy by John Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^John Ford$/i)'
  WHERE ID_T2S_EVALUATION = 293
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Cavalry Trilogy de John Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^John Ford$/i)'
  WHERE ID_T2S_EVALUATION = 339
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the cavalry trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 366
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies from the Dracula collection
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 470
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Star Wars universe
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^Star Wars$/i)'
  WHERE ID_T2S_EVALUATION = 511
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the back to the future collection
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 718
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies from the samouraï trilogy Musashi
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 748
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the man with no name trilogy
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 760
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie collection le gendarme de saint tropez
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 825
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Tora San collection
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 1064
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List all the Harry Potter movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^Harry Potter$/i)'
  WHERE ID_T2S_EVALUATION = 2133
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the movies of the Samurai trilogy starring Toshiro Mifune?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Toshiro Mifune$/i)'
  WHERE ID_T2S_EVALUATION = 2140
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movies in the Samurai trilogy with Toshiro Mifune
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Toshiro Mifune$/i)'
  WHERE ID_T2S_EVALUATION = 2141
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- In which trilogy is the movie « the good the bad the ugly » a part?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_title1&quot;])'
  WHERE ID_T2S_EVALUATION = 2200
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List James Bond movies ordered by release date
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^James Bond$/i)'
  WHERE ID_T2S_EVALUATION = 2277
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Mad Max collection
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2340
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the Star Trek Franchise
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2346
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 48: Movements and Styles (8 evaluations) =====
-- French New Wave films directed by François Truffaut
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;,&quot;Person_name1&quot;]) AND matches($.Person_name1, /^François Truffaut$/i)'
  WHERE ID_T2S_EVALUATION = 31
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List the Dogma 95 movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 43
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Czech New Wave movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 68
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- New Wave films
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 119
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the films of the French New Wave?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 495
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies in the French new wave
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 677
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List New Hollywood movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2300
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Is there a Pre-Code Hollywood movement?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movement_name1&quot;])'
  WHERE ID_T2S_EVALUATION = 2335
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 52: Movies - Questions with no answer (3 evaluations) =====
-- List movies with Sharon Stone released before 1970
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Sharon Stone$/i)'
  WHERE ID_T2S_EVALUATION = 2332
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List movies starring Humphrey Bogart and Lauren Bacall released in 1920
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Person_name2&quot;,&quot;Release_year1&quot;]) AND matches($.Person_name1, /^Humphrey Bogart$/i) AND matches($.Person_name2, /^Lauren Bacall$/i) AND matches($.Release_year1, /^1920$/i)'
  WHERE ID_T2S_EVALUATION = 2333
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- movies directed by Christopher Nolan released in 1850
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;]) AND matches($.Person_name1, /^Christopher Nolan$/i)'
  WHERE ID_T2S_EVALUATION = 2350
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');

-- ===== category 55: Movies - Genre (16 evaluations) =====
-- Adventure movie with Harrison Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Person_name1&quot;]) AND matches($.Movie_genre1, /^Adventure$/i) AND matches($.Person_name1, /^Harrison Ford$/i)'
  WHERE ID_T2S_EVALUATION = 26
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Adventure movies with Harrison Ford
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Person_name1&quot;]) AND matches($.Movie_genre1, /^Adventure$/i) AND matches($.Person_name1, /^Harrison Ford$/i)'
  WHERE ID_T2S_EVALUATION = 92
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Movie which is both a drama and a western
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Movie_genre2&quot;])'
  WHERE ID_T2S_EVALUATION = 279
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List horror movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Horror$/i)'
  WHERE ID_T2S_EVALUATION = 2351
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- What are the best romance movies?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Romance$/i)'
  WHERE ID_T2S_EVALUATION = 2352
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- which movies are both comedy and drama?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;,&quot;Movie_genre2&quot;]) AND matches($.Movie_genre1, /^Comedy$/i) AND matches($.Movie_genre2, /^Drama$/i)'
  WHERE ID_T2S_EVALUATION = 2353
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- List trending science fiction movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Science Fiction$/i)'
  WHERE ID_T2S_EVALUATION = 2354
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending sci-fi movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Science Fiction$/i)'
  WHERE ID_T2S_EVALUATION = 2360
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Feel-good comedies everyone's watching
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Comedy$/i)'
  WHERE ID_T2S_EVALUATION = 2361
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Thrillers to watch tonight
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Thriller$/i)'
  WHERE ID_T2S_EVALUATION = 2362
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Scary movies everyone's watching
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Horror$/i)'
  WHERE ID_T2S_EVALUATION = 2363
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Animated movies the whole family loves
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Animation$/i)'
  WHERE ID_T2S_EVALUATION = 2364
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Popular action movies right now
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Action$/i)'
  WHERE ID_T2S_EVALUATION = 2365
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Trending romantic movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Romance$/i)'
  WHERE ID_T2S_EVALUATION = 2366
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Popular sci-fi movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Science Fiction$/i)'
  WHERE ID_T2S_EVALUATION = 2407
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');
-- Popular animated movies
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Movie_genre1&quot;]) AND matches($.Movie_genre1, /^Animation$/i)'
  WHERE ID_T2S_EVALUATION = 2408
    AND (ASSERTIONS_ENTITY_EXTRACTION IS NULL OR ASSERTIONS_ENTITY_EXTRACTION = '');


-- ===== LEFT FOR A HUMAN DECISION, deliberately not generated =====
--
-- EN and FR disagree on the key set, decide by hand: 23
--   cat   3  #14    'Movies shot in color with Humphrey Bogart' -> ['Person_name1', 'Technical_format1'] | 'Films tournés en
--   cat   3  #506   'List color movies with katherine hepburn' -> ['Person_name1', 'Technical_format1'] | 'Répertorier les f
--   cat   3  #513   'Movies both in colors and black and white' -> ['Technical_format1', 'Technical_format2'] | 'Des films à
--   cat   9  #277   'Movie Drama western' -> ['Movie_genre1', 'Movie_genre2'] | 'Film dramatique western' -> []
--   cat  11  #883   "List movies that received The palme d'or in Cannes" -> ['Award_name1', 'Location_name1'] | "Donne-moi l
--   cat  15  #41    'List Dracula movies' -> ['Topic_name1'] | 'Lister les films de Dracula' -> ['Character_name1']
--   cat  20  #609   'Movie le bonheur' -> ['Movie_title1'] | 'Le film a-t-il réussi à transmettre le thème du bonheur de man
--   cat  27  #69    'Cinematographer Darius Khondji' -> ['Department_name1', 'Person_name1'] | 'Directeur de la photographie
--   cat  27  #364   'Who did the cinematography on the movie Le mépris?' -> ['Department_name1', 'Movie_title1'] | 'Qui a ré
--   cat  27  #674   'Movie director Steve McQueen' -> ['Person_name1'] | 'Réalisateur de cinéma Steve McQueen' -> ['Departme
--   cat  34  #2448  'Who are the Hollywood ten?' -> [] | 'Qui sont les Dix de Hollywood ?' -> ['Group_name1']
--   cat  35  #2237  'Who are the directors or writers who commited suicide?' -> ['Death_name1', 'Department_name1', 'Departm
--   cat  35  #2338  'List actors born in 67' -> [] | 'Liste des acteurs nés en 67' -> ['Birth_year1']
--   cat  35  #2444  'List movie directors born in the fifties' -> [] | 'Listez les réalisateurs de films nés dans les années
--   cat  45  #961   'List Criterion Collection movies' -> [] | 'Répertorier les films de la Collection Criterion' -> ['Colle
--   cat  45  #2216  'List Criterion Collection ordered by IMDb rating descending' -> [] | 'Liste de la Collection Criterion 
--   cat  45  #2273  'List movies in the Wikiflix list' -> [] | 'Répertorier les films dans la liste Wikiflix' -> ['List_name
--   cat  45  #2297  "List movies in the Danny Peary's Cult Movies list" -> ['List_name1'] | 'Les films cultes de Danny Peary
--   cat  47  #303   'Films de la John Ford cavalry trilogy' -> ['Collection_name1'] | 'Films de la trilogie de la cavalerie 
--   cat  47  #444   'Flamenco trilogy' -> ['Collection_name1'] | 'Trilogie flamenco' -> []
--   cat  47  #723   "What movies are in the Terry Gilliam's Imagination trilogy?" -> ['Collection_name1'] | "Quels films fon
--   cat  47  #2136  "List movies in park Chan wook's vengeance trilogy" -> ['Collection_name1'] | 'Listez les films de la tr
--   cat  55  #277   'Movie Drama western' -> ['Movie_genre1', 'Movie_genre2'] | 'Film dramatique western' -> []
--
-- already carries an assertion, left untouched: 5
--   cat   7  #2244  Ginza cosmetics
--   cat  15  #2221  Who starred as Rocky Balboa?
--   cat  29  #2235  Tommy (1975)
--   cat  32  #2215  List all actors that played the role of Sherlock Holmes in movies
--   cat  47  #2158  James Bond collection
--
-- extraction is empty, confirm before freezing it: 26
--   cat   3  #270   Which 50 movies have the longest runtime?
--   cat   3  #2159  Movies that are both in colors and black & white
--   cat   7  #204   What companies produced movies with budgets over $200 million?
--   cat   7  #2446  Which production companies produced the most movies with a budget over 200 million dollars?
--   cat   8  #48    List Estonian movies
--   cat   8  #49    List Portuguese speaking movies
--   cat   8  #2292  List all narrative locations
--   cat   8  #2439  Which places have been used as filming locations for the most movies?
--   cat   9  #2442  What are the most popular topics in films?
--   cat  20  #953   Movie valeur sentimentale
--   cat  20  #2135  Movie deux personnes échangeant de la salive
--   cat  27  #2323  List all professions
--   cat  34  #2440  List the most famous groups
--   cat  35  #2324  List all persons who died recently
--   cat  35  #2419  List people whose birthday is today
--   cat  35  #2445  Which actors died in the nineties?
--   cat  45  #44    Criterion Collection
--   cat  45  #493   Movies in the Criterion Collection
--   cat  45  #2438  What are the most famous curated movie lists
--   cat  46  #2399  Award-winning TV series
--   cat  47  #2256  Liste all movie collections with exactly 3 movies
--   cat  47  #2331  List collections with the highest ratings
--   cat  47  #2334  List movie collections
--   cat  47  #2431  List popular movie collections with exactly 3 movies
--   cat  48  #2441  List movements in cinema
--   cat  55  #2357  Documentaries people can't stop talking about
--
-- output not reproducible across runs, decide by hand: 1
--   cat  20  #855   'Movie with title nouvelle vague' -> Movement_name1 in one run, Movie_title1 in the next
