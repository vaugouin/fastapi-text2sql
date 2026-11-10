-- FASTAPI-TEXT2SQL-371 step 2: can a one-word alias hand a bare surname to the wrong person
-- WHILE the query still returns rows?
--
-- Step 1 completes a bare surname within the cast and crew of the work, but only on an empty
-- first page. The case it cannot see: the bare word W is a one-word alias (T_WC_T2S_PERSON_ALSO_KNOWN_AS)
-- of a person X credited on film M, while another person Y credited on M has W as surname.
-- "M with W" then resolves W to X (when the person gate rejects the bare word), returns X's
-- rows on M, and the user who meant Y gets a wrong non-empty answer.
-- Upper bound: the AKA level is only reached when the T_WC_T2S_PERSON gate rejects the word.
-- Scope: films with at least 10,000 IMDb votes (the films people name by title).
-- Voie 1 (SELECT and temporary tables only).

CREATE TEMPORARY TABLE tmp_alias1 (ID_PERSON INT NOT NULL, W VARCHAR(255) NOT NULL, KEY (W), KEY (ID_PERSON))
SELECT DISTINCT ID_PERSON, TRIM(PERSON_NAME_NORM) AS W
FROM T_WC_T2S_PERSON_ALSO_KNOWN_AS
WHERE (DELETED IS NULL OR DELETED = 0)
  AND TRIM(PERSON_NAME_NORM) NOT LIKE '% %'
  AND CHAR_LENGTH(TRIM(PERSON_NAME_NORM)) >= 3;

CREATE TEMPORARY TABLE tmp_film (ID_MOVIE INT NOT NULL PRIMARY KEY, MOVIE_TITLE VARCHAR(500), IMDB_VOTES INT)
SELECT ID_MOVIE, MOVIE_TITLE, IMDB_VOTES FROM T_WC_T2S_MOVIE WHERE IMDB_VOTES >= 10000;

CREATE TEMPORARY TABLE tmp_cred (ID_MOVIE INT NOT NULL, ID_PERSON INT NOT NULL, IS_CAST TINYINT, LASTW VARCHAR(255),
                                 KEY (ID_MOVIE, LASTW), KEY (ID_PERSON))
SELECT c.ID_MOVIE, c.ID_PERSON, MAX(c.CREDIT_TYPE = 'cast') AS IS_CAST,
       LOWER(SUBSTRING_INDEX(TRIM(p.PERSON_NAME), ' ', -1)) AS LASTW
FROM T_WC_T2S_PERSON_MOVIE c
JOIN tmp_film f ON f.ID_MOVIE = c.ID_MOVIE
JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = c.ID_PERSON
GROUP BY c.ID_MOVIE, c.ID_PERSON, p.PERSON_NAME;

-- X: credited on M and carrying the one-word alias W.
CREATE TEMPORARY TABLE tmp_xw (ID_MOVIE INT NOT NULL, X INT NOT NULL, X_CAST TINYINT, X_LAST VARCHAR(255), W VARCHAR(255),
                               KEY (ID_MOVIE, W))
SELECT c.ID_MOVIE, c.ID_PERSON AS X, c.IS_CAST AS X_CAST, c.LASTW AS X_LAST, a.W
FROM tmp_cred c JOIN tmp_alias1 a ON a.ID_PERSON = c.ID_PERSON;

-- Collisions: Y on the same film, surname W, another person.
CREATE TEMPORARY TABLE tmp_coll
SELECT x.ID_MOVIE, x.W, x.X, x.X_CAST, x.X_LAST, y.ID_PERSON AS Y, y.IS_CAST AS Y_CAST
FROM tmp_xw x JOIN tmp_cred y ON y.ID_MOVIE = x.ID_MOVIE AND y.LASTW = x.W AND y.ID_PERSON <> x.X;

-- 1. Sizes.
SELECT (SELECT COUNT(*) FROM tmp_alias1) AS one_word_aliases,
       (SELECT COUNT(*) FROM tmp_film) AS films_10k_votes,
       (SELECT COUNT(*) FROM tmp_cred) AS credits_on_them,
       (SELECT COUNT(*) FROM tmp_xw) AS alias_holders_credited,
       (SELECT COUNT(*) FROM (SELECT DISTINCT ID_MOVIE, W FROM tmp_xw) t) AS film_word_pairs_with_alias_holder;

-- 2. Collisions: all, and those where the alias holder X does not have W as its own surname
--    (the bare word then points at Y by surname and at X only through the alias).
SELECT COUNT(*) AS collision_rows,
       COUNT(DISTINCT ID_MOVIE, W) AS film_word_pairs,
       SUM(X_LAST <> W) AS rows_x_surname_differs,
       COUNT(DISTINCT CASE WHEN X_LAST <> W THEN CONCAT(ID_MOVIE, ':', W) END) AS pairs_x_surname_differs,
       SUM(X_LAST <> W AND Y_CAST = 1) AS rows_differs_y_cast,
       SUM(X_LAST <> W AND Y_CAST = 1 AND X_CAST = 0) AS rows_differs_y_cast_x_crew
FROM tmp_coll;

-- 3. The most voted films where it happens (X surname differs from W).
SELECT f.MOVIE_TITLE, f.IMDB_VOTES, k.W,
       px.PERSON_NAME AS alias_holder_x, IF(k.X_CAST, 'cast', 'crew') AS x_credit, ROUND(px.POPULARITY, 1) AS x_pop,
       py.PERSON_NAME AS surname_y, IF(k.Y_CAST, 'cast', 'crew') AS y_credit, ROUND(py.POPULARITY, 1) AS y_pop
FROM tmp_coll k
JOIN tmp_film f ON f.ID_MOVIE = k.ID_MOVIE
JOIN T_WC_T2S_PERSON px ON px.ID_PERSON = k.X
JOIN T_WC_T2S_PERSON py ON py.ID_PERSON = k.Y
WHERE k.X_LAST <> k.W
ORDER BY f.IMDB_VOTES DESC, k.W
LIMIT 60;

-- 4. The five bare surnames of evaluations 2674 to 2678: who holds them as a one-word alias.
SELECT a.W, COUNT(*) AS alias_holders, GROUP_CONCAT(p.PERSON_NAME ORDER BY p.POPULARITY DESC SEPARATOR ', ') AS holders
FROM tmp_alias1 a JOIN T_WC_T2S_PERSON p ON p.ID_PERSON = a.ID_PERSON
WHERE a.W IN ('grant', 'foster', 'phoenix', 'clavier', 'jackson')
GROUP BY a.W;
