-- Ground truth for user feedback #16 and #17 (2026-11-16, t2s-front, API 1.1.20): two "what share"
-- questions with "représente par un camembert" appended returned a film list instead of the share.
-- Also the Barbie gender split (2026-11-12, no feedback): right SQL, but a table.
-- Read-only (path 1).

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT 'A. Technical 58 (the black-and-white tag the API uses)' AS SECTION;
SELECT ID_TECHNICAL, ID_WIKIDATA, WIKIDATA_LABEL, TECHNICAL_TYPE, MOVIE_COUNT
FROM T_WC_T2S_TECHNICAL WHERE ID_TECHNICAL = 58 OR WIKIDATA_LABEL LIKE '%black%white%';

SELECT 'B. #16: films directed by Alfred Hitchcock, black and white against the rest' AS SECTION;
SELECT SUM(bw) AS BW_FILMS, COUNT(*) AS FILMS, ROUND(SUM(bw) / COUNT(*), 4) AS BW_SHARE
FROM (
  SELECT m.ID_MOVIE,
         MAX(CASE WHEN mt.ID_TECHNICAL = 58 AND (mt.DELETED IS NULL OR mt.DELETED = 0) THEN 1 ELSE 0 END) AS bw
  FROM T_WC_T2S_MOVIE m
  JOIN T_WC_T2S_PERSON_MOVIE pm ON pm.ID_MOVIE = m.ID_MOVIE AND pm.CREDIT_TYPE = 'crew' AND pm.CREW_JOB = 'Director'
  JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON AND p.PERSON_NAME = 'Alfred Hitchcock'
  LEFT JOIN T_WC_T2S_MOVIE_TECHNICAL mt ON mt.ID_MOVIE = m.ID_MOVIE
  WHERE (m.DELETED IS NULL OR m.DELETED = 0) AND (pm.DELETED IS NULL OR pm.DELETED = 0)
  GROUP BY m.ID_MOVIE
) t;

SELECT 'C. #17: Palme d''Or wins (award rows), with a French production country or not' AS SECTION;
SELECT ID_AWARD, AWARD_NAME, MOVIE_COUNT FROM T_WC_T2S_AWARD WHERE AWARD_NAME = 'Palme d''Or';

SELECT CASE WHEN EXISTS (SELECT 1 FROM T_WC_T2S_MOVIE_PRODUCTION_COUNTRY pc
                         WHERE pc.ID_MOVIE = ma.ID_MOVIE AND pc.COUNTRY_CODE = 'FR'
                           AND (pc.DELETED IS NULL OR pc.DELETED = 0))
            THEN 'French production' ELSE 'Other' END AS PART,
       COUNT(DISTINCT ma.ID_MOVIE) AS FILMS, COUNT(*) AS AWARD_ROWS
FROM T_WC_T2S_MOVIE_AWARD ma
JOIN T_WC_T2S_AWARD a ON a.ID_AWARD = ma.ID_AWARD AND a.AWARD_NAME = 'Palme d''Or'
WHERE (ma.DELETED IS NULL OR ma.DELETED = 0)
GROUP BY PART;

SELECT 'D. Barbie (2023) cast by gender (GENDER 1 = female, 2 = male, 0 = not set)' AS SECTION;
SELECT p.GENDER, COUNT(DISTINCT p.ID_PERSON) AS ACTORS
FROM T_WC_T2S_PERSON_MOVIE pm
JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = pm.ID_PERSON
JOIN T_WC_T2S_MOVIE m ON m.ID_MOVIE = pm.ID_MOVIE
WHERE m.MOVIE_TITLE = 'Barbie' AND YEAR(m.DAT_RELEASE) = 2023 AND pm.CREDIT_TYPE = 'cast'
  AND (pm.DELETED IS NULL OR pm.DELETED = 0)
GROUP BY p.GENDER ORDER BY p.GENDER;
