-- Retire une photo du cache de reconnaissance d'image, T_WC_T2S_VISION_CACHE, pour un tournage
-- a froid : la prochaine depose de la meme photo repaie une vraie reconnaissance (environ 18 s
-- mesurees le 2026-10-09) au lieu de la servir du cache en 0,3 s.
--
-- La cle n'est PAS le MD5 du fichier d'origine (.webp, .png, .heic) : le navigateur redimensionne
-- la photo en JPEG de 1024 px avant l'envoi, et c'est le MD5 de ce JPEG qui sert de cle. On le lit
-- dans le journal du client, voice-agent/logs/client-YYYYMMDD.log, ligne look_capture : les
-- 32 caracteres hexadecimaux avant .jpg dans image_ref. Le redimensionnement est stable, la meme
-- photo donne le meme MD5 a chaque depose (verifie sur six deposes du 2026-09-30 au 2026-10-03).
--
-- Pour une autre photo : remplacer le MD5 ci-dessous aux trois endroits, commiter, puis lancer.
--
-- Photo de cette version : Photos-movies-series/sLseAX6BWBTbPpslnP5ZEVXhWkn.webp (875 248 octets)
--   -> be5facad8bdfc3d48588f93cfbe14165
--
-- Retrait doux (DELETED = 1), comme le prevoit vision-recognition-cache.sql section 4 : la lecture
-- du cache ignore la ligne, et la prochaine reconnaissance la reactive par la cle unique
-- (IMAGE_MD5, API_VERSION), sans doublon.
--
-- Sur le VPS :
--   cd ~/docker/fastapi-text2sql-<couleur en service>
--   git pull
--   ~/docker/tools/runsqlvaugouindb.sh ~/docker/fastapi-text2sql-<couleur>/maintenance/vision-cache-reset-image.sql
-- Le resultat s'ecrit a cote, vision-cache-reset-image-YYYYMMDD.txt (-f pour rejouer le meme jour).


-- ===== 1. Avant : la photo est-elle en cache, et pour quelles versions ? =====

SELECT ID_ROW, API_VERSION, IMAGE_REF, VISION_MODEL, AUTHORITATIVE_EMPTY,
       VISION_IDENTIFICATION_PROCESSING_TIME, DELETED, TIM_UPDATED
FROM T_WC_T2S_VISION_CACHE
WHERE IMAGE_MD5 = 'be5facad8bdfc3d48588f93cfbe14165';


-- ===== 2. Retrait doux, toutes versions confondues =====

UPDATE T_WC_T2S_VISION_CACHE SET DELETED = 1, TIM_UPDATED = NOW()
WHERE IMAGE_MD5 = 'be5facad8bdfc3d48588f93cfbe14165'
  AND (DELETED IS NULL OR DELETED = 0);


-- ===== 3. Apres : plus aucune ligne vivante attendue (DELETED = 1 partout) =====

SELECT ID_ROW, API_VERSION, DELETED, TIM_UPDATED
FROM T_WC_T2S_VISION_CACHE
WHERE IMAGE_MD5 = 'be5facad8bdfc3d48588f93cfbe14165';
