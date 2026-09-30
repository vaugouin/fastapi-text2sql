-- Title + year homonyms of the T2S catalogue (FASTAPI-TEXT2SQL-307, bench B).
--
-- READ-ONLY: SELECT statements only, safe to re-run at any time.
--
--   ~/docker/tools/runsqlvaugouindb.sh ~/harvest-title-year-homonyms.sql
--
-- WHY THIS FILE EXISTS
-- The vision pre-stage composes "Movie <title> released in <year>" from a recognised image.
-- Title plus year is not a unique key: on 2026-09-30 a still from Scorsese's Taxi Driver
-- (tt0075314) also returned the Turkish Taksi Soforu (tt0281258), English title "Taxi Driver",
-- same year. This harvest measures how often that happens and yields the real pairs the live
-- bench (bench C, eval/bench-vision-homonyms.py) will photograph: stills (faces decide) and
-- posters (known credits decide), in both directions of fame.
--
-- Titles are grouped with the table collation (utf8mb4_unicode_ci): case- and accent-
-- insensitive, which is exactly how the generated `MOVIE_TITLE = '...'` compares them.
-- Only MOVIE_TITLE / SERIE_TITLE are grouped. Cross-column collisions (one film's English title
-- equal to another's ORIGINAL_TITLE) also exist but are left out of this first measure.

-- 1. Movies: size of the problem.
--    groups           : title + year pairs held by 2 films or more
--    rows             : films involved
--    groups_famous    : groups where at least one film has 10,000 IMDb votes or more
--                       (the case users will actually photograph)
--    groups_two_known : groups where at least two films have 1,000 votes or more
--                       (the hard case: popularity would not even look like an answer)
WITH g AS (
    SELECT MOVIE_TITLE, RELEASE_YEAR, COUNT(*) AS n,
           MAX(COALESCE(IMDB_VOTES, 0)) AS max_votes,
           SUM(COALESCE(IMDB_VOTES, 0) >= 1000) AS n_known
    FROM T_WC_T2S_MOVIE
    WHERE COALESCE(DELETED, 0) = 0 AND MOVIE_TITLE IS NOT NULL AND RELEASE_YEAR IS NOT NULL
    GROUP BY MOVIE_TITLE, RELEASE_YEAR
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS `groups`, SUM(n) AS `rows`,
       SUM(max_votes >= 10000) AS groups_famous,
       SUM(n_known >= 2) AS groups_two_known
FROM g;

-- 2. Movies: the 150 groups with the most famous member, one line per film.
--    rank_in_group 1 = most voted. directors and top3_cast are what the identity check will
--    compare with the vision model's faces and known_credits.
WITH g AS (
    SELECT MOVIE_TITLE, RELEASE_YEAR, MAX(COALESCE(IMDB_VOTES, 0)) AS max_votes
    FROM T_WC_T2S_MOVIE
    WHERE COALESCE(DELETED, 0) = 0 AND MOVIE_TITLE IS NOT NULL AND RELEASE_YEAR IS NOT NULL
    GROUP BY MOVIE_TITLE, RELEASE_YEAR
    HAVING COUNT(*) > 1
    ORDER BY max_votes DESC
    LIMIT 150
), m AS (
    SELECT g.max_votes, mv.MOVIE_TITLE, mv.RELEASE_YEAR, mv.ID_MOVIE, mv.ID_IMDB,
           COALESCE(mv.IMDB_VOTES, 0) AS IMDB_VOTES, mv.ORIGINAL_TITLE, mv.ORIGINAL_LANGUAGE,
           mv.IS_MOVIE,
           ROW_NUMBER() OVER (PARTITION BY mv.MOVIE_TITLE, mv.RELEASE_YEAR
                              ORDER BY COALESCE(mv.IMDB_VOTES, 0) DESC) AS rank_in_group
    FROM g
    JOIN T_WC_T2S_MOVIE mv ON mv.MOVIE_TITLE = g.MOVIE_TITLE AND mv.RELEASE_YEAR = g.RELEASE_YEAR
    WHERE COALESCE(mv.DELETED, 0) = 0
)
SELECT m.MOVIE_TITLE, m.RELEASE_YEAR, m.rank_in_group, m.ID_MOVIE, m.ID_IMDB, m.IMDB_VOTES,
       m.ORIGINAL_TITLE, m.ORIGINAL_LANGUAGE, m.IS_MOVIE,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY p.PERSON_NAME SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_MOVIE pm JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON
         WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'crew' AND pm.CREW_JOB = 'Director'
           AND COALESCE(pm.DELETED, 0) = 0) AS directors,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY pm.DISPLAY_ORDER SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_MOVIE pm JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON
         WHERE pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'cast' AND pm.DISPLAY_ORDER < 3
           AND COALESCE(pm.DELETED, 0) = 0) AS top3_cast
FROM m
ORDER BY m.max_votes DESC, m.MOVIE_TITLE, m.RELEASE_YEAR, m.rank_in_group;

-- 3. Movies: the hard case, groups where two films or more have 1,000 votes or more.
WITH g AS (
    SELECT MOVIE_TITLE, RELEASE_YEAR
    FROM T_WC_T2S_MOVIE
    WHERE COALESCE(DELETED, 0) = 0 AND MOVIE_TITLE IS NOT NULL AND RELEASE_YEAR IS NOT NULL
    GROUP BY MOVIE_TITLE, RELEASE_YEAR
    HAVING SUM(COALESCE(IMDB_VOTES, 0) >= 1000) >= 2
)
SELECT mv.MOVIE_TITLE, mv.RELEASE_YEAR, mv.ID_MOVIE, mv.ID_IMDB, mv.IMDB_VOTES,
       mv.ORIGINAL_TITLE, mv.ORIGINAL_LANGUAGE
FROM g
JOIN T_WC_T2S_MOVIE mv ON mv.MOVIE_TITLE = g.MOVIE_TITLE AND mv.RELEASE_YEAR = g.RELEASE_YEAR
WHERE COALESCE(mv.DELETED, 0) = 0
ORDER BY mv.MOVIE_TITLE, mv.RELEASE_YEAR, mv.IMDB_VOTES DESC;

-- 4. Series: size of the problem (same columns as section 1).
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR, COUNT(*) AS n,
           MAX(COALESCE(IMDB_VOTES, 0)) AS max_votes,
           SUM(COALESCE(IMDB_VOTES, 0) >= 1000) AS n_known
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS `groups`, SUM(n) AS `rows`,
       SUM(max_votes >= 10000) AS groups_famous,
       SUM(n_known >= 2) AS groups_two_known
FROM g;

-- 5. Series: the 50 groups with the most famous member. Creators stand for directors.
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR, MAX(COALESCE(IMDB_VOTES, 0)) AS max_votes
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING COUNT(*) > 1
    ORDER BY max_votes DESC
    LIMIT 50
)
SELECT s.SERIE_TITLE, s.FIRST_AIR_YEAR, s.ID_SERIE, s.ID_IMDB, COALESCE(s.IMDB_VOTES, 0) AS IMDB_VOTES,
       s.ORIGINAL_TITLE, s.ORIGINAL_LANGUAGE,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY p.PERSON_NAME SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = s.ID_SERIE AND ps.CREDIT_TYPE = 'crew' AND ps.CREW_JOB = 'Creator'
           AND COALESCE(ps.DELETED, 0) = 0) AS creators,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY ps.DISPLAY_ORDER SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = s.ID_SERIE AND ps.CREDIT_TYPE = 'cast' AND ps.DISPLAY_ORDER < 3
           AND COALESCE(ps.DELETED, 0) = 0) AS top3_cast
FROM g
JOIN T_WC_T2S_SERIE s ON s.SERIE_TITLE = g.SERIE_TITLE AND s.FIRST_AIR_YEAR = g.FIRST_AIR_YEAR
WHERE COALESCE(s.DELETED, 0) = 0
ORDER BY g.max_votes DESC, s.SERIE_TITLE, s.FIRST_AIR_YEAR, COALESCE(s.IMDB_VOTES, 0) DESC;
