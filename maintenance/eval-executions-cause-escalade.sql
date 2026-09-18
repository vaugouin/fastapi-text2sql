-- Ajoute FIRST_PASS_FAILURE_CODE et QUERY_MODE a T_WC_T2S_EVALUATION_EXECUTION
-- (FASTAPI-TEXT2SQL-271).
--
-- MIGRATION SEPAREE, comme eval-mode-de-resolution.sql avant elle : les migrations
-- precedentes sont passees, les rejouer ferait echouer leurs ALTER sur des colonnes
-- desormais existantes. Chaque fichier reste rejouable pour lui-meme.
--
-- POURQUOI
-- -257 a donne a la campagne le CONSTAT de l'escalade : COMPLEX_MODEL_USED dit qu'une ligne a
-- bascule sur le modele fort, RESOLUTION_MODE_RESPECTED dit si elle en avait le droit. Aucune
-- colonne ne dit POURQUOI elle a bascule. Or les causes n'ont ni le meme cout ni le meme
-- correctif :
--   descriptive_identification   l'extraction a classe la question comme une identification
--                                d'entite non nommee. L'escalade est le comportement voulu,
--                                c'est la raison d'etre du mode.
--   requires_complex_resolution  Text2SQL s'est declare incapable. L'escalade est un aveu.
--   unbacked_entity_literal      la garde de provenance a refuse un litteral que ni
--                                l'utilisateur ni l'extraction n'ont fourni. L'escalade
--                                rattrape une hallucination.
--   no_results:<signal>          la premiere passe a rendu zero ligne.
--   text2sql_error, sql_execution_error, sql_guard_rejected
--                                la premiere passe a casse.
-- Confondre la premiere avec les autres fait lire un succes du dispositif comme une faiblesse
-- du chemin normal, et inversement.
--
-- LE PREALABLE, CORRIGE DANS LE MEME COMMIT
-- La colonne n'aurait pas suffi : jusqu'a ce commit, main.py rangeait les deux premieres causes
-- sous la MEME valeur, "requires_complex_resolution". Seul first_pass_failure_reason, du texte
-- libre, les distinguait, et aucune campagne ne peut grouper la-dessus. main.py porte desormais
-- complex_resolution_code, pose au point de decision, et "descriptive_identification" est une
-- valeur a part entiere du vocabulaire ferme de first_pass_failure_code.
--
-- CONSEQUENCE SUR LA COMPARAISON ENTRE CAMPAGNES, a savoir avant de conclure
-- Les lignes ecrites AVANT ce commit portent, dans leur JSON_RESULT, la valeur melangee. Sur ces
-- lignes-la, "requires_complex_resolution" veut dire "descriptive OU Text2SQL incapable". La
-- section 3 propose de les departager a partir de first_pass_failure_reason, qui lui a toujours
-- dit la verite. Mesure du 2026-09-17 sur les 505 logs locaux : 35 reprises sous cette valeur,
-- et les 35 sont des routages descriptifs. Zero venait de Text2SQL. L'etiquette commune portait
-- donc le nom du cas jamais observe, ce qui est la pire facon de se tromper : elle ne ressemble
-- pas a une erreur, elle ressemble a une statistique.
--
-- POURQUOI DEUX COLONNES ET NON UNE
-- FIRST_PASS_FAILURE_CODE ne vaut que sur une ligne REPRISE. QUERY_MODE vaut sur toutes, y
-- compris celles qui n'ont pas escalade, ce qui en fait le denominateur : sans lui on ne peut pas
-- demander "combien de questions descriptives la campagne a-t-elle vues", seulement "combien ont
-- escalade". Les deux colonnes repondent a deux questions, et la seconde est celle qui permet de
-- calculer un taux.
--
-- LE PIEGE QUE QUERY_MODE EVITE, et c'est la vraie raison de cette colonne
-- Sur une reprise, le champ entity_extraction de la reponse decrit la passe INTERNE, celle de la
-- question reecrite par le modele fort (FASTAPI-TEXT2SQL-256). Son query_mode lit donc presque
-- toujours named_entity_query, puisque le modele fort rend justement une question a entite
-- nommee. Le classement qui a PROVOQUE le routage vit dans first_pass_entity_extraction. Mesure
-- du 2026-09-17 sur les 505 logs locaux : 30 reprises classees descriptive_identification en
-- premiere passe, dont 27 affichent named_entity_query dans entity_extraction et 3 rien du tout.
-- Lire le mauvais champ inverserait la conclusion, et ferait lire la campagne comme une absence
-- quasi totale de questions descriptives. La colonne prend donc first_pass_entity_extraction
-- quand il existe, entity_extraction sinon.
--
-- LA COMBINAISON QUI N'EST PAS UN TROU
-- COMPLEX_MODEL_USED = 1 avec FIRST_PASS_FAILURE_CODE vide n'est pas une colonne mal remplie :
-- c'est la signature du seul chemin qui escalade sans passer par la reprise, la reponse scalaire
-- directe, quand le SQL a rendu une cellule unique valant 0. Elle se lit comme une cause a part
-- entiere, et ANSWER_SINGLE_VALUE_PROCESSING_TIME la confirme.
--
-- CE QUI A TOURNE, ET CE QUI N'A PAS TOURNE
-- Section 2 executee le 2026-09-18 : les deux colonnes existent en production. Le reste du
-- fichier n'a pas ete joue. Les sections 1 et 4 sont de la lecture, la section 3 est le
-- rattrapage facultatif des campagnes anterieures, encore ouvert.
-- La base n'est pas joignable depuis le poste de developpement, donc rien ici n'a ete verifie
-- depuis le depot : la section 2 est passee entre les mains de Philippe, pas entre les miennes.
-- Les DDL de reference doc/sql/T2S_EVALUATION-tables.sql et doc/sql/T2S-tables.sql ont ete mis a
-- jour en meme temps ; les trois doivent rester d'accord.


-- ===== 1. Constat, a lire avant d'ecrire =====

-- Les colonnes existent-elles deja ? (0 ligne = tout est a ajouter)
-- Si cette requete rend 0 ligne alors que vous attendiez le contraire, nommez le schema
-- explicitement (TABLE_SCHEMA = 'vaugouindb') : DATABASE() ment quand la session phpMyAdmin est
-- posee sur INFORMATION_SCHEMA. Voir maintenance/AGENTS.md, le piege DATABASE().
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN ('FIRST_PASS_FAILURE_CODE', 'QUERY_MODE')
ORDER BY COLUMN_NAME;

-- Les quatre colonnes de -257 sont-elles bien la ? (4 attendues)
SELECT COUNT(*) AS colonnes_257
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
  AND COLUMN_NAME IN ('COMPLEX_MODEL_USED',
                      'ANSWER_SINGLE_VALUE_PROCESSING_TIME',
                      'RESOLUTION_MODE',
                      'RESOLUTION_MODE_RESPECTED');

-- L'ampleur du trou, sur la derniere campagne complete : combien d'escalades, et combien
-- d'entre elles disent aujourd'hui leur cause autrement qu'en texte libre.
SELECT API_VERSION,
       COUNT(*)                                  AS lignes,
       SUM(COMPLEX_MODEL_USED = 1)               AS escalades,
       SUM(COMPLEX_MODEL_USED = 1
           AND JSON_VALID(JSON_RESULT)
           AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_code')), '') <> '')
                                                 AS dont_cause_lisible_dans_le_json,
       SUM(COMPLEX_MODEL_USED = 1
           AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_code')), '') = '')
                                                 AS dont_reponse_scalaire_directe
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0
  AND API_VERSION = '001.001.019'
GROUP BY API_VERSION;


-- ===== 2. Ajout des colonnes =====
-- Aucune sauvegarde prealable requise : un ADD COLUMN ne touche aucune donnee existante et se
-- defait par les DROP COLUMN de la section 5.

ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD COLUMN `FIRST_PASS_FAILURE_CODE` varchar(120) DEFAULT NULL
    COMMENT 'Cause de l escalade, vocabulaire ferme : descriptive_identification, requires_complex_resolution, unbacked_entity_literal, text2sql_error, sql_guard_rejected, sql_execution_error, entity_fallback_unmatchable, no_results avec ses signaux. NULL sans reprise ; NULL avec COMPLEX_MODEL_USED=1 signe la reponse scalaire directe.'
    AFTER `RESOLUTION_MODE_RESPECTED`,
  ADD COLUMN `QUERY_MODE` varchar(32) DEFAULT NULL
    COMMENT 'Classement de la PREMIERE passe : named_entity_query, descriptive_identification, ordinary_filter_query. Lu dans first_pass_entity_extraction quand il existe, sinon entity_extraction. NULL quand le modele n a pas emis le champ (facultatif, FASTAPI-TEXT2SQL-255) ou sur un hit du cache exact, ou aucune extraction n a lieu.'
    AFTER `FIRST_PASS_FAILURE_CODE`,
  ADD KEY `FIRST_PASS_FAILURE_CODE` (`FIRST_PASS_FAILURE_CODE`),
  ADD KEY `QUERY_MODE` (`QUERY_MODE`);

-- Les lignes anterieures gardent NULL, et c'est voulu. Sur FIRST_PASS_FAILURE_CODE, NULL dit
-- "cette campagne ne mesurait pas cet indicateur en colonne", ce qu'une chaine vide confondrait
-- avec "escalade sans reprise", qui est justement une valeur signifiante. Sur QUERY_MODE, NULL
-- dit trois choses que la section 4 separe : champ non mesure, champ non emis par le modele,
-- ou extraction jamais faite.


-- ===== 3. Rattrapage des lignes deja jouees, facultatif =====
-- A ne lancer que si vous voulez pouvoir comparer les campagnes anterieures a la prochaine.
-- Tout ce qui suit relit JSON_RESULT, qui contient deja tout : ce n'est pas une invention de
-- donnee, c'est une recopie. JSON_VALID ecarte les lignes dont la reponse n'est pas du JSON.

-- 3a. Lire avant d'ecrire. Ce que le rattrapage poserait, par valeur.
SELECT COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_code')), ''),
                '(vide)') AS code,
       COUNT(*) AS lignes
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0 AND JSON_VALID(JSON_RESULT) AND COMPLEX_MODEL_USED = 1
GROUP BY code
ORDER BY lignes DESC;

-- 3b. La recopie elle-meme.
-- UPDATE T_WC_T2S_EVALUATION_EXECUTION
-- SET FIRST_PASS_FAILURE_CODE =
--       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_code')), ''),
--     QUERY_MODE = COALESCE(
--       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_entity_extraction.query_mode')), ''),
--       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.entity_extraction.query_mode')), ''))
-- WHERE DELETED = 0 AND JSON_VALID(JSON_RESULT);

-- 3c. Departager les lignes anterieures au commit, ou descriptive_identification et
-- requires_complex_resolution arrivaient sous la seule seconde valeur. first_pass_failure_reason
-- portait deja la distinction, en clair. C'est un rattrapage sur chaine de caracteres, donc le
-- compte d'abord, l'ecriture ensuite.
-- SELECT COUNT(*) AS a_requalifier
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND JSON_VALID(JSON_RESULT)
--   AND FIRST_PASS_FAILURE_CODE = 'requires_complex_resolution'
--   AND JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_reason'))
--       LIKE '%descriptive_identification%';
--
-- UPDATE T_WC_T2S_EVALUATION_EXECUTION
-- SET FIRST_PASS_FAILURE_CODE = 'descriptive_identification'
-- WHERE DELETED = 0 AND JSON_VALID(JSON_RESULT)
--   AND FIRST_PASS_FAILURE_CODE = 'requires_complex_resolution'
--   AND JSON_UNQUOTE(JSON_EXTRACT(JSON_RESULT, '$.first_pass_failure_reason'))
--       LIKE '%descriptive_identification%';


-- ===== 4. Verification apres coup, une fois une campagne relancee =====

-- La lecture que tout ce fichier existe pour rendre possible : l'escalade par cause.
-- SELECT COALESCE(FIRST_PASS_FAILURE_CODE,
--                 CASE WHEN COMPLEX_MODEL_USED = 1 THEN 'reponse scalaire directe'
--                      ELSE 'pas d escalade' END)     AS cause,
--        COUNT(*)                                      AS lignes,
--        ROUND(100 * AVG(ASSERTIONS_TOTAL_SCORE), 1)   AS score_assertions_pct,
--        ROUND(AVG(TOTAL_PROCESSING_TIME), 2)          AS total_moyen_s
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND API_VERSION = '001.001.019'
-- GROUP BY cause
-- ORDER BY lignes DESC;

-- Le taux d'escalade par classement, qui est la mesure directe du dispositif -253/-254 :
-- descriptive_identification doit tendre vers 100 %, les deux autres modes vers 0 %.
-- SELECT COALESCE(QUERY_MODE, '(non emis)')         AS classement,
--        COUNT(*)                                    AS lignes,
--        SUM(COMPLEX_MODEL_USED = 1)                 AS escalades,
--        ROUND(100 * AVG(COMPLEX_MODEL_USED = 1), 1) AS taux_escalade_pct
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND API_VERSION = '001.001.019'
-- GROUP BY COALESCE(QUERY_MODE, '(non emis)')
-- ORDER BY lignes DESC;

-- Le croisement avec le mode declare par la banque (-257). Une question declaree complex qui
-- escalade pour une cause AUTRE que descriptive_identification est passee par ou il ne fallait
-- pas : bon verdict, mauvaise raison, et RESOLUTION_MODE_RESPECTED le comptait comme un succes.
-- SELECT x.RESOLUTION_MODE, x.FIRST_PASS_FAILURE_CODE, COUNT(*) AS lignes
-- FROM T_WC_T2S_EVALUATION_EXECUTION x
-- WHERE x.DELETED = 0 AND x.API_VERSION = '001.001.019' AND x.COMPLEX_MODEL_USED = 1
-- GROUP BY x.RESOLUTION_MODE, x.FIRST_PASS_FAILURE_CODE
-- ORDER BY lignes DESC;

-- La population a lire en premier : les questions declarees complex que la premiere passe a cru
-- pouvoir traiter, donc classees autrement que descriptive_identification. C'est le rate du
-- classement, pas celui du SQL, et aucune colonne ne le montrait jusqu'ici.
-- SELECT x.ID_T2S_EVALUATION, x.LANG, e.QUESTION, x.QUERY_MODE, x.FIRST_PASS_FAILURE_CODE
-- FROM T_WC_T2S_EVALUATION_EXECUTION x
-- JOIN T_WC_T2S_EVALUATION e ON e.ID_T2S_EVALUATION = x.ID_T2S_EVALUATION
-- WHERE x.DELETED = 0 AND x.API_VERSION = '001.001.019'
--   AND x.RESOLUTION_MODE = 'complex'
--   AND COALESCE(x.QUERY_MODE, '') <> 'descriptive_identification'
-- ORDER BY x.ID_T2S_EVALUATION;

-- Et le controle d'intendance : QUERY_MODE non emis. Le champ est facultatif cote garde-fou
-- (FASTAPI-TEXT2SQL-255), donc un taux qui monte signale que le modele a cesse de le rendre, ce
-- qui desactive silencieusement le routage descriptif. A surveiller campagne apres campagne.
-- SELECT API_VERSION,
--        COUNT(*)                                AS lignes,
--        SUM(QUERY_MODE IS NULL)                 AS sans_classement,
--        ROUND(100 * AVG(QUERY_MODE IS NULL), 1) AS pct_sans_classement
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND API_VERSION >= '001.001.019'
-- GROUP BY API_VERSION
-- ORDER BY API_VERSION;


-- ===== 5. Retour arriere =====
-- ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
--   DROP COLUMN `FIRST_PASS_FAILURE_CODE`,
--   DROP COLUMN `QUERY_MODE`;
