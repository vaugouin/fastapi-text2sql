-- ============================================================================
-- Nouvelle evaluation : une requete dont la bonne reponse exige l'operateur <>
-- ============================================================================
--
-- NON ENCORE APPLIQUE. 1 evaluation, categorie 12 (Movies - Complex queries).
--
-- POURQUOI CE FICHIER EXISTE. Le 2026-10-02, l'ASSERTION_REFRESH_SQL de l'eval 2517
-- a perdu son "<>" a l'enregistrement dans le back-office : f_striphtmltags lisait
-- "<>" comme une balise HTML vide et l'effacait, MariaDB repondait #1064. Correctif
-- dans webathenkel lib/global.inc.php et tmdb-front lib/global-light.inc.php (commit
-- 09bd5aa). Cette evaluation teste l'autre bout de la chaine : que l'API ecrive
-- elle-meme une exclusion par inegalite quand la question l'exige.
--
-- LA QUESTION. "Quels autres films sont sortis la meme annee que Pulp Fiction ?" Le
-- mot "autres" impose d'exclure le film de reference, et la forme naturelle est une
-- auto-jointure ou une sous-requete sur RELEASE_YEAR, plus ID_MOVIE <> 680. Une
-- requete qui oublie l'exclusion rend Pulp Fiction dans sa propre liste.
--
-- CE QUE LES ASSERTIONS PROTEGENT, selon les trois niveaux du README 4.5 :
--   * plancher : COUNT(*) > 20, 1994 compte des centaines de films en base ;
--   * ancre : Les Evades (278) et Forrest Gump (13), tetes de 1994 au classement
--     IMDB_RATING_WEIGHTED, donc dans les 100 premieres lignes ;
--   * contre-exemple : Pulp Fiction (680) NOT IN. C'est lui qui mesure l'exclusion,
--     quelle que soit la forme SQL choisie par le modele.
--   * regex SQL : (<>|!=). Les deux operateurs sont strictement equivalents en
--     MariaDB, refuser != punirait une requete juste. Une exclusion ecrite en NOT IN
--     ou NOT EXISTS ferait rougir la regex seule ; c'est accepte, puisque c'est
--     l'operateur d'inegalite que l'evaluation veut voir.
--
-- STOCKAGE. Les chevrons sont ecrits &lt; et &gt;, comme le formulaire les stocke ;
-- le harnais passe les trois assertions par html.unescape() avant usage. Aucun
-- antislash dans la regex, donc rien a doubler.
--
-- PAS D'ASSERTION_REFRESH_SQL, et c'est delibere : le rafraichissement reecrirait
-- ASSERTIONS_QUERY_RESULT en un simple IN (...) et effacerait le NOT IN (680), qui
-- fait tout l'interet de la fiche (README 4.6). L'annee de sortie d'un film est un
-- fait, pas un classement.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. Avant. Doit rendre zero ligne ; une ligne ici veut dire que la question
--    existe deja et que la garde du INSERT fera son office.
-- ---------------------------------------------------------------------------
SELECT '0. Etat avant insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Which other movies were released the same year as Pulp Fiction?';

-- ---------------------------------------------------------------------------
-- 1. Les temoins en base. A lire AVANT d'inserer.
--    a) Pulp Fiction : une seule ligne attendue, ID_MOVIE 680, RELEASE_YEAR 1994.
--       Une homonymie ici changerait la question.
--    b) Le haut de 1994 au classement par defaut : 278 et 13 doivent y figurer.
--       Sinon, remplacer l'ancre par les deux premiers ID que cette section montre.
-- ---------------------------------------------------------------------------
SELECT '1a. Pulp Fiction en base' AS SECTION;

SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE, T_WC_T2S_MOVIE.RELEASE_YEAR,
       T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED
FROM T_WC_T2S_MOVIE
WHERE T_WC_T2S_MOVIE.MOVIE_TITLE = 'Pulp Fiction';

SELECT '1b. Haut de 1994, Pulp Fiction exclu' AS SECTION;

SELECT other.ID_MOVIE, other.MOVIE_TITLE, other.IMDB_RATING_WEIGHTED
FROM T_WC_T2S_MOVIE ref
JOIN T_WC_T2S_MOVIE other ON other.RELEASE_YEAR = ref.RELEASE_YEAR
WHERE ref.ID_MOVIE = 680
  AND other.ID_MOVIE <> ref.ID_MOVIE
ORDER BY other.IMDB_RATING_WEIGHTED DESC
LIMIT 10;

SELECT '1c. Taille de la reponse (plancher > 20)' AS SECTION;

SELECT COUNT(*) AS FILMS_1994_HORS_PULP_FICTION
FROM T_WC_T2S_MOVIE ref
JOIN T_WC_T2S_MOVIE other ON other.RELEASE_YEAR = ref.RELEASE_YEAR
WHERE ref.ID_MOVIE = 680
  AND other.ID_MOVIE <> ref.ID_MOVIE;

-- ---------------------------------------------------------------------------
-- 2. L'evaluation.
-- ---------------------------------------------------------------------------
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which other movies were released the same year as Pulp Fiction?',
       'Quels autres films sont sortis la même année que Pulp Fiction ?',
       1, 0, 12, 0, CURDATE(), NOW(),
       '(?i)(&lt;&gt;|!=)',
       'COUNT(*) &gt; 20 AND ID_MOVIE IN (278, 13) AND ID_MOVIE NOT IN (680)',
       'Le mot autres impose d exclure le film de reference : la requete doit retrouver l annee de Pulp Fiction puis s en retirer par une inegalite (ID_MOVIE <> 680 ou equivalent). Le contre-exemple NOT IN (680) attrape l exclusion oubliee quelle que soit la forme SQL ; la regex verifie que l inegalite est bien ecrite.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which other movies were released the same year as Pulp Fiction?') AS existing);

-- ---------------------------------------------------------------------------
-- 3. Apres. Doit rendre une ligne, categorie 12, regex (?i)(&lt;&gt;|!=).
--    Le LONG_DESC doit encore contenir "<>" : ce texte part par SQL et non par le
--    formulaire, donc aucun filtre ne l'a touche.
-- ---------------------------------------------------------------------------
SELECT '3. Etat apres insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY,
       ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT,
       LOCATE('<>', LONG_DESC) > 0 AS LONG_DESC_GARDE_LE_CHEVRON
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Which other movies were released the same year as Pulp Fiction?';
