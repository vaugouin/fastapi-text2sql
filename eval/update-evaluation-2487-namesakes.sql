-- ============================================================================
-- 2487, John Williams : l'homonymie devient le discriminant au lieu du piège
-- ============================================================================
--
-- NON ENCORE APPLIQUÉ. Troisième et dernier volet de FASTAPI-TEXT2SQL-238, après
-- new-evaluations-award-flattening.sql (l'insertion) et
-- update-evaluations-award-flattening.sql (le durcissement de 2486).
--
-- ⚠ CE FICHIER REVIENT SUR LA DÉCISION DU FICHIER PRÉCÉDENT, qui écrivait « le
-- plancher de 2487 ne bouge pas ». Il avait raison sur les données dont il
-- disposait et tort sur celles-ci, et la différence mérite d'être dite, parce que
-- c'est la même mesure qui a produit les deux conclusions.
--
-- CE QUE LA SECTION 3 A RENDU, le 2026-09-10. Six personnes nommées John Williams
-- dans T_WC_T2S_PERSON, dont trois portent des récompenses :
--
--   ID_PERSON  QID          PRIX  QUI
--   491        Q131285      16    le compositeur (Oscars, Grammy, Emmy, Kennedy)
--   5182       Q921945      2     un acteur (Tony, Donaldson, prix de théâtre)
--   3966235    Q2077062     2     un écrivain (Guggenheim, National Book Award)
--   195752 / 1134531 / 1245482     0
--
-- Le fichier précédent refusait un plancher chiffré parce que ma mesure avait fondu
-- ces gens en une seule ligne de 21 récompenses : calibrer sur un agrégat
-- d'homonymes aurait rougi une réponse correcte. L'argument tombe dès que le compte
-- est par personne. **16 contre 2, l'écart est franc**, et un plancher posé entre
-- les deux ne se contente plus de constater qu'il y a des lignes : il vérifie que
-- l'API a résolu la question vers le BON John Williams.
--
-- CE QUE L'ASSERTION ACTUELLE NE VOIT PAS, vérifié contre l'évaluateur :
-- `COUNT(*) > 0` passe au vert sur le compositeur, sur l'acteur ET sur l'écrivain.
-- Une erreur de résolution d'entité y est donc parfaitement invisible. Avec le
-- plancher à 5, seul le compositeur passe.
--
-- ⚠ POURQUOI UN COMPTE ET NON UN ANCRAGE PAR LE NOM D'UN PRIX. J'ai d'abord essayé
-- `AWARD_NAME IN ('Academy Award for Best Original Score')`, qui discrimine tout
-- aussi bien. Il a un défaut rédhibitoire ici : **la phase 11 exécute chaque
-- évaluation dans les deux langues avec la MÊME assertion**, et la réponse française
-- rend « Oscar de la meilleure musique de film ». L'ancrage serait rouge en français
-- sur une réponse juste. C'est la raison de fond pour laquelle la banque préfère les
-- colonnes d'identifiant aux libellés. Un compte de lignes, lui, ne parle aucune
-- langue.
--
-- Les deux contre-exemples restent : « John Williams » et « Steven Spielberg » sont
-- des noms propres, identiques dans les deux langues.
--
-- LA MARGE. 16 mesurés, seuil à 5, et les homonymes plafonnent à 2. N'importe quel
-- seuil de 3 à 15 discriminerait ; 5 laisse le compositeur perdre les deux tiers de
-- ses prix avant de rougir à tort, et l'acteur en gagner deux avant de passer à
-- tort. C'est le point le plus stable de l'intervalle.
--
-- ⚠ COLLATION. Lancer avec --force.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '1. Avant' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2487;

-- ---------------------------------------------------------------------------
-- 2. Le plancher, recalibré sur la personne et non sur l'agrégat
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT =
      'COUNT(*) > 5 AND AWARD_NAME NOT IN (''John Williams'', ''Steven Spielberg'')',
    LONG_DESC = CONCAT(LONG_DESC,
      ' Mesure du 2026-09-10 : six personnes portent ce nom en base, dont trois ont '
      'des recompenses, 16 pour le compositeur Q131285, 2 pour un acteur Q921945 et '
      '2 pour un ecrivain Q2077062. Le plancher passe de 0 a 5, ce qui fait de cette '
      'evaluation un detecteur de mauvaise resolution d''entite en plus de son role '
      'd''origine : COUNT(*) > 0 passait au vert sur les trois. Un compte plutot qu''un '
      'nom de prix, parce que la phase 11 evalue les deux langues avec la meme '
      'assertion et que la reponse francaise rend "Oscar de la meilleure musique de film".'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2487;

-- ---------------------------------------------------------------------------
-- 3. Après. Les deux évaluations du ticket, dans leur forme définitive.
--
--    ⚠ Une différence d'apparence sans conséquence : 2486 et 2487 s'affichent
--    l'une en texte brut, l'autre avec des entités HTML (&gt;, &#039;). Les deux
--    formes fonctionnent, le harnais passe la chaîne par html.unescape() avant de
--    la lire (README §4). Vérifié contre l'évaluateur : la forme échappée rend
--    « Invalid COUNT(*) syntax » si on la lit telle quelle, et le bon verdict une
--    fois déséchappée, ce que le harnais fait toujours.
-- ---------------------------------------------------------------------------
SELECT '3. Etat final des deux evaluations' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (2486, 2487)
ORDER BY ID_T2S_EVALUATION;

-- ============================================================================
-- APRÈS. Déployer, puis rejouer la phase 11 et la phase 20 sur les deux.
--
-- CE QUE CHAQUE ROUGE VOUDRAIT DIRE, maintenant que les assertions discriminent :
--
--   2486, COUNT(*) == 1 en échec avec 3 lignes : l'aplatissement est revenu, c'est
--         le signal que ce ticket existe pour donner.
--   2486, une seule ligne mais un contre-exemple qui remonte : le modèle lit encore
--         la table plate par un autre chemin.
--   2487, COUNT(*) > 5 en échec avec 2 lignes : l'API a résolu vers l'acteur ou
--         l'écrivain. Ce n'est PAS un défaut d'aplatissement, c'est un défaut de
--         résolution d'entité, et il mérite alors son propre ticket. La mesure
--         ci-dessus donne déjà les six identifiants pour l'instruire.
--   L'un ou l'autre, « Column 'AWARD_NAME' does not exist » : le modèle a nommé la
--         colonne autrement, rien à voir avec -238. Corriger l'assertion et rejouer
--         la seule phase 20, qui est du scoring hors ligne et ne coûte aucun jeton.
-- ============================================================================
