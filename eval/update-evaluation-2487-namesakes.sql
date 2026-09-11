-- ============================================================================
-- 2487, John Williams : le contre-exemple, parce qu'un compte ne suffit pas
-- ============================================================================
--
-- NON ENCORE APPLIQUÉ. Troisième et dernier volet de FASTAPI-TEXT2SQL-238, après
-- new-evaluations-award-flattening.sql (l'insertion) et
-- update-evaluations-award-flattening.sql (le durcissement de 2486).
--
-- ⚠ CE FICHIER A CHANGÉ D'AVIS DEUX FOIS, ET LA TROISIÈME VERSION EST LA SEULE
-- MESURÉE. Le trajet vaut d'être écrit, parce que chaque étape semblait solide.
--
--   1er état, le 2026-09-10 : « le plancher de 2487 ne bouge pas ». Fondé sur une
--     requête de mesure fausse, qui groupait sur PERSON_NAME et fondait donc tous les
--     hommes de ce nom en une ligne de 21 récompenses. Calibrer sur cet agrégat aurait
--     rougi une réponse correcte.
--   2e état, le même jour : « COUNT(*) > 5 », une fois le compte fait par personne.
--     Six John Williams en base, trois avec des récompenses, 16 pour le compositeur
--     Q131285, 2 pour un acteur Q921945, 2 pour un écrivain Q2077062. L'écart 16 contre
--     2 paraissait franc, et le plancher devait vérifier que l'API avait résolu vers le
--     bon homme.
--   3e état, celui-ci, après la recette du 2026-09-11 : **le plancher n'aurait rien
--     vu**. La campagne a rendu VINGT récompenses, parce que le SQL généré filtre sur
--     WHERE T_WC_T2S_PERSON.PERSON_NAME = 'John Williams' et fusionne les trois hommes,
--     16 + 2 + 2. Or 20 est supérieur à 5. L'évaluation serait passée au vert sur une
--     réponse qui mélange un Oscar de la meilleure musique et un Tony du meilleur
--     second rôle.
--
-- LA LEÇON, et elle dépasse ce fichier : **un plancher chiffré ne voit pas une réponse
-- TROP LARGE tant que le compte reste plausible.** Il n'attrape que la réponse trop
-- étroite. Seul le contre-exemple, le « niveau 3 » du README §4.5, attrape une requête
-- qui ratisse plus large que la question.
--
-- LES CONTRE-EXEMPLES RETENUS sont pris chez les homonymes, et c'est ce qui les rend
-- décisifs : le National Book Award appartient à l'écrivain, le Tony du meilleur second
-- rôle à l'acteur. **Aucun des deux ne peut appartenir au compositeur.** Leur présence
-- dans la réponse signe la fusion, sans ambiguïté et sans avoir à compter.
--
-- Les deux contre-exemples d'origine restent, « John Williams » et « Steven Spielberg »,
-- qui gardent le rôle pour lequel cette évaluation a été écrite : une liste de prix ne
-- contient jamais un être humain.
--
-- POURQUOI DES NOMS ET NON UN ANCRAGE POSITIF. J'avais essayé
-- AWARD_NAME IN ('Academy Award for Best Original Score'), qui discrimine aussi. Défaut
-- rédhibitoire : la phase 11 exécute chaque évaluation dans les DEUX langues avec la
-- MÊME assertion, et la réponse française rend « Oscar de la meilleure musique de film ».
-- L'ancrage serait rouge en français sur une réponse juste. Les quatre valeurs
-- ci-dessous sont des noms propres ou des titres de prix anglophones non traduits dans
-- la base, donc stables dans les deux langues.
--
-- CETTE ÉVALUATION DEVIENT LE DÉTECTEUR PERMANENT DE FASTAPI-TEXT2SQL-248, le défaut de
-- résolution qu'elle vient de révéler. Elle ne le corrige pas, elle le rend visible.
--
-- ⚠ COLLATION. Lancer avec --force.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '1. Avant' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2487;

-- ---------------------------------------------------------------------------
-- 2. Le contre-exemple étendu aux homonymes
--
--    Vérifié contre l'évaluateur réel avant d'être écrit ici :
--      le compositeur seul (16 prix) ............ VERT
--      la fusion des trois (20 prix) ............ ROUGE, nomme les deux intrus
--      résultat vide ............................ ROUGE
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT =
      'COUNT(*) > 0 AND AWARD_NAME NOT IN (''John Williams'', ''Steven Spielberg'', ''National Book Award'', ''Tony Award for Best Featured Actor in a Play'')',
    LONG_DESC = CONCAT(LONG_DESC,
      ' Mesure du 2026-09-10 : six personnes portent ce nom en base, dont trois ont '
      'des recompenses, 16 pour le compositeur Q131285, 2 pour un acteur Q921945 et '
      '2 pour un ecrivain Q2077062. La campagne du 2026-09-11 a rendu les VINGT, le SQL '
      'genere filtrant sur PERSON_NAME : la reponse melange trois hommes, voir '
      'FASTAPI-TEXT2SQL-248. Deux contre-exemples sont donc ajoutes, pris chez les '
      'homonymes, qui font de cette evaluation le detecteur permanent de ce defaut. Des '
      'noms propres et non un plancher chiffre, parce qu''un compte ne voit pas une '
      'reponse trop large tant qu''il reste plausible, et parce que la phase 11 evalue '
      'les deux langues avec la meme assertion.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2487;

-- ---------------------------------------------------------------------------
-- 3. Après. Les deux évaluations du ticket, dans leur forme définitive.
--
--    ⚠ Une différence d'apparence sans conséquence : 2486 et 2487 s'affichent l'une en
--    texte brut, l'autre avec des entités HTML (&gt;, &#039;). Les deux formes
--    fonctionnent, le harnais passe la chaîne par html.unescape() avant de la lire
--    (README §4). Vérifié contre l'évaluateur : la forme échappée rend « Invalid
--    COUNT(*) syntax » lue telle quelle, et le bon verdict une fois déséchappée, ce que
--    le harnais fait toujours.
-- ---------------------------------------------------------------------------
SELECT '3. Etat final des deux evaluations' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (2486, 2487)
ORDER BY ID_T2S_EVALUATION;

-- ============================================================================
-- APRÈS. Rejouer la phase 20 suffit : c'est du scoring hors ligne sur la réponse déjà
-- stockée, aucun jeton dépensé. 2487 doit passer au ROUGE, et ce rouge est le résultat
-- attendu : il mesure FASTAPI-TEXT2SQL-248, qui n'est pas encore corrigé.
--
-- ⚠ UN ROUGE ATTENDU N'EST PAS UN ROUGE ACCEPTÉ. Tant que -248 vit, cette évaluation
-- reste rouge, et il faut que le ticket porte cette dette plutôt que l'assertion. La
-- tentation inverse, adoucir l'assertion pour retrouver le vert, rendrait le défaut
-- invisible exactement comme il l'était avant le 2026-09-11.
--
-- CE QUE CHAQUE ROUGE VOUDRA DIRE ENSUITE :
--   2486, COUNT(*) == 1 en échec avec 3 lignes : l'aplatissement est revenu.
--   2486, une seule ligne mais un contre-exemple qui remonte : le modèle lit encore la
--         table plate par un autre chemin.
--   2487, un contre-exemple d'homonyme qui remonte : -248 n'est pas corrigé.
--   L'un ou l'autre, « Column 'AWARD_NAME' does not exist » : le modèle a nommé la
--         colonne autrement, rien à voir avec -238.
-- ============================================================================
