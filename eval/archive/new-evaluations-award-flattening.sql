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
-- Le README §4.6 ajoute la raison la plus forte de s'en passer ici : « ne jamais
-- donner un refresh SQL à une évaluation dont l'intérêt est le contre-exemple ». Le
-- rafraîchissement REMPLACE l'assertion entière par un `<ID> IN (...)`, donc il
-- effacerait précisément le NOT IN qui fait tout l'intérêt de ces deux lignes.
--
-- ⚠ LES ASSERTIONS ONT ÉTÉ RÉÉCRITES LE 2026-09-09, AVANT TOUTE APPLICATION, ET LA
-- RAISON MÉRITE D'ÊTRE LUE. La première version employait `AWARD_NAME NOT LIKE
-- '%Academy Awards'`. **`LIKE` n'existe pas dans le DSL d'assertion.** Les formes
-- admises par `evaluate_dataframe_assertions()` sont COUNT(*), COUNT(col),
-- CELL(row,col), IN, NOT IN, et les comparaisons == != < > <= >= (README §4.3,
-- vérifié dans `text2sql_eval_functions.py:163-184`). Une expression `NOT LIKE` ne
-- correspond ni à la branche IN, faute d'un « IN » isolé, ni au motif de comparaison,
-- faute d'un opérateur reconnu : elle tombe dans `_evaluate_comparison_assertion`,
-- rend « Invalid comparison syntax » et vaut False.
--
-- Les deux évaluations auraient donc scoré **0 quoi qu'il arrive**, avec le prompt
-- corrigé comme avec l'ancien. C'est le pire résultat possible pour ce fichier : il
-- aurait affiché en rouge la correction qu'il était censé prouver, et rien n'aurait
-- distingué cet échec d'un vrai. Une assertion qui ne peut pas passer est pire que
-- pas d'assertion du tout, car elle a l'air de mesurer quelque chose.
--
-- Les deux formes retenues à la place, `COUNT(*) > 0 AND <col> NOT IN (...)`, sont
-- exactement le « niveau 3, le contre-exemple » du README §4.5, qu'il décrit comme le
-- niveau absent de toute la banque. Elles nomment les intrus au lieu de les décrire
-- par motif, ce qui est plus étroit mais réellement évaluable.
--
-- ⚠ LA SECTION 1 EXISTE POUR ÇA : lire les valeurs réelles de AWARD_NAME AVANT
-- d'insérer, et corriger les listes du NOT IN si les libellés diffèrent. Un
-- contre-exemple qui nomme une chaîne absente de la base ne protège de rien.
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
-- 1. CE QUE LA BASE CONTIENT AUJOURD'HUI POUR LES DEUX TÉMOINS.
--
--    À lire AVANT d'insérer. Deux choses à y vérifier :
--      a) les récompenses rendues sont bien des récompenses, ce qui confirme que la
--         correction amont (TMDB-MOVIE-PREPROCESS-039) a bien nettoyé T2S_AWARD ;
--      b) les libellés exacts, pour que les NOT IN ci-dessous nomment des chaînes qui
--         existent vraiment. Si « 96th Academy Awards » ou « American Fiction »
--         n'apparaissent nulle part, le contre-exemple ne protège de rien et il faut
--         le remplacer par ce que la mesure montre.
--
--    Ces lignes NE DOIVENT PLUS contenir de cérémonie, d'œuvre ni de collègue : c'est
--    le défaut que -039 a corrigé en amont et que -238 empêche le modèle de rejouer.
-- ---------------------------------------------------------------------------
SELECT '1. Recompenses en base pour les deux temoins' AS SECTION;

SELECT p.PERSON_NAME, a.AWARD_NAME, a.AWARD_NAME_FR, COUNT(*) AS OCCURRENCES
FROM T_WC_T2S_PERSON p
JOIN T_WC_T2S_PERSON_AWARD pa ON pa.ID_PERSON = p.ID_PERSON
JOIN T_WC_T2S_AWARD a ON a.ID_AWARD = pa.ID_AWARD
WHERE p.PERSON_NAME IN ('Cord Jefferson', 'John Williams')
GROUP BY p.PERSON_NAME, a.AWARD_NAME, a.AWARD_NAME_FR
ORDER BY p.PERSON_NAME, a.AWARD_NAME;

-- ---------------------------------------------------------------------------
-- 2. Le cas témoin de la migration, devenu évaluation.
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
       'COUNT(*) > 0 AND AWARD_NAME NOT IN (''96th Academy Awards'', ''American Fiction'')',
       'Le témoin de la migration Wikidata V1 vers V2. La table V1 aplatissait sous P166 la récompense, la cérémonie (96th Academy Awards) et l''oeuvre (American Fiction), toutes trois rendues comme des prix. La réponse ne doit contenir que des catégories de prix.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which awards did Cord Jefferson receive?') AS existing);

-- ---------------------------------------------------------------------------
-- 3. Le cas des co-lauréats, la moitié du défaut que le premier ne couvre pas.
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
       'COUNT(*) > 0 AND AWARD_NAME NOT IN (''John Williams'', ''Steven Spielberg'')',
       'Les co-lauréats. V1 rangeait sous P166 les personnes nommées en qualificatif P1346, si bien que John Williams lui-meme figurait comme une récompense dans T_WC_T2S_AWARD. Une liste de prix ne contient jamais un etre humain.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Which awards did John Williams receive?') AS existing);

-- ---------------------------------------------------------------------------
-- 4. Après. Doit rendre les deux lignes, avec leurs assertions, et une colonne
--    ASSERTION_REFRESH_SQL vide sur les deux : voir l'avertissement en tête.
-- ---------------------------------------------------------------------------
SELECT '4. Etat apres insertion' AS SECTION;

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
--
-- ⚠ SI LA PHASE 20 REND ROUGE, LIRE LE MESSAGE AVANT DE CONCLURE. Trois causes très
-- différentes se ressemblent dans la colonne de score :
--
--   1. « Column 'AWARD_NAME' does not exist in DataFrame ». Le message liste alors
--      les colonnes réellement rendues. Le modèle a nommé la colonne autrement, par
--      exemple dans la forme unifiée ID_CONTENT / CONTENT_TYPE du prompt. Ce n'est
--      PAS un échec de -238 : corriger le nom dans l'assertion et rejouer la phase 20
--      seule, qui est du scoring hors ligne et ne redépense aucun jeton.
--   2. Un contre-exemple qui remonte vraiment, « 96th Academy Awards » par exemple.
--      Là c'est le vrai signal, et il dit que le modèle lit encore la table plate.
--   3. COUNT(*) > 0 en échec : la question ne rend rien, ce qui est un défaut de
--      résolution d'entité et non d'aplatissement.
--
-- Cette relecture est le prix des assertions étroites. Elle est plus courte que la
-- confusion qu'aurait produite une assertion inévaluable.
-- ---------------------------------------------------------------------------
