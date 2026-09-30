-- Title + first-air-year homonyms of the T2S series (FASTAPI-TEXT2SQL-307, bench B for series).
--
-- READ-ONLY: SELECT statements only, safe to re-run at any time.
--
--   ~/docker/tools/runsqlvaugouindb.sh ~/harvest-title-year-homonyms-series.sql
--
-- WHY THIS FILE EXISTS
-- The vision identity check tells namesakes apart with the faces read on the image and the
-- credits the model knows. For a movie the decisive credit is the director. For a series it is
-- the creator (CREW_JOB = 'Creator'), and the first harvest (harvest-title-year-homonyms.sql,
-- sections 4 and 5) showed it is often missing, even on well-known series (Them 2021,
-- Happiness 2021, The Family 2023), and that anime and live-action adaptations share title,
-- year, language AND original title (Horimiya 2021, Komi Can't Communicate 2021). This file
-- measures the problem for series in full, and above all how much each discriminator covers.
--
-- Titles are grouped with the table collation (utf8mb4_unicode_ci), as the generated
-- `SERIE_TITLE = '...'` compares them: `Mars` and `MARS` (2016) fall in the same group.

-- 1. Size of the problem.
--    groups           : title + first-air-year pairs held by 2 series or more
--    rows             : series involved
--    groups_famous    : groups with a series of 10,000 IMDb votes or more
--    groups_two_known : groups with two series of 1,000 votes or more (the hard case)
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

-- 2. Discriminator coverage of the series involved, split by fame.
--    with_creator / with_cast : series holding at least one creator / one cast credit
--    with_neither             : series the identity check can only reach by title or language
--    same_language_groups     : groups where every member shares the original language
--    same_original_title_groups : groups where every member shares the original title too
--                               (the anime / live-action case: only the cast separates them)
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR,
           COUNT(DISTINCT COALESCE(ORIGINAL_LANGUAGE, '')) AS n_lang,
           COUNT(DISTINCT COALESCE(ORIGINAL_TITLE, '')) AS n_otitle
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING COUNT(*) > 1
), s AS (
    SELECT se.ID_SERIE, COALESCE(se.IMDB_VOTES, 0) >= 1000 AS known,
           EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_SERIE ps
                    WHERE ps.ID_SERIE = se.ID_SERIE AND ps.CREDIT_TYPE = 'crew'
                      AND ps.CREW_JOB = 'Creator' AND COALESCE(ps.DELETED, 0) = 0) AS has_creator,
           EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_SERIE ps
                    WHERE ps.ID_SERIE = se.ID_SERIE AND ps.CREDIT_TYPE = 'cast'
                      AND COALESCE(ps.DELETED, 0) = 0) AS has_cast
    FROM g
    JOIN T_WC_T2S_SERIE se ON se.SERIE_TITLE = g.SERIE_TITLE AND se.FIRST_AIR_YEAR = g.FIRST_AIR_YEAR
    WHERE COALESCE(se.DELETED, 0) = 0
)
SELECT IF(known, '1,000 votes or more', 'under 1,000 votes') AS fame,
       COUNT(*) AS series,
       SUM(has_creator) AS with_creator,
       SUM(has_cast) AS with_cast,
       SUM(NOT has_creator AND NOT has_cast) AS with_neither,
       (SELECT SUM(n_lang = 1) FROM g) AS same_language_groups,
       (SELECT SUM(n_lang = 1 AND n_otitle = 1) FROM g) AS same_original_title_groups
FROM s
GROUP BY known
ORDER BY known DESC;

-- 3. When the creator is missing, what else does the crew hold? The 25 most frequent crew
--    jobs among the series of these groups that have NO 'Creator' credit. If 'Director' or
--    'Executive Producer' is well filled there, it can stand in for the creator.
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING COUNT(*) > 1
), nocreator AS (
    SELECT se.ID_SERIE
    FROM g
    JOIN T_WC_T2S_SERIE se ON se.SERIE_TITLE = g.SERIE_TITLE AND se.FIRST_AIR_YEAR = g.FIRST_AIR_YEAR
    WHERE COALESCE(se.DELETED, 0) = 0
      AND NOT EXISTS (SELECT 1 FROM T_WC_T2S_PERSON_SERIE ps
                       WHERE ps.ID_SERIE = se.ID_SERIE AND ps.CREDIT_TYPE = 'crew'
                         AND ps.CREW_JOB = 'Creator' AND COALESCE(ps.DELETED, 0) = 0)
)
SELECT ps.CREW_JOB, COUNT(DISTINCT ps.ID_SERIE) AS series, COUNT(*) AS credits
FROM nocreator n
JOIN T_WC_T2S_PERSON_SERIE ps ON ps.ID_SERIE = n.ID_SERIE
WHERE ps.CREDIT_TYPE = 'crew' AND COALESCE(ps.DELETED, 0) = 0
GROUP BY ps.CREW_JOB
ORDER BY series DESC
LIMIT 25;

-- 4. The 150 groups with the most famous member, one line per series.
--    rank_in_group 1 = most voted. creators and top3_cast are what the identity check compares.
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR, MAX(COALESCE(IMDB_VOTES, 0)) AS max_votes
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING COUNT(*) > 1
    ORDER BY max_votes DESC
    LIMIT 150
), s AS (
    SELECT g.max_votes, se.SERIE_TITLE, se.FIRST_AIR_YEAR, se.LAST_AIR_YEAR, se.ID_SERIE, se.ID_IMDB,
           COALESCE(se.IMDB_VOTES, 0) AS IMDB_VOTES, se.ORIGINAL_TITLE, se.ORIGINAL_LANGUAGE,
           ROW_NUMBER() OVER (PARTITION BY se.SERIE_TITLE, se.FIRST_AIR_YEAR
                              ORDER BY COALESCE(se.IMDB_VOTES, 0) DESC) AS rank_in_group
    FROM g
    JOIN T_WC_T2S_SERIE se ON se.SERIE_TITLE = g.SERIE_TITLE AND se.FIRST_AIR_YEAR = g.FIRST_AIR_YEAR
    WHERE COALESCE(se.DELETED, 0) = 0
)
SELECT s.SERIE_TITLE, s.FIRST_AIR_YEAR, s.LAST_AIR_YEAR, s.rank_in_group, s.ID_SERIE, s.ID_IMDB,
       s.IMDB_VOTES, s.ORIGINAL_TITLE, s.ORIGINAL_LANGUAGE,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY p.PERSON_NAME SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = s.ID_SERIE AND ps.CREDIT_TYPE = 'crew' AND ps.CREW_JOB = 'Creator'
           AND COALESCE(ps.DELETED, 0) = 0) AS creators,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY ps.DISPLAY_ORDER SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = s.ID_SERIE AND ps.CREDIT_TYPE = 'cast' AND ps.DISPLAY_ORDER < 3
           AND COALESCE(ps.DELETED, 0) = 0) AS top3_cast
FROM s
ORDER BY s.max_votes DESC, s.SERIE_TITLE, s.FIRST_AIR_YEAR, s.rank_in_group;

-- 5. The hard case: groups where two series or more have 1,000 votes or more, with the
--    discriminators, since these are the pairs the live bench must photograph.
WITH g AS (
    SELECT SERIE_TITLE, FIRST_AIR_YEAR
    FROM T_WC_T2S_SERIE
    WHERE COALESCE(DELETED, 0) = 0 AND SERIE_TITLE IS NOT NULL AND FIRST_AIR_YEAR IS NOT NULL
    GROUP BY SERIE_TITLE, FIRST_AIR_YEAR
    HAVING SUM(COALESCE(IMDB_VOTES, 0) >= 1000) >= 2
)
SELECT se.SERIE_TITLE, se.FIRST_AIR_YEAR, se.ID_SERIE, se.ID_IMDB, se.IMDB_VOTES,
       se.ORIGINAL_TITLE, se.ORIGINAL_LANGUAGE,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY p.PERSON_NAME SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = se.ID_SERIE AND ps.CREDIT_TYPE = 'crew' AND ps.CREW_JOB = 'Creator'
           AND COALESCE(ps.DELETED, 0) = 0) AS creators,
       (SELECT GROUP_CONCAT(p.PERSON_NAME ORDER BY ps.DISPLAY_ORDER SEPARATOR ' | ')
          FROM T_WC_T2S_PERSON_SERIE ps JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = ps.ID_PERSON
         WHERE ps.ID_SERIE = se.ID_SERIE AND ps.CREDIT_TYPE = 'cast' AND ps.DISPLAY_ORDER < 3
           AND COALESCE(ps.DELETED, 0) = 0) AS top3_cast
FROM g
JOIN T_WC_T2S_SERIE se ON se.SERIE_TITLE = g.SERIE_TITLE AND se.FIRST_AIR_YEAR = g.FIRST_AIR_YEAR
WHERE COALESCE(se.DELETED, 0) = 0
ORDER BY se.SERIE_TITLE, se.FIRST_AIR_YEAR, se.IMDB_VOTES DESC;
