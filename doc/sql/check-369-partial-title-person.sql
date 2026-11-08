-- FASTAPI-TEXT2SQL-369: "Film Raid avec Dany Boon" returns 0 rows.
-- Read-only measurement (voie 1, ssh vps-agent) feeding the co-constrained title rescue:
-- 1. the persons of the test questions, 2. their film credits (the pool the rescue scores
-- the partial title against), 3. the exact-title homonyms the lexicon picks today, and
-- whether the named person is credited on any of them.

-- 1. Persons
SELECT p.ID_PERSON, p.PERSON_NAME, p.POPULARITY
FROM T_WC_T2S_PERSON p
WHERE p.PERSON_NAME IN ('Dany Boon', 'Samy Naceri', 'Viggo Mortensen', 'Jean Reno', 'Al Pacino', 'Gérard Depardieu', 'Keanu Reeves', 'Christian Clavier')
ORDER BY p.PERSON_NAME, p.POPULARITY DESC;

-- 2. Film credits of those persons, one row per film and credit type
SELECT p.PERSON_NAME, m.ID_MOVIE, m.RELEASE_YEAR, m.IMDB_VOTES,
       pm.CREDIT_TYPE, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.ORIGINAL_TITLE
FROM T_WC_T2S_PERSON p
JOIN T_WC_T2S_PERSON_MOVIE pm ON pm.ID_PERSON = p.ID_PERSON
JOIN T_WC_T2S_MOVIE m ON m.ID_MOVIE = pm.ID_MOVIE
WHERE p.PERSON_NAME IN ('Dany Boon', 'Samy Naceri', 'Viggo Mortensen', 'Jean Reno', 'Al Pacino', 'Gérard Depardieu', 'Keanu Reeves', 'Christian Clavier')
GROUP BY p.PERSON_NAME, m.ID_MOVIE, pm.CREDIT_TYPE
ORDER BY p.PERSON_NAME, m.RELEASE_YEAR, m.ID_MOVIE, pm.CREDIT_TYPE;

-- 3. Exact-title homonyms of the bare words, and how many test persons are credited on each
SELECT m.ID_MOVIE, m.RELEASE_YEAR, m.IMDB_VOTES, m.MOVIE_TITLE, m.MOVIE_TITLE_FR, m.ORIGINAL_TITLE,
       GROUP_CONCAT(DISTINCT p.PERSON_NAME ORDER BY p.PERSON_NAME SEPARATOR ', ') AS TEST_PERSONS_CREDITED
FROM T_WC_T2S_MOVIE m
LEFT JOIN T_WC_T2S_PERSON_MOVIE pm ON pm.ID_MOVIE = m.ID_MOVIE
LEFT JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON
     AND p.PERSON_NAME IN ('Dany Boon', 'Samy Naceri', 'Viggo Mortensen', 'Jean Reno', 'Al Pacino', 'Gérard Depardieu', 'Keanu Reeves', 'Christian Clavier')
WHERE m.MOVIE_TITLE IN ('Raid', 'Taxi', 'Visiteurs', 'Godfather', 'Rings', 'Matrix', 'Astérix', 'Ch''tis')
   OR m.MOVIE_TITLE_FR IN ('Raid', 'Taxi', 'Visiteurs', 'Godfather', 'Rings', 'Matrix', 'Astérix', 'Ch''tis')
   OR m.ORIGINAL_TITLE IN ('Raid', 'Taxi', 'Visiteurs', 'Godfather', 'Rings', 'Matrix', 'Astérix', 'Ch''tis')
GROUP BY m.ID_MOVIE
ORDER BY m.MOVIE_TITLE, m.RELEASE_YEAR;
