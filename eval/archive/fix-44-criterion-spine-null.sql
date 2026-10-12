-- ============================================================================
-- Eval 44 « Criterion Collection » : le numero de collection vaut NULL, plus 0
-- ============================================================================
--
-- CE QUI S'EST PASSE. Le 2026-08-26, TMDB-MOVIE-PREPROCESS-043 a fait lire
-- T_WC_T2S_MOVIE.ID_CRITERION_SPINE dans les statements Wikidata V2 au lieu de la
-- table V1. V1 rangeait 0 pour « ce film n'a pas de numero de collection », V2 ne
-- range rien, donc NULL. C'est une correction : 0 n'a jamais designe un film.
--
-- MAIS L'EXPRESSION DE TRI ETAIT ECRITE CONTRE LE 0 :
--
--   ORDER BY CASE WHEN ID_CRITERION_SPINE = 0 THEN 1 ELSE 0 END, ID_CRITERION_SPINE ASC
--
-- NULL = 0 ne vaut pas vrai, il vaut NULL. Le CASE tombe donc dans le ELSE et rend
-- 0, puis ORDER BY ... ASC place les NULL EN TETE sous MariaDB. Les ~447 films sans
-- numero sont passes de la fin de la liste a son debut, sans erreur ni message.
--
-- ⚠ ET L'EVAL A ABSORBE LE DEFAUT AU LIEU DE LE SIGNALER. Son assertion s'est
-- auto-rafraichie a 04:56:40 le 2026-08-27, c'est-a-dire APRES le passage de nuit :
-- elle a capture le nouvel ordre et l'enregistre desormais comme attendu. L'eval
-- passe au vert en garantissant le defaut.
--
-- La lecon depasse cette ligne : une assertion qui se rafraichit depuis la MEME
-- expression que celle qu'elle est censee tester ne peut pas, par construction,
-- attraper un defaut DANS cette expression. Elle teste la stabilite, pas la
-- justesse. C'est a verser au registre de topics/evaluations.md.
--
-- ⚠ COLLATION. Lancer avec --force. Sans la premiere ligne, une comparaison passant
-- par un CAST rend ERROR 1267.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. AVANT. Etat courant, a lire avant de modifier quoi que ce soit.
-- ---------------------------------------------------------------------------
SELECT '0. Etat avant correction' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 40) AS QUESTION,
       LEFT(ASSERTIONS_QUERY_RESULT, 60) AS ASSERTION,
       ASSERTION_REFRESH_LAST
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 0b. LE MEME DEFAUT AILLEURS ? A lire avant de conclure que 44 est un cas isole.
--     Toute eval dont le SQL de rafraichissement compare un SPINE a 0 porte le
--     meme probleme, et une seule requete le dit.
-- ---------------------------------------------------------------------------
SELECT '0b. Autres evals portant la comparaison a zero' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 50) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE ASSERTION_REFRESH_SQL LIKE '%ID_CRITERION_SPINE = 0%'
   OR ASSERTIONS_QUERY_RESULT LIKE '%ID_CRITERION_SPINE = 0%'
   OR ASSERTIONS_SQL_QUERY LIKE '%ID_CRITERION_SPINE = 0%';

-- ---------------------------------------------------------------------------
-- 1. LA CORRECTION. Trois gestes en un seul UPDATE.
--
--    (a) ASSERTION_REFRESH_SQL : COALESCE couvre les deux etats, 0 comme NULL.
--        Ecrit ainsi, il reste juste sur une base pas encore migree.
--    (b) ASSERTIONS_QUERY_RESULT : remis sur les vingt premiers numeros de
--        collection, 1 a 20, releves dans l'export du 2026-08-27. Ce sont les
--        Criterion que la question attend : La Grande Illusion, Les Sept
--        Samourais, Une femme disparait, Amarcord, Les Quatre Cents Coups...
--    (c) ASSERTION_REFRESH_LAST a NULL, pour que le job de rafraichissement
--        repasse et confirme lui-meme, plutot que de me croire sur parole.
-- ---------------------------------------------------------------------------

UPDATE T_WC_T2S_EVALUATION
SET ASSERTION_REFRESH_SQL = 'SELECT DISTINCT T_WC_T2S_MOVIE.ID_MOVIE FROM T_WC_T2S_MOVIE WHERE T_WC_T2S_MOVIE.ID_CRITERION IS NOT NULL AND T_WC_T2S_MOVIE.ID_CRITERION > 0 ORDER BY CASE WHEN COALESCE(T_WC_T2S_MOVIE.ID_CRITERION_SPINE, 0) = 0 THEN 1 ELSE 0 END, T_WC_T2S_MOVIE.ID_CRITERION_SPINE ASC LIMIT 20',
    ASSERTIONS_QUERY_RESULT = 'ID_MOVIE IN (777, 346, 940, 7857, 147, 648, 10971, 10835, 11782, 36040, 490, 11031, 274, 31372, 31374, 31378, 5336, 26031, 25504, 14924)',
    ASSERTION_REFRESH_LAST = NULL
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 2. APRES. L'assertion doit citer 777 en premier, et non 30734.
-- ---------------------------------------------------------------------------
SELECT '2. Etat apres correction' AS SECTION;

SELECT ID_T2S_EVALUATION,
       ASSERTIONS_QUERY_RESULT,
       ASSERTION_REFRESH_SQL,
       ASSERTION_REFRESH_LAST
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 3. CONTROLE INDEPENDANT. Rejoue le SQL corrige et compare a l'oeil : la liste
--    doit commencer par les numeros 1, 2, 3 et finir par le 20, et non par une
--    suite de films sans numero.
-- ---------------------------------------------------------------------------
SELECT '3. Ce que le SQL corrige produit reellement' AS SECTION;

SELECT T_WC_T2S_MOVIE.ID_MOVIE, T_WC_T2S_MOVIE.MOVIE_TITLE,
       T_WC_T2S_MOVIE.ID_CRITERION_SPINE
FROM T_WC_T2S_MOVIE
WHERE T_WC_T2S_MOVIE.ID_CRITERION IS NOT NULL AND T_WC_T2S_MOVIE.ID_CRITERION > 0
ORDER BY CASE WHEN COALESCE(T_WC_T2S_MOVIE.ID_CRITERION_SPINE, 0) = 0 THEN 1 ELSE 0 END,
         T_WC_T2S_MOVIE.ID_CRITERION_SPINE ASC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- 4. LE ZERO SUBSISTE-T-IL ? Le passage du 2026-08-26 a laisse UNE ligne a 0,
--    King Kong vs. Godzilla, parce que Wikidata porte un P12279 valant « 0 » et
--    que le garde numerique l'acceptait. Le garde a ete resserre le 2026-08-27
--    (tmdb_preprocess_helpers.f_wikidatabestvaluesql) : apres le prochain
--    passage, cette requete doit rendre zero ligne.
-- ---------------------------------------------------------------------------
SELECT '4. Zeros restants sur le numero de collection (attendu apres passage : 0)' AS SECTION;

SELECT ID_MOVIE, MOVIE_TITLE, ID_CRITERION, ID_CRITERION_SPINE
FROM T_WC_T2S_MOVIE
WHERE ID_CRITERION_SPINE = 0;
