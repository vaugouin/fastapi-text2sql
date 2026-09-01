-- ============================================================================
-- Nouvelles évaluations fermant FASTAPI-TEXT2SQL-238 (aplatissement des prix)
-- ============================================================================
--
-- NON ENCORE APPLIQUÉ. 2 évaluations, catégorie 27 (Persons, cast & crew).
--
-- POURQUOI CE FICHIER EXISTE. La règle du dépôt : « un défaut de l'API se ferme par
-- une évaluation, jamais par un ticket seul ». Le défaut ferme ici est que
-- data/text_to_sql.md décrivait au modèle T_WC_WIKIDATA_ITEM_PROPERTY, la table qui
-- APLATIT la valeur principale d'un statement et les valeurs de tous ses
-- qualificatifs sous le même ID_PROPERTY. Sous P166 y cohabitaient donc, comme s'il
-- s'agissait de prix : la récompense, la cérémonie qui l'a remise, l'œuvre pour
-- laquelle elle l'a été, et les CO-LAURÉATS. Mesuré le 2026-08-29 : 26 815 des
-- 27 449 items sous P166 étaient des valeurs de qualificatif, dont 6 290 co-lauréats
-- sous P1346.
--
-- LA VÉRIFICATION PRÉALABLE A ÉTÉ FAITE, et selon les trois questions ordonnées de
-- la règle (la question existe-t-elle / porte-t-elle une assertion / cette assertion
-- aurait-elle attrapé CE défaut) :
--
--   * Des évaluations sur les prix existent, mais elles interrogent l'objet et non le
--     sujet : « quel film de Scorsese a gagné la Palme d'or », « quelles séries ont
--     reçu un Emmy ». Elles répondent par des ŒUVRES. L'aplatissement ne s'y voit pas,
--     parce que la question ne demande jamais la LISTE des prix d'une personne.
--   * Aucune ne demande « quels prix a reçus untel ». C'est précisément la forme où
--     la cérémonie, l'œuvre et les collègues remontaient comme des récompenses.
--   * Geste : écrire l'évaluation, avec son assertion.
--
-- CE QUE LES ASSERTIONS PROTÈGENT. Elles portent sur l'INVARIANT et non sur la
-- réponse observée, conformément à la règle de rédaction : « la réponse aux prix
-- d'une personne ne contient jamais la cérémonie, ni l'œuvre, ni un collègue ». Cela
-- vieillit bien, là où une liste de titres serait à maintenir au premier
-- rafraîchissement de la base.
--
-- ⚠ AUCUN ASSERTION_REFRESH_SQL SUR CES DEUX ÉVALUATIONS, ET C'EST DÉLIBÉRÉ. Le
-- README §4.6 documente l'angle mort du mécanisme : un SQL de rafraîchissement doit
-- reproduire l'ORDER BY de la requête évaluée, si bien qu'un défaut DANS cette
-- expression est recalculé à l'identique des deux côtés et certifié en vert. C'est
-- exactement ce qui est arrivé à l'éval 44 le 2026-08-27. Ces deux-ci sont des
-- ancrages permanents : un Oscar est un fait, pas un classement.
--
-- ⚠ COLLATION. Lancer avec --force.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. Avant. Doit rendre zéro ligne ; une ligne ici veut dire que la question
--    existe déjà et que la garde du INSERT fera son office.
-- ---------------------------------------------------------------------------
SELECT '0. Etat avant insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Which awards did Cord Jefferson receive?',
  'Which awards did John Williams receive?'
);

-- ---------------------------------------------------------------------------
-- 1. Le cas témoin de la migration, devenu évaluation.
--
--    Cord Jefferson (Q100146356) porte chez Wikidata UN SEUL P166 : l'Oscar du
--    meilleur scénario adapté, avec trois qualificatifs, l'œuvre American Fiction,
--    l'année, et la 96e cérémonie. La table V1 rendait les trois valeurs comme des
--    prix. L'assertion interdit nommément les deux intrus.
-- ---------------------------------------------------------------------------
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which awards did Cord Jefferson receive?',
       'Quelles récompenses Cord Jefferson a-t-il reçues ?',
       1, 0, 27, 0, CURDATE(), NOW(),
       'COUNT(*) > 0 AND AWARD_NAME NOT LIKE ''%Academy Awards'' AND AWARD_NAME NOT LIKE ''%American Fiction%''',
       'Le témoin de la migration Wikidata V1 vers V2. La table V1 aplatissait sous P166 la récompense, la cérémonie (96th Academy Awards) et l''oeuvre (American Fiction), toutes trois rendues comme des prix. La réponse ne doit contenir que des catégories de prix.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which awards did Cord Jefferson receive?') AS existing);

-- ---------------------------------------------------------------------------
-- 2. Le cas des co-lauréats, la moitié du défaut que le premier ne couvre pas.
--
--    John Williams (Q131285) figurait dans T_WC_T2S_AWARD comme une RÉCOMPENSE,
--    parce que V1 rangeait sous P166 les personnes nommées en qualificatif P1346
--    sur le statement de l'oeuvre. L'assertion interdit qu'un être humain apparaisse
--    dans une liste de prix, ce qui est un invariant et non une liste à maintenir.
-- ---------------------------------------------------------------------------
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Which awards did John Williams receive?',
       'Quelles récompenses John Williams a-t-il reçues ?',
       1, 0, 27, 0, CURDATE(), NOW(),
       'COUNT(*) > 0 AND AWARD_NAME NOT LIKE ''%John Williams%'' AND AWARD_NAME NOT LIKE ''%Steven Spielberg%''',
       'Les co-lauréats. V1 rangeait sous P166 les personnes nommées en qualificatif P1346, si bien que John Williams lui-meme figurait comme une récompense dans T_WC_T2S_AWARD. Une liste de prix ne contient jamais un etre humain.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which awards did John Williams receive?') AS existing);

-- ---------------------------------------------------------------------------
-- 3. Après. Doit rendre les deux lignes, avec leurs assertions.
-- ---------------------------------------------------------------------------
SELECT '3. Etat apres insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 60) AS QUESTION,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Which awards did Cord Jefferson receive?',
  'Which awards did John Williams receive?'
)
ORDER BY ID_T2S_EVALUATION;

-- ---------------------------------------------------------------------------
-- APRÈS IMPORT. Rejouer la phase 11 (les questions n'ont jamais été exécutées)
-- puis la phase 20. Les deux évaluations doivent passer au vert AVEC le prompt
-- corrigé, et seraient passées au ROUGE avec l'ancien : c'est la seule preuve que
-- la correction de -238 tient, et la raison d'être de ce fichier.
-- ---------------------------------------------------------------------------
