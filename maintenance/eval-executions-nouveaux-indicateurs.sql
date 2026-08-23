-- Ajoute a T_WC_T2S_EVALUATION_EXECUTION les cinq indicateurs que l'API rend deja,
-- ou va rendre, et qui n'avaient pas de colonne.
--
-- POURQUOI CE FICHIER
-- La chaine de mesure est deja generique : l'evaluateur stocke la reponse HTTP entiere
-- dans JSON_RESULT, et l'export vers /shared recopie ce JSON tel quel sous api_output.
-- Un champ ajoute a Text2SQLResponse arrive donc en base et dans l'export sans qu'on
-- touche a quoi que ce soit. Les colonnes ci-dessous sont un DOUBLON volontaire de cinq
-- de ces champs, pour qu'une campagne se decoupe en SQL sans JSON_EXTRACT sur chaque
-- ligne, ce dont se servent les graphes PHP de eval/lib/.
--
-- CE QUE CHAQUE COLONNE PORTE
-- RESULT_ENTITY_PROCESSING_TIME    le classificateur d'entite de reponse, chronometre
--                                  depuis le 2026-08-21 et rendu par l'API depuis, mais
--                                  jamais colonne.
-- EMBEDDINGS_CACHE_SEARCH_TIME     la recherche dans le cache de questions anonymisees.
--                                  Meme situation.
-- ENTITY_RESOLUTION_PLANNING_TIME  la part de la resolution d'entites recouverte par
--                                  l'appel text2sql (FASTAPI-TEXT2SQL-201). ATTENTION :
--                                  cette valeur est deja COMPRISE dans
--                                  EMBEDDINGS_PROCESSING_TIME, qui la reincorpore pour
--                                  rester comparable aux campagnes anterieures au
--                                  fork-join. Ne jamais additionner les deux.
-- ENTITY_RAW_FALLBACK_COUNT        nombre d'entites dont aucun resolveur configure n'a
--                                  abouti, donc dont les mots bruts ont ete substitues
--                                  dans le SQL (FASTAPI-TEXT2SQL-156).
-- NO_ENTITY_EXTRACTED              1 quand l'extraction n'a rien trouve du tout, donc que
--                                  la question n'a jamais ete anonymisee. Stocke en int(5)
--                                  comme les autres drapeaux de ce schema (DELETED).
--
-- Les deux dernieres sont les signaux qui decident de la reprise par le modele complexe
-- sur resultat vide. Les avoir en colonnes permet de mesurer l'effet du correctif -156
-- par une requete plutot qu'en relisant les journaux avec
-- analyze-complex-retry-logs.py.
--
-- NON VERIFIE
-- Rien ici n'a ete execute : la base n'est pas joignable depuis le poste de developpement.
-- Le fichier est valide syntaxiquement, pas par un passage reel. Le DDL de reference
-- doc/sql/T2S_EVALUATION-tables.sql a ete mis a jour en meme temps ; les deux doivent
-- rester d'accord.
--
-- IDEMPOTENT
-- MariaDB ne connait pas ADD COLUMN IF NOT EXISTS sur toutes les versions, donc la
-- section 1 verifie d'abord. Ne lancer la section 2 que sur les colonnes absentes.

-- ===== 1. Constat, a lire avant d'ecrire =====

-- Quelles colonnes existent deja ? (0 ligne = tout est a ajouter)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN (
    'RESULT_ENTITY_PROCESSING_TIME',
    'EMBEDDINGS_CACHE_SEARCH_TIME',
    'ENTITY_RESOLUTION_PLANNING_TIME',
    'ENTITY_RAW_FALLBACK_COUNT',
    'NO_ENTITY_EXTRACTED'
  )
ORDER BY COLUMN_NAME;

-- Combien de lignes sont concernees, pour mesurer le cout de l'ALTER.
SELECT COUNT(*) AS lignes_existantes FROM T_WC_T2S_EVALUATION_EXECUTION;


-- ===== 2. Ajout des colonnes =====
-- Aucune sauvegarde prealable n'est requise : un ADD COLUMN ne touche aucune donnee
-- existante et se defait par le DROP COLUMN de la section 3.

ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD COLUMN `RESULT_ENTITY_PROCESSING_TIME` double DEFAULT NULL AFTER `TOTAL_PROCESSING_TIME`,
  ADD COLUMN `EMBEDDINGS_CACHE_SEARCH_TIME` double DEFAULT NULL AFTER `RESULT_ENTITY_PROCESSING_TIME`,
  ADD COLUMN `ENTITY_RESOLUTION_PLANNING_TIME` double DEFAULT NULL AFTER `EMBEDDINGS_CACHE_SEARCH_TIME`,
  ADD COLUMN `ENTITY_RAW_FALLBACK_COUNT` int(5) DEFAULT NULL AFTER `ENTITY_RESOLUTION_PLANNING_TIME`,
  ADD COLUMN `NO_ENTITY_EXTRACTED` int(5) DEFAULT NULL AFTER `ENTITY_RAW_FALLBACK_COUNT`;

-- Les lignes anterieures gardent NULL, et c'est voulu : NULL dit "cette campagne n'a pas
-- mesure cet indicateur", ce que 0 confondrait avec "mesure a zero". Les moyennes doivent
-- donc etre calculees sur les lignes non nulles.


-- ===== 3. Retour arriere =====
-- ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
--   DROP COLUMN `RESULT_ENTITY_PROCESSING_TIME`,
--   DROP COLUMN `EMBEDDINGS_CACHE_SEARCH_TIME`,
--   DROP COLUMN `ENTITY_RESOLUTION_PLANNING_TIME`,
--   DROP COLUMN `ENTITY_RAW_FALLBACK_COUNT`,
--   DROP COLUMN `NO_ENTITY_EXTRACTED`;


-- ===== 4. Verification apres coup, une fois une campagne relancee =====

-- Les nouvelles colonnes se remplissent-elles ? (attendu : non nul a partir de la
-- premiere campagne lancee apres le redeploiement de l'API)
-- SELECT API_VERSION,
--        COUNT(*)                                   AS lignes,
--        COUNT(RESULT_ENTITY_PROCESSING_TIME)       AS avec_classificateur,
--        COUNT(ENTITY_RESOLUTION_PLANNING_TIME)     AS avec_recouvrement,
--        ROUND(AVG(ENTITY_RESOLUTION_PLANNING_TIME), 3) AS recouvrement_moyen,
--        SUM(ENTITY_RAW_FALLBACK_COUNT > 0)         AS avec_repli_brut,
--        SUM(NO_ENTITY_EXTRACTED = 1)               AS sans_entite
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0
-- GROUP BY API_VERSION
-- ORDER BY API_VERSION;
