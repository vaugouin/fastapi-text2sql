-- ============================================================================
-- Deux evaluations Criterion qui isolent une seule variable : la presence, ou
-- l'absence, d'un mot de type dans la question
-- ============================================================================
--
-- NON APPLIQUE. Deux INSERT, section 2, chacun garde par un NOT EXISTS.
--
-- POURQUOI CES DEUX QUESTIONS, ET POURQUOI ENSEMBLE. Le prompt dit qu'une question
-- sur le CONTENU d'une collection doit rendre les films ET les series, sauf si elle
-- restreint le type :
--
--   « Unless the question restricts the type, a question about the content of a
--     collection must return both [...] Restricting to movies when the question did
--     not ask silently drops part of the answer, and a missing row looks exactly
--     like a row that does not exist. »
--
-- FASTAPI-TEXT2SQL-264 dit que l'API ne le fait pas, et que la cause n'est pas le
-- modele mais la garde d'entite de reponse, dont le classifieur ne dispose pas de
-- movie_serie dans son vocabulaire (_RESULT_ENTITY_SOURCES, main.py:565) et qui
-- regenere donc vers T_WC_T2S_MOVIE.
--
-- Une seule question ne prouverait rien : rouge, elle pourrait l'etre parce que la
-- collection se resout mal, parce que la jonction serie est vide, ou pour dix
-- autres raisons. La PAIRE isole la variable. Meme collection, meme contenu
-- attendu, meme assertion. Une seule difference, le mot de type :
--
--   A  « What is in the Criterion Collection? »        AUCUN mot de type
--   B  « Movies and series in the Criterion Collection »  les deux types nommes
--
-- ATTENDU AU MOMENT DE L'ECRITURE, 2026-09-16 : A ROUGE, B VERT. C'est cet ecart
-- qui demontre -264, et lui seul. Si A et B sont rouges toutes les deux, la cause
-- est ailleurs et -264 est mal diagnostique. Si A et B sont vertes toutes les deux,
-- -264 est deja corrige.
--
-- B a ete verifie manuellement le 2026-09-02, dans la recette de
-- FASTAPI-TEXT2SQL-237 : « Liste les films et les series de la Collection
-- Criterion » rendait bien une UNION a quinze colonnes, spine affiche. Il est
-- attendu vert, mais il n'a jamais ete note par l'evaluateur, d'ou son ajout ici.
--
-- POURQUOI L'ASSERTION PORTE SUR LE SQL ET NON SUR LES LIGNES. Le slot
-- ASSERTIONS_SQL_QUERY est une expression reguliere appliquee a
-- response_json["sql_query"] : elle teste la FORME de la requete. C'est le seul
-- test qui ne depende ni de l'ordre, ni de la page, ni d'un rafraichissement de la
-- base. Une reponse films-seuls ne peut pas la satisfaire, quelle que soit la
-- popularite du moment. Une liste d'identifiants, elle, tomberait avec le premier
-- changement de tri, ce qui est precisement le piege documente sur l'evaluation 44.
--
-- ASSERTIONS_QUERY_RESULT EST LAISSE NULL, DELIBEREMENT. Ces deux questions n'ont
-- jamais ete notees contre la base, et inventer une liste d'identifiants serait
-- deviner. La section 4 tient un bloc pret a remplir une fois -264 livre et les
-- lignes reellement observees. Meme regle que new-evaluations-entity-types.sql.
--
-- GARDE DE REJEU. Chaque INSERT est un INSERT ... SELECT garde par un NOT EXISTS
-- sur la question anglaise, la sous-requete etant enveloppee dans une table derivee
-- pour contourner la restriction MySQL 1093. Meme idiome que
-- new-evaluations-entity-types.sql. Un second passage n'insere rien.
--
-- CATEGORIE 45, « Movies - Recognition & Famous Lists Queries », celle de
-- l'evaluation 44.
--
-- IS_SAMPLE = 0 : ces deux questions sont des instruments de mesure, pas des
-- questions de vitrine. La vitrine reste servie par l'evaluation 44.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. PRE-VOL. A lancer EN PREMIER. Doit rendre zero ligne.
--    Une ligne ici signifie que la question est deja dans la banque et que la
--    section 2 la sautera, ce qui est la garde qui fait son travail.
-- ---------------------------------------------------------------------------
SELECT '0. Pre-vol, doit rendre zero ligne' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 60) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'What is in the Criterion Collection?',
  'Movies and series in the Criterion Collection'
);

-- ---------------------------------------------------------------------------
-- 1. LA VERITE TERRAIN, a lire avant de conclure quoi que ce soit d'un rouge.
--    La collection doit porter des series. Au 2026-09-16 : 11 series, 8 portant
--    un numero de tranche. Si SERIE_COUNT valait zero, les deux evaluations
--    seraient rouges pour une raison de donnee et non de requete.
-- ---------------------------------------------------------------------------
SELECT '1. La collection porte-t-elle des series ?' AS SECTION;

SELECT c.ID_T2S_COLLECTION, c.COLLECTION_NAME, c.MOVIE_COUNT, c.SERIE_COUNT,
       COUNT(sc.ID_SERIE) AS SERIES_DANS_LA_JONCTION
FROM T_WC_T2S_COLLECTION c
LEFT JOIN T_WC_T2S_SERIE_COLLECTION sc ON sc.ID_T2S_COLLECTION = c.ID_T2S_COLLECTION
WHERE c.COLLECTION_NAME = 'The Criterion Collection'
GROUP BY c.ID_T2S_COLLECTION, c.COLLECTION_NAME, c.MOVIE_COUNT, c.SERIE_COUNT;

-- ---------------------------------------------------------------------------
-- 2. LES DEUX INSERT.
-- ---------------------------------------------------------------------------

-- A. Aucun mot de type. Le temoin de FASTAPI-TEXT2SQL-264. Attendu ROUGE.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, LONG_DESC)
SELECT 'What is in the Criterion Collection?',
       'Qu''y a-t-il dans la Collection Criterion ?',
       1, 0, 45, 0, CURDATE(), NOW(),
       'T_WC_T2S_SERIE_COLLECTION',
       'Temoin de FASTAPI-TEXT2SQL-264. La question demande le contenu sans nommer aucun type, le prompt exige donc les deux. Attendue ROUGE tant que la garde d''entite de reponse ne sait pas dire movie_serie et regenere vers T_WC_T2S_MOVIE. A lire avec sa jumelle, qui nomme les deux types et doit etre verte : c''est l''ecart entre les deux qui demontre le defaut.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'What is in the Criterion Collection?') AS existing);

-- B. Les deux types nommes. Le controle. Attendu VERT.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, LONG_DESC)
SELECT 'Movies and series in the Criterion Collection',
       'Films et series de la Collection Criterion',
       1, 0, 45, 0, CURDATE(), NOW(),
       'T_WC_T2S_SERIE_COLLECTION',
       'Controle de la paire FASTAPI-TEXT2SQL-264. La question nomme les deux types, la garde d''entite de reponse n''a donc rien a corriger et l''UNION sort au premier coup. Verifie manuellement le 2026-09-02 dans la recette de -237, jamais note par l''evaluateur avant aujourd''hui. Attendue VERTE : si elle est rouge, le defaut n''est pas celui que -264 decrit.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Movies and series in the Criterion Collection') AS existing);

-- ---------------------------------------------------------------------------
-- 3. APRES. Les deux lignes doivent exister, categorie 45, avec leur assertion
--    de forme et ASSERTIONS_QUERY_RESULT a NULL.
-- ---------------------------------------------------------------------------
SELECT '3. Etat apres insertion' AS SECTION;

SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY,
       LEFT(QUESTION, 50) AS QUESTION,
       ASSERTIONS_SQL_QUERY,
       ASSERTIONS_QUERY_RESULT AS DOIT_ETRE_NULL
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'What is in the Criterion Collection?',
  'Movies and series in the Criterion Collection'
);

-- ---------------------------------------------------------------------------
-- 4. PLUS TARD, une fois -264 livre et les deux evaluations vertes.
--    Relever les lignes reellement rendues par la question A, puis poser une
--    assertion de contenu qui verrouille la presence d'au moins une serie. Ne
--    PAS ecrire cette assertion avant d'avoir vu la page : l'ordre d'une UNION
--    Criterion doit se faire sur ID_CRITERION_SPINE, quinzieme colonne du
--    contrat, les NULL pousses en fin de liste. Tant que ce tri n'est pas
--    confirme, toute liste d'identifiants est une hypothese.
--
--    UPDATE T_WC_T2S_EVALUATION
--    SET ASSERTIONS_QUERY_RESULT = 'ID_SERIE IN (<une serie vue sur la page>)'
--    WHERE QUESTION = 'What is in the Criterion Collection?';
-- ---------------------------------------------------------------------------
