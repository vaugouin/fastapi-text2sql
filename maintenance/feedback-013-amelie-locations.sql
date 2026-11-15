-- Ground truth for user feedback #13 (2026-11-15, voice-agent, API 1.1.20):
-- "Show me on a map all the Parisian locations for the movie Amélie" failed twice,
-- the rephrased "find the movie Amélie and map the filming locations in Paris" returned 3 pins.
-- Read-only (path 1).

SELECT 'A. Movies titled Amelie / Amélie' AS SECTION;
SELECT ID_MOVIE, MOVIE_TITLE, MOVIE_TITLE_FR, ORIGINAL_TITLE, RELEASE_DATE
FROM T_WC_T2S_MOVIE
WHERE (MOVIE_TITLE IN ('Amélie', 'Amelie') OR MOVIE_TITLE_FR LIKE '%Amélie Poulain%' OR ORIGINAL_TITLE LIKE '%Amélie Poulain%')
  AND (DELETED IS NULL OR DELETED = 0);

SELECT 'B. Every location linked to movie 194, with its role and whether Paris is an ancestor' AS SECTION;
SELECT ml.LOCATION_ROLE, loc.ID_LOCATION, loc.ID_WIKIDATA, loc.LOCATION_NAME, loc.LOCATION_TYPE,
       loc.LATITUDE, loc.LONGITUDE,
       (SELECT MIN(la.DEPTH) FROM T_WC_T2S_LOCATION_ANCESTOR la
          JOIN T_WC_T2S_LOCATION p ON p.ID_LOCATION = la.ID_ANCESTOR
         WHERE la.ID_LOCATION = loc.ID_LOCATION AND p.LOCATION_NAME = 'Paris' AND p.DELETED = 0) AS PARIS_DEPTH
FROM T_WC_T2S_MOVIE_LOCATION ml
JOIN T_WC_T2S_LOCATION loc ON loc.ID_LOCATION = ml.ID_LOCATION
WHERE ml.ID_MOVIE = 194 AND loc.DELETED = 0
ORDER BY ml.LOCATION_ROLE, loc.LOCATION_NAME;

SELECT 'C. Ancestors of the three pins served (3950 Montmartre, 38 Paris, 6585 Porte des Lilas - Cinema)' AS SECTION;
SELECT la.ID_LOCATION, la.DEPTH, p.ID_LOCATION AS ID_ANCESTOR, p.LOCATION_NAME AS ANCESTOR_NAME, p.LOCATION_TYPE
FROM T_WC_T2S_LOCATION_ANCESTOR la
JOIN T_WC_T2S_LOCATION p ON p.ID_LOCATION = la.ID_ANCESTOR
WHERE la.ID_LOCATION IN (3950, 38, 6585)
ORDER BY la.ID_LOCATION, la.DEPTH;

SELECT 'D. Locations named Paris (homonyms the provenance guard or resolution could meet)' AS SECTION;
SELECT ID_LOCATION, ID_WIKIDATA, LOCATION_NAME, LOCATION_TYPE, LATITUDE, LONGITUDE
FROM T_WC_T2S_LOCATION
WHERE LOCATION_NAME = 'Paris' AND DELETED = 0;
