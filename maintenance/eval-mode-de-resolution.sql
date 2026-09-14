-- Ajoute le mode de resolution attendu a T_WC_T2S_EVALUATION, et les quatre colonnes qui
-- permettent de le juger a T_WC_T2S_EVALUATION_EXECUTION (FASTAPI-TEXT2SQL-257).
--
-- MIGRATION SEPAREE, comme eval-executions-chronometre-complexe.sql avant elle : les
-- migrations precedentes sont passees, les rejouer ferait echouer leurs ALTER sur des
-- colonnes desormais existantes. Chaque fichier reste rejouable pour lui-meme.
--
-- POURQUOI (FASTAPI-TEXT2SQL-257)
-- complex_model_used est aujourd'hui une observation : elle decrit ce qui s'est passe et ne
-- peut jamais echouer. Aucune evaluation ne dit quel chemin DEVAIT la resoudre. Une question
-- qui bascule sur le modele fort alors que le chemin normal aurait du suffire est donc comptee
-- "reussie", alors que c'est une regression du chemin normal payee au prix de deux passages
-- complets du pipeline. Declarer le mode attendu transforme le constat en critere.
--
-- LE DECLENCHEUR
-- Les questions descriptives de la video #8 : "un presentateur meteo qui se reveille chaque
-- matin le meme jour", attendu Un jour sans fin. Aucune entite a extraire, aucune colonne a
-- filtrer, aucune jointure possible. Ce genre de question NE PEUT PAS se resoudre sans
-- l'escalade, et la banque n'avait aucun moyen de le dire.
--
-- LE PREREQUIS, ET IL EST LA VRAIE RAISON DE CE FICHIER
-- Le verdict se calcule sur ce que la campagne enregistre, et l'enregistrement etait
-- incomplet d'un quart. Mesure du 2026-09-14 sur la campagne 001.001.018 : complex_model_used
-- vaut vrai sur 46 executions, mais COMPLEX_QUESTION_PROCESSING_TIME n'en voit que 34. Les 12
-- manquantes viennent des chemins qui levent le drapeau sans remplir ce chronometre-la, en
-- particulier la reponse scalaire directe, qui encaisse dans answer_single_value_processing_time.
-- Ni COMPLEX_MODEL_USED ni ANSWER_SINGLE_VALUE_PROCESSING_TIME n'existaient en colonne. Sans
-- elles, trancher une campagne demanderait de rouvrir chaque JSON_RESULT, ce que les colonnes
-- dediees existent precisement pour eviter.
--
-- POURQUOI ASSERTIONS_TOTAL_SCORE N'EST PAS TOUCHE, et c'est un choix
-- Il aurait ete tentant de faire echouer le score global quand le mode n'est pas respecte.
-- C'eut ete se tirer une balle dans le pied : ASSERTIONS_TOTAL_SCORE est la mesure qui permet
-- de comparer une campagne a la precedente, et y injecter un nouveau motif d'echec rendrait
-- 1.1.19 incomparable a 1.1.18. Le respect du mode vit donc dans sa propre colonne,
-- RESOLUTION_MODE_RESPECTED. Deux mesures, deux lectures, aucune contamination.
--
-- POURQUOI LE MODE EST AUSSI COPIE SUR L'EXECUTION
-- RESOLUTION_MODE existe des deux cotes. Cote banque c'est la declaration courante ; cote
-- execution c'est celle qui avait cours au moment du passage. Requalifier une evaluation plus
-- tard ne doit pas reecrire le sens des campagnes deja jouees.
--
-- NON VERIFIE
-- Rien ici n'a ete execute : la base n'est pas joignable depuis le poste de developpement
-- (connexion refusee sur localhost:3306 le 2026-09-14). Valide syntaxiquement, pas par un
-- passage reel. Les DDL de reference doc/sql/T2S_EVALUATION-tables.sql et doc/sql/T2S-tables.sql
-- ont ete mis a jour en meme temps ; les trois doivent rester d'accord.


-- ===== 1. Constat, a lire avant d'ecrire =====

-- Les colonnes existent-elles deja ? (0 ligne = tout est a ajouter)
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND (
    (TABLE_NAME = 'T_WC_T2S_EVALUATION' AND COLUMN_NAME = 'RESOLUTION_MODE')
    OR (TABLE_NAME = 'T_WC_T2S_EVALUATION_EXECUTION'
        AND COLUMN_NAME IN ('COMPLEX_MODEL_USED',
                            'ANSWER_SINGLE_VALUE_PROCESSING_TIME',
                            'RESOLUTION_MODE',
                            'RESOLUTION_MODE_RESPECTED'))
  )
ORDER BY TABLE_NAME, COLUMN_NAME;

-- L'ampleur du trou que ces colonnes bouchent, sur la derniere campagne complete.
-- Attendu au 2026-09-14 : 46 escalades vues par le JSON, 34 seulement par la colonne de temps.
SELECT API_VERSION,
       COUNT(*)                                          AS lignes,
       SUM(COMPLEX_QUESTION_PROCESSING_TIME > 0)         AS vues_par_la_colonne_de_temps,
       SUM(JSON_RESULT LIKE '%"complex_model_used": true%'
           OR JSON_RESULT LIKE '%"complex_model_used":true%') AS vues_par_le_json
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE DELETED = 0
  AND API_VERSION = '001.001.018'
GROUP BY API_VERSION;


-- ===== 2. Ajout des colonnes =====
-- Aucune sauvegarde prealable requise : un ADD COLUMN ne touche aucune donnee existante et se
-- defait par les DROP COLUMN de la section 4.

-- 2a. La declaration, cote banque.
ALTER TABLE `T_WC_T2S_EVALUATION`
  ADD COLUMN `RESOLUTION_MODE` varchar(10) DEFAULT NULL
    COMMENT 'Mode qui doit resoudre la question : standard (sans escalade), complex (escalade indispensable), any (aucune attente). NULL = any.'
    AFTER `ASSERTION_REFRESH_LAST`,
  ADD KEY `RESOLUTION_MODE` (`RESOLUTION_MODE`);

-- Les 1445 lignes existantes gardent NULL, et il faut resister a l'envie de les backfiller en
-- masse a 'any'. NULL dit "la question n'a pas ete examinee sous cet angle", pas "peu importe".
-- Le code traite les deux pareil au moment du verdict, mais seul NULL permet de retrouver plus
-- tard ce qui reste a qualifier :
--   SELECT COUNT(*) FROM T_WC_T2S_EVALUATION
--   WHERE IS_EVAL = 1 AND DELETED = 0 AND RESOLUTION_MODE IS NULL;

-- 2b. Les quatre colonnes cote execution.
ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
  ADD COLUMN `COMPLEX_MODEL_USED` int(5) DEFAULT NULL
    COMMENT 'L escalade vers le modele fort a-t-elle servi (1/0). Couvre les chemins que COMPLEX_QUESTION_PROCESSING_TIME rate, dont la reponse scalaire directe.'
    AFTER `COMPLEX_QUESTION_PROCESSING_TIME`,
  ADD COLUMN `ANSWER_SINGLE_VALUE_PROCESSING_TIME` double DEFAULT NULL
    COMMENT 'Temps de la reponse scalaire directe, quand le SQL a rendu une cellule unique valant 0. 0 quand ce chemin n a pas tire.'
    AFTER `COMPLEX_MODEL_USED`,
  ADD COLUMN `RESOLUTION_MODE` varchar(10) DEFAULT NULL
    COMMENT 'Mode declare par la banque AU MOMENT DE CE PASSAGE. Copie exprès : requalifier une evaluation plus tard ne doit pas reecrire le sens des campagnes deja jouees.'
    AFTER `ANSWER_SINGLE_VALUE_PROCESSING_TIME`,
  ADD COLUMN `RESOLUTION_MODE_RESPECTED` int(5) DEFAULT NULL
    COMMENT 'Le mode declare a-t-il ete respecte (1/0). NULL quand le mode vaut any ou n est pas declare. Volontairement separe de ASSERTIONS_TOTAL_SCORE, qui doit rester comparable entre campagnes.'
    AFTER `RESOLUTION_MODE`,
  ADD KEY `COMPLEX_MODEL_USED` (`COMPLEX_MODEL_USED`),
  ADD KEY `RESOLUTION_MODE` (`RESOLUTION_MODE`),
  ADD KEY `RESOLUTION_MODE_RESPECTED` (`RESOLUTION_MODE_RESPECTED`);

-- Les lignes anterieures gardent NULL partout, et c'est voulu. Sur COMPLEX_MODEL_USED, NULL dit
-- "cette campagne ne mesurait pas cet indicateur en colonne", ce que 0 confondrait avec "aucune
-- escalade n'a eu lieu", qui est justement la valeur signifiante.


-- ===== 3. Qualifier les premieres evaluations =====
-- A jouer question par question, jamais en masse. Le mode se decide en lisant la question, pas
-- en regardant ce qu'une campagne a fait : la campagne dit ce qui EST arrive, le mode dit ce qui
-- DOIT arriver, et les confondre reviendrait a graver la regression dans le critere.

-- Exemple, une question descriptive qui ne peut pas se resoudre sans escalade.
-- UPDATE T_WC_T2S_EVALUATION SET RESOLUTION_MODE = 'complex'
-- WHERE ID_T2S_EVALUATION = <id de la question "presentateur meteo, meme jour">;

-- Exemple, une recherche par titre qui doit rester sur le chemin normal.
-- UPDATE T_WC_T2S_EVALUATION SET RESOLUTION_MODE = 'standard'
-- WHERE ID_T2S_EVALUATION = <id d'une question a titre exact>;

-- Ce que la campagne suggere, comme PISTE de qualification et rien de plus : les questions que
-- l'escalade a resolues sont des candidates a 'complex', a lire une par une avant de trancher.
-- SELECT e.ID_T2S_EVALUATION, e.QUESTION, x.API_VERSION, x.LANG
-- FROM T_WC_T2S_EVALUATION_EXECUTION x
-- JOIN T_WC_T2S_EVALUATION e ON e.ID_T2S_EVALUATION = x.ID_T2S_EVALUATION
-- WHERE x.DELETED = 0 AND e.RESOLUTION_MODE IS NULL
--   AND x.COMPLEX_MODEL_USED = 1
-- ORDER BY e.ID_T2S_EVALUATION;


-- ===== 4. Retour arriere =====
-- ALTER TABLE `T_WC_T2S_EVALUATION` DROP COLUMN `RESOLUTION_MODE`;
-- ALTER TABLE `T_WC_T2S_EVALUATION_EXECUTION`
--   DROP COLUMN `COMPLEX_MODEL_USED`,
--   DROP COLUMN `ANSWER_SINGLE_VALUE_PROCESSING_TIME`,
--   DROP COLUMN `RESOLUTION_MODE`,
--   DROP COLUMN `RESOLUTION_MODE_RESPECTED`;


-- ===== 5. Verification apres coup, une fois une campagne relancee =====

-- Le taux d'escalade par mode declare. C'est la lecture que tout ce fichier existe pour rendre
-- possible : 'standard' doit tendre vers 0 %, 'complex' vers 100 %.
-- SELECT COALESCE(RESOLUTION_MODE, 'any (non declare)') AS mode,
--        COUNT(*)                                       AS lignes,
--        SUM(COMPLEX_MODEL_USED = 1)                    AS escalades,
--        ROUND(100 * AVG(COMPLEX_MODEL_USED = 1), 1)    AS taux_escalade_pct,
--        SUM(RESOLUTION_MODE_RESPECTED = 0)             AS modes_non_respectes,
--        ROUND(100 * AVG(ASSERTIONS_TOTAL_SCORE), 1)    AS score_assertions_pct
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND API_VERSION = '001.001.019'
-- GROUP BY COALESCE(RESOLUTION_MODE, 'any (non declare)')
-- ORDER BY lignes DESC;

-- Les deux populations a lire en premier : une question standard que l'escalade a resolue,
-- c'est une regression du chemin normal, meme quand la reponse finale est juste.
-- SELECT x.ID_T2S_EVALUATION, x.LANG, e.QUESTION,
--        x.ASSERTIONS_TOTAL_SCORE, x.COMPLEX_QUESTION_PROCESSING_TIME
-- FROM T_WC_T2S_EVALUATION_EXECUTION x
-- JOIN T_WC_T2S_EVALUATION e ON e.ID_T2S_EVALUATION = x.ID_T2S_EVALUATION
-- WHERE x.DELETED = 0 AND x.API_VERSION = '001.001.019'
--   AND x.RESOLUTION_MODE = 'standard' AND x.COMPLEX_MODEL_USED = 1
-- ORDER BY x.ID_T2S_EVALUATION;

-- Et l'inverse : une question complex que le chemin normal a resolue seule. Soit l'assertion
-- est trop molle, soit la question est plus facile que prevu. Dans les deux cas, aller lire.
-- SELECT x.ID_T2S_EVALUATION, x.LANG, e.QUESTION, x.ASSERTIONS_TOTAL_SCORE
-- FROM T_WC_T2S_EVALUATION_EXECUTION x
-- JOIN T_WC_T2S_EVALUATION e ON e.ID_T2S_EVALUATION = x.ID_T2S_EVALUATION
-- WHERE x.DELETED = 0 AND x.API_VERSION = '001.001.019'
--   AND x.RESOLUTION_MODE = 'complex' AND x.COMPLEX_MODEL_USED = 0
-- ORDER BY x.ID_T2S_EVALUATION;

-- Enfin, le controle qui prouve que les 12 executions invisibles le sont devenues : sur une
-- campagne neuve, les deux comptes doivent desormais coincider a l'unite pres.
-- SELECT SUM(COMPLEX_MODEL_USED = 1)                AS escalades_vues_en_colonne,
--        SUM(COMPLEX_QUESTION_PROCESSING_TIME > 0)  AS dont_reprise_de_question,
--        SUM(ANSWER_SINGLE_VALUE_PROCESSING_TIME > 0) AS dont_reponse_scalaire
-- FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE DELETED = 0 AND API_VERSION = '001.001.019';
