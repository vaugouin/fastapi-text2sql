-- Ajoute COMPLEX_QUESTION_PROCESSING_TIME a T_WC_T2S_EVALUATION_EXECUTION.
--
-- SUITE DE eval-executions-nouveaux-indicateurs.sql, deja execute le 2026-08-23. Fichier
-- separe plutot qu'ajout a celui-la : le precedent est passe, le rejouer ferait echouer
-- ses cinq ALTER sur des colonnes desormais existantes. Chaque migration reste ainsi
-- rejouable pour elle-meme.
--
-- POURQUOI CETTE COLONNE (FASTAPI-TEXT2SQL-204)
-- L'appel de simplification qui precede une reprise par le modele complexe n'etait
-- chronometre nulle part. Ce n'etait sans consequence que tant que la reprise ne se
-- declenchait jamais : zero reprise sur 231 resultats vides en 1.1.17 et 1.1.18. Le
-- correctif -156, deploye le 2026-08-23, l'a ramenee a la vie.
--
-- Mesure sur la premiere reprise observee ensuite : 26,76 s au client contre un
-- total_processing_time annonce de 10,54 s, soit 60 % du cout reel manquant. Trois causes,
-- toutes corrigees dans le meme commit : l'appel de simplification non chronometre, les
-- chronometres du premier passage jetes au profit du second, et l'ecriture en cache qui
-- heritait du defaut.
--
-- CE QUE LA COLONNE PORTE
-- Le temps de l'appel de simplification seul. Elle vaut 0 quand aucune reprise n'a eu lieu,
-- ce qui en fait le filtre le plus direct pour isoler les lignes reprises, plus sur que
-- COMPLEX_MODEL_USED qui vit dans le JSON.
--
-- A SAVOIR EN LISANT LES AUTRES COLONNES
-- Sur une ligne reprise, toutes les autres durees couvrent DESORMAIS les deux passages :
-- l'endpoint tourne deux fois et les durees s'additionnent. TOTAL_PROCESSING_TIME est le
-- temps reel de bout en bout, donc superieur a la somme des etapes, qui ignore la plomberie
-- entre elles. Les lignes ecrites AVANT ce correctif ne portent que le second passage et
-- sous-estiment donc leur cout : les comparer aux nouvelles n'a pas de sens sur une
-- population reprise. ENTITY_RAW_FALLBACK_COUNT et NO_ENTITY_EXTRACTED, eux, ne sont pas
-- additionnes et decrivent la resolution qui a produit le resultat rendu.
--
-- NON VERIFIE
-- Rien ici n'a ete execute : la base n'est pas joignable depuis le poste de developpement.
-- Valide syntaxiquement, pas par un passage reel. Le DDL de reference
-- doc/sql/T2S_EVALUATION-tables.sql a ete mis a jour en meme temps ; les deux doivent rester
-- d'accord.

-- ===== 1. Constat, a lire avant d'ecrire =====

-- La colonne existe-t-elle deja ? (0 ligne = a ajouter)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME = 'COMPLEX_QUESTION_PROCESSING_TIME';

-- Les cinq colonnes de la migration precedente sont-elles bien la ? (5 lignes attendues)
SELECT COUNT(*) AS colonnes_precedentes
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN (
    'RESULT_ENTITY_PROCESSING_TIME',
    'EMBEDDINGS_CACHE_SEARCH_TIME',
    'ENTITY_RESOLUTION_PLANNING_TIME',
    'ENTITY_RAW_FALLBACK_COUNT',
    'NO_ENTITY_EXTRACTED'
  );


-- ===== 2. Ajout de la colonne =====
-- Aucune sauvegarde prealable requise : un ADD COLUMN ne touche aucune donnee existante et
-- se defait par le DROP COLUMN de la section 3.

ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD COLUMN `COMPLEX_QUESTION_PROCESSING_TIME` double DEFAULT NULL AFTER `NO_ENTITY_EXTRACTED`;

-- Les lignes anterieures gardent NULL, et c'est voulu : NULL dit "cette campagne ne mesurait
-- pas cet indicateur", ce que 0 confondrait avec "aucune reprise n'a eu lieu", qui est
-- justement la valeur signifiante de cette colonne.


-- ===== 3. Retour arriere =====
-- ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
--   DROP COLUMN `COMPLEX_QUESTION_PROCESSING_TIME`;


-- ===== 4. Verification apres coup, une fois une campagne relancee =====

-- Combien de lignes ont ete reprises, et ce que la reprise coute vraiment.
-- SELECT API_VERSION,
--        COUNT(*)                                            AS lignes,
--        SUM(COMPLEX_QUESTION_PROCESSING_TIME > 0)           AS reprises,
--        ROUND(AVG(COMPLEX_QUESTION_PROCESSING_TIME), 3)     AS simplification_moyenne,
--        ROUND(AVG(CASE WHEN COMPLEX_QUESTION_PROCESSING_TIME > 0
--                       THEN TOTAL_PROCESSING_TIME END), 2)  AS total_moyen_avec_reprise,
--        ROUND(AVG(CASE WHEN COMPLEX_QUESTION_PROCESSING_TIME = 0
--                       THEN TOTAL_PROCESSING_TIME END), 2)  AS total_moyen_sans_reprise
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0
--   AND COMPLEX_QUESTION_PROCESSING_TIME IS NOT NULL
-- GROUP BY API_VERSION
-- ORDER BY API_VERSION;
