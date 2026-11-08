-- FASTAPI-TEXT2SQL-371: the two queries of entity.plan_co_constrained_person_rescue, as the code
-- builds them, for "Gladiator" and "Taxi Driver" (read only, voie 1, 2026-11-08). Checks that
-- they run on MariaDB and that the pool holds the person the bare surname means.
--   ssh vps-agent run fastapi-text2sql-blue/doc/sql/check-371-person-pool.sql

SELECT `ID_MOVIE` AS _ID FROM `T_WC_T2S_MOVIE` WHERE `MOVIE_TITLE` = 'Gladiator' OR `MOVIE_TITLE_FR` = 'Gladiator' OR `ORIGINAL_TITLE` = 'Gladiator';

SELECT p.ID_PERSON AS _ID, p.PERSON_NAME, p.POPULARITY AS _POP, MAX(x._CAST) AS _CAST
FROM (SELECT c.ID_PERSON, 0 AS _W, MAX(c.CREDIT_TYPE = 'cast') AS _CAST FROM `T_WC_T2S_PERSON_MOVIE` c
      WHERE c.`ID_MOVIE` IN (SELECT ID_MOVIE FROM T_WC_T2S_MOVIE WHERE MOVIE_TITLE = 'Gladiator' OR MOVIE_TITLE_FR = 'Gladiator' OR ORIGINAL_TITLE = 'Gladiator') GROUP BY c.ID_PERSON) x
JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = x.ID_PERSON
GROUP BY p.ID_PERSON, p.PERSON_NAME, p.POPULARITY HAVING COUNT(DISTINCT x._W) = 1
ORDER BY (p.PERSON_NAME LIKE '% Phoenix') DESC, p.POPULARITY DESC LIMIT 8;

SELECT p.ID_PERSON AS _ID, p.PERSON_NAME, p.POPULARITY AS _POP, MAX(x._CAST) AS _CAST, COUNT(*) OVER () AS POOL_SIZE
FROM (SELECT c.ID_PERSON, 0 AS _W, MAX(c.CREDIT_TYPE = 'cast') AS _CAST FROM `T_WC_T2S_PERSON_MOVIE` c
      WHERE c.`ID_MOVIE` IN (103) GROUP BY c.ID_PERSON) x
JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = x.ID_PERSON
GROUP BY p.ID_PERSON, p.PERSON_NAME, p.POPULARITY HAVING COUNT(DISTINCT x._W) = 1
ORDER BY (p.PERSON_NAME LIKE '% Foster') DESC, p.POPULARITY DESC LIMIT 5;
