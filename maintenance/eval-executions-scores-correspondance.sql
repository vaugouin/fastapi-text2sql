-- Ajoute les deux scores de correspondance a T_WC_T2S_EVALUATION_EXECUTION.
--
--   ENTITY_MATCH_WORST_DISTANCE    distance embeddings du pire match ACCEPTE de la requete
--   ENTITY_MATCH_WORST_FUZZ_RATIO  fuzz.ratio du pire match ACCEPTE de la requete
--
-- TROISIEME MIGRATION DE LA SERIE, fichier separe des deux precedentes
-- eval-executions-nouveaux-indicateurs.sql et eval-executions-chronometre-complexe.sql sont
-- deja passees le 2026-08-23 ; les rejouer echouerait sur des colonnes existantes. Chaque
-- migration reste rejouable pour elle-meme.
--
-- POURQUOI CES COLONNES (FASTAPI-TEXT2SQL-206)
-- Sur les quatorze resolveurs de data/entity_resolution.json, un seul porte un seuil de rejet :
-- Collection_name, avec min_fuzz_ratio = 72. Les treize autres n'ont ni max_distance ni
-- min_fuzz_ratio, donc la recherche par embeddings accepte toujours son plus proche voisin,
-- aussi lointain soit-il. Mesure du 2026-08-24 : "Wagonlit collection" a resolu vers
-- "Life Collection", et "Collection Bibendum" n'a ete rejete que parce que Collection_name est
-- justement le seul type protege (distance 1.042, fuzz_ratio 54).
--
-- On ne peut pas choisir un seuil sans connaitre la distribution des distances, et rien ne
-- l'enregistrait : le code ne calculait la distance QUE lorsqu'un seuil etait configure, donc
-- jamais pour les treize types qui en manquent. La mesure est desormais systematique.
--
-- POURQUOI LE PIRE ET NON LA MOYENNE
-- Une requete resout souvent plusieurs entites. Un seuil coupe la plus faible, pas la moyenne :
-- c'est donc le pire match accepte qui dit si la requete aurait survecu a un seuil donne. Les
-- rejets sont exclus du calcul, ayant deja ete refuses. Le detail par entite vit dans
-- entity_match_scores, present dans JSON_RESULT et dans api_output de l'export.
--
-- SENS DES DEUX ECHELLES, A NE PAS CONFONDRE
-- La distance est une DISSIMILARITE : plus elle est grande, plus le candidat est loin, et un
-- seuil s'ecrit "distance <= max_distance". Le ratio est une SIMILARITE sur 100 : plus il est
-- grand, plus le candidat est proche, et le seuil s'ecrit "ratio >= min_fuzz_ratio". Les deux
-- colonnes portent donc le PIRE dans des directions opposees, la plus grande distance et le
-- plus petit ratio.
--
-- NULL VEUT DIRE QUELQUE CHOSE
-- NULL signifie qu'aucune entite de la requete n'est passee par un resolveur mesure : question
-- sans entite, ou entites traitees par vocabulaire ferme ou par regex, qui ne produisent pas de
-- score. A distinguer d'un 0, qui serait un vrai match parfaitement mauvais.
--
-- NON VERIFIE
-- Rien ici n'a ete execute : la base n'est pas joignable depuis le poste de developpement.
-- Valide syntaxiquement, pas par un passage reel. Le DDL de reference
-- doc/sql/T2S_EVALUATION-tables.sql a ete mis a jour en meme temps ; les deux doivent rester
-- d'accord.

-- ===== 1. Constat, a lire avant d'ecrire =====

-- Les colonnes existent-elles deja ? (0 ligne = a ajouter)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN ('ENTITY_MATCH_WORST_DISTANCE', 'ENTITY_MATCH_WORST_FUZZ_RATIO');

-- Les six colonnes des deux migrations precedentes sont-elles bien la ? (6 lignes attendues)
SELECT COUNT(*) AS colonnes_precedentes
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN (
    'RESULT_ENTITY_PROCESSING_TIME',
    'EMBEDDINGS_CACHE_SEARCH_TIME',
    'ENTITY_RESOLUTION_PLANNING_TIME',
    'ENTITY_RAW_FALLBACK_COUNT',
    'NO_ENTITY_EXTRACTED',
    'COMPLEX_QUESTION_PROCESSING_TIME'
  );


-- ===== 2. Ajout des colonnes et de leurs index =====
-- Aucune sauvegarde prealable requise : un ADD COLUMN ne touche aucune donnee existante et se
-- defait par le DROP COLUMN de la section 3.

ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD COLUMN `ENTITY_MATCH_WORST_DISTANCE`   double DEFAULT NULL AFTER `COMPLEX_QUESTION_PROCESSING_TIME`,
  ADD COLUMN `ENTITY_MATCH_WORST_FUZZ_RATIO` double DEFAULT NULL AFTER `ENTITY_MATCH_WORST_DISTANCE`;

-- Les index servent la calibration elle-meme, qui trie et filtre sur ces deux colonnes.
ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD INDEX `ENTITY_MATCH_WORST_DISTANCE`   (`ENTITY_MATCH_WORST_DISTANCE`),
  ADD INDEX `ENTITY_MATCH_WORST_FUZZ_RATIO` (`ENTITY_MATCH_WORST_FUZZ_RATIO`);

-- Les lignes anterieures gardent NULL, et c'est voulu : elles datent de campagnes qui ne
-- mesuraient pas, ce qu'un 0 confondrait avec un match parfaitement mauvais.


-- ===== 3. Retour arriere =====
-- ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
--   DROP COLUMN `ENTITY_MATCH_WORST_DISTANCE`,
--   DROP COLUMN `ENTITY_MATCH_WORST_FUZZ_RATIO`;


-- ===== 4. La calibration, une fois une campagne relancee =====

-- Distribution du pire ratio accepte, croisee avec la reussite des assertions. C'est la lecture
-- qui designe le seuil : le point ou les lignes en echec se concentrent sans emporter celles qui
-- reussissent. Un seuil pose au-dessus de ce point coupe surtout du faux.
-- SELECT FLOOR(ENTITY_MATCH_WORST_FUZZ_RATIO / 10) * 10 AS tranche_ratio,
--        COUNT(*)                                       AS lignes,
--        SUM(ASSERTIONS_TOTAL_SCORE = 1)                AS reussites,
--        SUM(ASSERTIONS_TOTAL_SCORE = 0)                AS echecs
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0
--   AND ENTITY_MATCH_WORST_FUZZ_RATIO IS NOT NULL
-- GROUP BY tranche_ratio
-- ORDER BY tranche_ratio;

-- Meme lecture sur la distance, en sens inverse : ce sont les GRANDES valeurs qui sont suspectes.
-- SELECT ROUND(ENTITY_MATCH_WORST_DISTANCE, 1) AS tranche_distance,
--        COUNT(*)                              AS lignes,
--        SUM(ASSERTIONS_TOTAL_SCORE = 1)       AS reussites,
--        SUM(ASSERTIONS_TOTAL_SCORE = 0)       AS echecs
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0
--   AND ENTITY_MATCH_WORST_DISTANCE IS NOT NULL
-- GROUP BY tranche_distance
-- ORDER BY tranche_distance;

-- ATTENTION : ces deux requetes ne voient que les correspondances ACCEPTEES, puisque le seuil
-- n'existe pas encore et que rien n'est rejete. Elles donnent donc la classe positive et rien
-- d'autre. La classe negative doit etre fabriquee, ce que fait eval/bench-entity-resolution.py.
