-- Cree la table du cache de reconnaissance d'image, T_WC_T2S_VISION_CACHE
-- (FASTAPI-TEXT2SQL-114, point 9).
--
-- POURQUOI UNE TABLE DE PLUS, ET PAS UNE COLONNE SUR T_WC_T2S_CACHE
-- Le contrat de T_WC_T2S_CACHE est question -> SQL. Sa cle est QUESTION ou QUESTION_HASHED,
-- plus API_VERSION, UI_LANGUAGE et IS_ANONYMIZED. Aucun etage du cache existant n'indexe des
-- octets, verifie le 2026-09-20. La reconnaissance est image -> entites : ni la meme cle, ni
-- la meme valeur, ni la meme duree de vie. Une ligne dont QUESTION ne serait pas une question
-- casserait toutes les requetes de maintenance ecrites sur cette table.
--
-- CE QUE CA EVITE, CHIFFRE
-- Sans ce cache, la meme photo redeposee repaie l'appel de vision, environ 4 centimes et deux
-- secondes, que la question soit la meme ou non : la question composee est identique, donc le
-- cache SQL repond, mais il repond apres la depense. Le dispositif cachait la moitie bon
-- marche et pas la chere. Ce qui evitait reellement le second appel, dans le reste du ticket,
-- est le renvoi de l'entite resolue par le client : un contrat cote client, que celui qui
-- l'oublie paie plein tarif sans que rien ne le signale. Un cache serveur tient sans la
-- cooperation de personne.
--
-- LA CLE EXISTAIT DEJA
-- uploads.f_getuploadfilename hache les OCTETS BRUTS dans le nom du depot
-- (YYYYMMDD-HHMMSS_vision_<version>_<md5>.<ext>). Les memes octets redeposes donnent un
-- horodatage different et le MEME md5. La cle est donc gratuite, et elle est stable.
--
-- TROIS REGLES, CHACUNE POUR UN DEFAUT DEJA PAYE AILLEURS
-- 1. Portee par version d'API, comme tout le reste ici, parce que data/vision_identification.md
--    est recharge a chaud : sans la portee, une retouche de prompt livree sans bump servirait
--    des identifications faites par le prompt precedent. C'est le piege deja consigne dans
--    Version management workflow.
-- 2. Seule la moitie independante de la question est stockee. about_image et image_answer
--    dependent de ce que l'utilisateur a demande et sont volontairement jetes
--    (vision_cache.identification_payload). Ce qui reste, hints / items / authoritative_empty /
--    justification, est une propriete de l'image seule, et c'est ce qui permet a une ligne de
--    servir n'importe quelle question posee plus tard sur cette photo.
-- 3. authoritative_empty SE CACHE, contrairement au resultat SQL vide de la Gotcha #8b. Une
--    photo de repas le restera demain, et c'est le cas ou le cache evite le plus surement une
--    depense inutile.
--
-- LA BORNE DE RETENTION, A NE PAS RATER
-- Les images sont purgees a 30 jours (-275). Une entree dont le fichier a disparu RESTE VALIDE,
-- puisqu'elle est indexee sur l'empreinte des octets et non sur le fichier ; mais elle ne sert
-- alors que l'identification, jamais les pixels. Une question portant sur l'affiche elle-meme
-- a toujours besoin du fichier et recoit le 410 de uploads.load_vision_image. Le cache rend
-- l'entite, jamais l'image. Corollaire : cette table n'a pas de purge et n'en veut pas, ses
-- lignes sont petites et elles survivent utilement a leurs images.
--
-- POURQUOI LA CLE UNIQUE NE PORTE PAS LE MODELE
-- T_WC_T2S_CACHE ne porte pas le modele non plus, et pour la meme raison : un appelant qui veut
-- comparer deux modeles passe retrieve_from_cache = false, comme le fait l'evaluateur. Le modele
-- est stocke (VISION_MODEL) pour qu'une ligne dise qui l'a ecrite, jamais pour discriminer une
-- lecture. Mettre le modele dans la cle rendrait le cache inoperant des qu'un client change de
-- defaut, ce qui est l'inverse du but.
--
-- NON VERIFIE
-- Rien ici n'a ete execute : la base n'est pas joignable depuis le poste de developpement.
-- Valide syntaxiquement, pas par un passage reel. Le code degrade proprement tant que la table
-- n'existe pas : vision_cache.py bascule sur le premier "Table doesn't exist" (erreur 1146) et
-- le chemin vision continue de fonctionner, sans cache, au lieu de rendre 500.


-- ===== 1. Constat, a lire avant d'ecrire =====

-- La table existe-t-elle deja ? (0 ligne = tout est a creer)
-- Attention au piege DATABASE() decrit dans maintenance/AGENTS.md : en cas de doute, nommer
-- le schema en clair plutot que de croire un resultat vide.
SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_VISION_CACHE';


-- ===== 2. Creation =====

CREATE TABLE IF NOT EXISTS T_WC_T2S_VISION_CACHE (
  ID_ROW BIGINT(20) NOT NULL AUTO_INCREMENT,
  -- L'empreinte MD5 des octets de l'image, telle qu'elle figure dans le nom du depot.
  IMAGE_MD5 CHAR(32) NOT NULL,
  -- Version formatee XXX.YYY.ZZZ, comme T_WC_T2S_CACHE.API_VERSION.
  API_VERSION VARCHAR(11) NOT NULL,
  -- Le nom de depot vu en dernier pour ces octets. Indicatif : le fichier peut avoir ete
  -- purge, et la meme image redeposee porte un horodatage different pour le meme MD5.
  IMAGE_REF VARCHAR(255) NULL,
  -- La moitie independante de la question, en JSON : hints, items, authoritative_empty,
  -- justification. Jamais about_image ni image_answer.
  IDENTIFICATION MEDIUMTEXT NULL,
  VISION_MODEL VARCHAR(100) NULL,
  AUTHORITATIVE_EMPTY TINYINT(1) NOT NULL DEFAULT 0,
  VISION_IDENTIFICATION_PROCESSING_TIME DECIMAL(10,4) NULL,
  DELETED TINYINT(1) DEFAULT 0,
  DAT_CREAT DATE NULL,
  TIM_UPDATED DATETIME NULL,
  PRIMARY KEY (ID_ROW),
  UNIQUE KEY UK_T2S_VISION_CACHE (IMAGE_MD5, API_VERSION),
  KEY IDX_T2S_VISION_CACHE_REF (IMAGE_REF)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ===== 3. Verification =====

-- Les colonnes attendues, dans l'ordre.
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_VISION_CACHE'
ORDER BY ORDINAL_POSITION;

-- La cle unique est ce qui empeche une photo redeposee d'empiler des lignes : elle doit
-- exister, sur (IMAGE_MD5, API_VERSION), et etre unique.
SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
FROM INFORMATION_SCHEMA.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_VISION_CACHE'
ORDER BY INDEX_NAME, SEQ_IN_INDEX;

-- Apres quelques requetes image : combien d'identifications par version, et combien de
-- photos hors cinema (celles qui rapportent le plus au cache).
SELECT API_VERSION,
       COUNT(*)                        AS identifications,
       SUM(AUTHORITATIVE_EMPTY = 1)    AS hors_catalogue,
       ROUND(AVG(VISION_IDENTIFICATION_PROCESSING_TIME), 2) AS secondes_moyennes
FROM T_WC_T2S_VISION_CACHE
WHERE (DELETED IS NULL OR DELETED = 0)
GROUP BY API_VERSION
ORDER BY API_VERSION;


-- ===== 4. Retrait, si la table doit disparaitre =====

-- Retrait doux d'une identification suspecte (le prompt a change, une photo est mal lue) :
-- la ligne est retiree, la reconnaissance sera repayee une fois, et une ligne neuve la
-- remplacera par la cle unique.
-- UPDATE T_WC_T2S_VISION_CACHE SET DELETED = 1, TIM_UPDATED = NOW()
--  WHERE IMAGE_MD5 = '<md5>' AND API_VERSION = '<XXX.YYY.ZZZ>';

-- Retrait complet. Aucune sauvegarde prealable n'est demandee ici, contrairement a la regle
-- generale de ce dossier, et c'est delibere : cette table est integralement reconstructible
-- en repayant les appels de vision. Ce qu'elle contient n'existe nulle part ailleurs, mais
-- rien ne s'y perd qui ne puisse etre recalcule a partir des images encore presentes.
-- DROP TABLE T_WC_T2S_VISION_CACHE;
