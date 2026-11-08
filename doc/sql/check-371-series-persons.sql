-- Evaluations for the co-constrained rescue beyond movie titles (FASTAPI-TEXT2SQL-369 series
-- branch, and the reverse case of the broader ticket: a partial person name constrained by a
-- resolved title). Read only, voie 1, 2026-11-08.
--   ssh vps-agent pull fastapi-text2sql-blue
--   ssh vps-agent run fastapi-text2sql-blue/doc/sql/check-371-series-persons.sql

-- 1. Series credits of the candidate persons whose bare word matches the series title
SELECT p.PERSON_NAME, p.ID_PERSON, s.ID_SERIE, s.FIRST_AIR_YEAR, s.IMDB_VOTES, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.ORIGINAL_TITLE
FROM T_WC_T2S_PERSON p
JOIN T_WC_T2S_PERSON_SERIE ps ON ps.ID_PERSON = p.ID_PERSON
JOIN T_WC_T2S_SERIE s ON s.ID_SERIE = ps.ID_SERIE
WHERE (p.PERSON_NAME = 'Steve Carell'        AND s.SERIE_TITLE LIKE '%Office%')
   OR (p.PERSON_NAME = 'Bryan Cranston'      AND s.SERIE_TITLE LIKE '%Breaking%')
   OR (p.PERSON_NAME = 'Emilia Clarke'       AND s.SERIE_TITLE LIKE '%Thrones%')
   OR (p.PERSON_NAME = 'Dominic West'        AND s.SERIE_TITLE LIKE '%Wire%')
   OR (p.PERSON_NAME = 'Claire Foy'          AND s.SERIE_TITLE LIKE '%Crown%')
   OR (p.PERSON_NAME = 'Mathieu Kassovitz'   AND (s.SERIE_TITLE LIKE '%Bureau%' OR s.SERIE_TITLE_FR LIKE '%Bureau%'))
   OR (p.PERSON_NAME = 'Omar Sy'             AND s.SERIE_TITLE LIKE '%Lupin%')
   OR (p.PERSON_NAME = 'Benedict Cumberbatch' AND s.SERIE_TITLE LIKE '%Sherlock%')
GROUP BY p.ID_PERSON, s.ID_SERIE
ORDER BY p.PERSON_NAME, s.FIRST_AIR_YEAR;

-- 2. Exact-title series homonyms of the bare words (what the lexicon can pick alone)
SELECT s.ID_SERIE, s.FIRST_AIR_YEAR, s.IMDB_VOTES, s.POPULARITY, s.SERIE_TITLE, s.SERIE_TITLE_FR, s.ORIGINAL_TITLE
FROM T_WC_T2S_SERIE s
WHERE s.SERIE_TITLE IN ('Office', 'Breaking', 'Thrones', 'Wire', 'Crown', 'Bureau', 'Lupin', 'Sherlock', 'The Office', 'The Crown', 'The Wire')
   OR s.SERIE_TITLE_FR IN ('Office', 'Breaking', 'Thrones', 'Wire', 'Crown', 'Bureau', 'Lupin', 'Sherlock', 'Le Bureau')
   OR s.ORIGINAL_TITLE IN ('Office', 'Breaking', 'Thrones', 'Wire', 'Crown', 'Bureau', 'Lupin', 'Sherlock')
ORDER BY s.SERIE_TITLE, s.FIRST_AIR_YEAR;

-- 3. Persons whose name is exactly, or ends with, a bare surname (homonyms for the reverse case)
SELECT x.SURNAME, COUNT(*) AS PERSONS, SUM(p.PERSON_NAME = x.SURNAME) AS EXACT_BARE,
       SUBSTRING_INDEX(GROUP_CONCAT(p.PERSON_NAME ORDER BY p.POPULARITY DESC SEPARATOR ', '), ', ', 6) AS MOST_POPULAR
FROM (SELECT 'Grant' AS SURNAME UNION ALL SELECT 'Foster' UNION ALL SELECT 'Reno'
      UNION ALL SELECT 'Phoenix' UNION ALL SELECT 'Jackson' UNION ALL SELECT 'Clavier') x
JOIN T_WC_T2S_PERSON p ON p.PERSON_NAME = x.SURNAME OR p.PERSON_NAME LIKE CONCAT('% ', x.SURNAME)
GROUP BY x.SURNAME;

-- 4. The intended films and the full-name person credited on each
SELECT m.ID_MOVIE, m.RELEASE_YEAR, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, p.ID_PERSON, p.PERSON_NAME, pm.CREDIT_TYPE
FROM T_WC_T2S_MOVIE m
JOIN T_WC_T2S_PERSON_MOVIE pm ON pm.ID_MOVIE = m.ID_MOVIE
JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON
WHERE (m.MOVIE_TITLE = 'Notting Hill' AND p.PERSON_NAME LIKE '% Grant')
   OR (m.MOVIE_TITLE = 'Taxi Driver'  AND p.PERSON_NAME LIKE '% Foster')
   OR (m.MOVIE_TITLE_FR = 'Les Visiteurs' AND p.PERSON_NAME LIKE '% Clavier')
   OR (m.MOVIE_TITLE = 'Gladiator'    AND p.PERSON_NAME LIKE '% Phoenix')
   OR (m.MOVIE_TITLE = 'Pulp Fiction' AND p.PERSON_NAME LIKE '% Jackson')
GROUP BY m.ID_MOVIE, p.ID_PERSON, pm.CREDIT_TYPE
ORDER BY m.MOVIE_TITLE, m.RELEASE_YEAR;
