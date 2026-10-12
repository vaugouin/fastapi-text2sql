-- Retire les trois tables de sauvegarde du cache, devenues inutiles.
--
--   T_WC_T2S_CACHE_PURGE_20260803
--   T_WC_T2S_CACHE_PURGE_AGG_20260803
--   T_WC_T2S_CACHE_TWINS_20260820
--
-- DESTRUCTIF, ET LA CONVENTION DU DOSSIER EXIGE QUE LA RAISON SOIT ECRITE
-- Ce dossier impose la suppression douce (DELETED = 1) pour des lignes. Ici il s'agit de
-- tables entieres, et un DROP ne se defait pas. La raison est double.
--
-- 1. Elles ne protegent plus rien. Une table de sauvegarde existe pour rendre possible
--    l'annulation d'un nettoyage. Celui des lignes jumelles est clos (FASTAPI-TEXT2SQL-202
--    est marque fait, le code n'ecrit plus la ligne jumelle), donc son annulation n'a plus
--    d'objet. Les deux purges datent du 2026-08-03 et n'ont jamais ete contestees depuis.
--
-- 2. Elles coutent tous les jours. backupvaugouindb-t2s.sh (depot tmdb-front) resout les
--    tables a sauvegarder dynamiquement par LIKE 'T_WC_T2S_%'. Ces trois-la matchent, donc
--    elles sont copiees dans chaque dump nocturne depuis leur creation, alors qu'elles ne
--    servent plus. C'est la meme motivation que l'arret volontaire de l'API Green :
--    economiser les ressources du VPS.
--
-- LE FILET, ET C'EST LE MEME MECANISME
-- Puisque ces tables entrent dans le dump T2S, n'importe quel dump anterieur au DROP les
-- contient. La recuperation passe par la restauration selective d'une table depuis un dump,
-- pas par le DROP lui-meme. **Prendre un dump juste avant d'executer la section 3.**
--
-- CE QUI N'EST PAS DOCUMENTE, ET DOIT ETRE REGARDE AVANT
-- Seule TWINS est creee par un fichier de ce dossier (cache-jumelles-et-empoisonnees.sql),
-- qui dit ce qu'elle contient et porte son UPDATE d'annulation. Les deux PURGE_20260803
-- ne sont creees par AUCUN fichier du depot et ne sont citees nulle part, sinon dans
-- maintenance/AGENTS.md comme simple precedent de nommage. Autrement dit, personne ne sait
-- plus ce qu'elles contiennent. La section 1 est donc obligatoire : elle est la derniere
-- occasion de le constater, et le resultat merite d'etre recopie en commentaire au bas de ce
-- fichier avant le DROP, faute de quoi le savoir part avec la table.
--
-- EXECUTE LE 2026-08-24
-- Les trois tables ont ete supprimees et les dumps de schema de doc/sql regeneres dans
-- fastapi-text2sql et tmdb-front : la liste des tables y perd exactement ces trois entrees,
-- 42 lignes par fichier, aucune autre difference. Voir la section 5 pour ce qui n'a pas ete
-- releve a temps.

-- ===========================================================================
-- 1. Constat. Obligatoire avant tout DROP.
-- ===========================================================================

-- Les trois tables existent-elles encore, que pesent-elles, et depuis quand ?
SELECT TABLE_NAME,
       TABLE_ROWS                                              AS lignes_estimees,
       ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 1)    AS taille_mo,
       CREATE_TIME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
    'T_WC_T2S_CACHE_PURGE_20260803',
    'T_WC_T2S_CACHE_PURGE_AGG_20260803',
    'T_WC_T2S_CACHE_TWINS_20260820'
  )
ORDER BY TABLE_NAME;

-- Que contiennent les deux PURGE, dont plus aucun fichier ne parle ?
-- A lire avant de decider, et a recopier au bas de ce fichier.
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('T_WC_T2S_CACHE_PURGE_20260803', 'T_WC_T2S_CACHE_PURGE_AGG_20260803')
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- SELECT * FROM T_WC_T2S_CACHE_PURGE_20260803 LIMIT 5;
-- SELECT * FROM T_WC_T2S_CACHE_PURGE_AGG_20260803 LIMIT 5;

-- ===========================================================================
-- 2. Verifier que l'annulation du nettoyage des jumelles n'a plus d'objet.
-- ===========================================================================
-- La sauvegarde TWINS ne sert qu'a ce seul UPDATE, cite par
-- cache-jumelles-et-empoisonnees.sql section 7 :
--   UPDATE T_WC_T2S_CACHE c
--     JOIN T_WC_T2S_CACHE_TWINS_20260820 b ON b.ID_ROW = c.ID_ROW
--     SET c.DELETED = COALESCE(b.DELETED, 0);
--
-- Combien de lignes ce retour arriere ressusciterait-il aujourd'hui ? Le chiffre dit ce
-- qu'on renonce a pouvoir defaire. Si le nettoyage est acquis, il est sans importance ;
-- s'il surprend, ne pas executer la section 3 et comprendre d'abord.
SELECT COUNT(*) AS lignes_que_l_annulation_ressusciterait
FROM T_WC_T2S_CACHE c
JOIN T_WC_T2S_CACHE_TWINS_20260820 b ON b.ID_ROW = c.ID_ROW
WHERE COALESCE(c.DELETED, 0) = 1
  AND COALESCE(b.DELETED, 0) = 0;

-- ===========================================================================
-- 3. Suppression. A n'executer qu'apres un dump frais.
-- ===========================================================================
-- IF EXISTS pour rester rejouable : une seconde execution ne produit qu'un avertissement.

DROP TABLE IF EXISTS `T_WC_T2S_CACHE_TWINS_20260820`;
DROP TABLE IF EXISTS `T_WC_T2S_CACHE_PURGE_AGG_20260803`;
DROP TABLE IF EXISTS `T_WC_T2S_CACHE_PURGE_20260803`;

-- ===========================================================================
-- 4. Verification apres coup.
-- ===========================================================================
-- Doit rendre zero ligne.
-- SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
-- WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'T_WC_T2S_CACHE_%20260%';
--
-- Puis regenerer les dumps de schema de doc/sql dans fastapi-text2sql ET tmdb-front, qui
-- portent tous deux ces tables depuis la derniere regeneration et doivent rester d'accord.

-- ===========================================================================
-- 5. Ce que contenaient les deux PURGE, releve avant suppression.
-- ===========================================================================
-- NON RELEVE. La suppression a eu lieu le 2026-08-24 sans que le resultat de la section 1
-- soit recopie ici. Le contenu de ces deux tables n'est donc plus documente nulle part.
--
-- Ce qu'on en sait encore, et c'est tout : creees le 2026-08-03, jamais referencees par aucun
-- fichier du depot, citees seulement dans maintenance/AGENTS.md comme precedent de nommage
-- (`<TABLE>_<PURPOSE>_<YYYYMMDD>`). Leur nom indique une sauvegarde de T_WC_T2S_CACHE avant une
-- purge, et AGG une forme agregee, mais c'est une lecture du nom, pas un constat.
--
-- Recuperable si le besoin s'en fait sentir : tout dump nocturne anterieur au 2026-08-24 les
-- contient, backupvaugouindb-t2s.sh resolvant ses tables par LIKE 'T_WC_T2S_%'. Une
-- restauration selective dans une base de travail rendrait le releve possible.
--
-- La lecon pour la prochaine fois, et c'est la raison d'etre de cette section : un DROP se
-- prepare en ecrivant ce que la table contenait, pas en promettant de le faire.
