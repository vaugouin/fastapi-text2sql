-- ============================================================================
-- Eval 44 « Criterion Collection » : deux reponses sont justes, l'assertion doit
-- les accepter toutes les deux
-- ============================================================================
--
-- NON APPLIQUE. Un seul UPDATE, section 2.
--
-- LE PROBLEME. La question est un nom de collection NU. Elle peut se lire de deux
-- facons, et les deux sont defendables : « montre-moi la collection » (la fiche,
-- qui porte MOVIE_COUNT, SERIE_COUNT, l'affiche et le resume) ou « montre-moi ce
-- qu'elle contient » (les oeuvres). L'API repond aujourd'hui l'une OU l'autre
-- selon la langue, et l'evaluation ne notait juste que la seconde.
--
-- MESURE, runs 1.1.18 des 2026-08-30 et 2026-08-31 :
--
--   EN  'Criterion Collection'   -> result_entity movie      -> 100 films  -> 1.0
--   FR  'Collection Criterion'   -> result_entity collection -> 1 ligne    -> 0.0
--
-- Le cote francais rend la fiche (ID_T2S_COLLECTION 5035) et c'etait compte comme
-- une mauvaise reponse. Ce n'en est pas une.
--
-- CE N'EST PAS UN CAS ISOLE, ET C'EST CE QUI TRANCHE. Trois autres evaluations
-- posent EXACTEMENT la meme forme de question, un nom de collection nu, et elles
-- attendent la FICHE :
--
--   1064  'Tora San collection'    -> ID_T2S_COLLECTION IN (1831)  -> vert
--   2158  'James Bond collection'  -> ID_T2S_COLLECTION IN (84)    -> vert
--    444  'Flamenco trilogy'       -> ID_T2S_COLLECTION IN (59)    -> rouge, mais
--                                     pour une raison de resolution, zero ligne
--
-- La banque enferme donc les deux reponses a la fois, et rien dans les questions
-- ne les distingue. Faire trancher le prompt en faveur du contenu ferait passer
-- 1064 et 2158 au rouge. Accepter les deux cote assertion ne casse rien et dit la
-- verite sur la question.
--
-- LE OR FONCTIONNE DEJA, VERIFIE PAR EXECUTION LE 2026-09-16. Quand une colonne
-- manque, _evaluate_in_assertion rend proprement passed=False (« Column does not
-- exist ») au lieu de lever une exception, donc False OR True vaut True. Teste sur
-- les trois formes de reponse possibles :
--
--   fiche collection      -> True
--   liste de films        -> True
--   UNION films+series    -> True   (via le pont de schema unifie, qui synthetise
--                                    ID_MOVIE depuis ID_CONTENT + CONTENT_TYPE)
--
-- Le troisieme cas est celui de demain : l'assertion survit au jour ou la requete
-- deviendra une UNION (FASTAPI-TEXT2SQL-264).
--
-- ⚠ NE PAS AJOUTER D'AUTRE OPERATEUR A CETTE ASSERTION. L'analyseur n'a ni
-- precedence ni parentheses de groupement (EVALUATIONS-010 et -011). Un seul OR
-- entre deux operandes est le seul terrain sur : « A OR B AND C » serait evalue
-- comme « (A OR B) AND C ».
--
-- ⚠ CE QUE CE CHANGEMENT COUTE, ET IL FAUT LE SAVOIR. En acceptant les deux
-- reponses, l'evaluation 44 cesse de signaler l'asymetrie anglais/francais : les
-- deux cotes passeront au vert. Cette asymetrie est FASTAPI-TEXT2SQL-265 et ne
-- vit plus que dans son ticket, avec les exports du 30 et du 31 aout pour preuve.
-- De meme, 44 ne temoigne plus de FASTAPI-TEXT2SQL-264 : ce role passe a la paire
-- de questions de new-evaluations-criterion-typeless-content.sql.
--
-- ⚠ ASSERTION_REFRESH_SQL A DEJA ETE MIS A NULL par Philippe le 2026-09-16. Ne pas
-- le remettre : les vingt identifiants alimentent une ligne defilante de la vitrine
-- voice-agent, et un rafraichissement nocturne la ferait bouger sous la
-- demonstration. Ils sont justes, verifie sur le run du 2026-08-31 : ce sont
-- exactement les vingt PREMIERES lignes rendues, positions 1 a 20, dans l'ordre des
-- tranches Criterion.
--
-- ⚠ COLLATION. Lancer avec --force si une comparaison passant par un CAST rend
-- ERROR 1267, comme pour fix-44-criterion-spine-null.sql.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- 0. AVANT. A lire avant de modifier quoi que ce soit.
--    ASSERTION_REFRESH_SQL doit deja valoir NULL. S'il ne l'est pas, arreter ici
--    et le mettre a NULL d'abord, sinon le processus 70 ecrasera l'assertion
--    ecrite en section 2 des son prochain passage.
-- ---------------------------------------------------------------------------
SELECT '0. Etat avant correction' AS SECTION;

SELECT ID_T2S_EVALUATION,
       LEFT(QUESTION, 40)                 AS QUESTION,
       LEFT(QUESTION_FR, 40)              AS QUESTION_FR,
       ASSERTIONS_QUERY_RESULT,
       ASSERTIONS_SQL_QUERY,
       ASSERTION_REFRESH_SQL              AS REFRESH_SQL_DOIT_ETRE_NULL,
       ASSERTION_REFRESH_LAST,
       IS_SHOWCASE
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 0b. LES TROIS JUMELLES. Elles ne sont pas modifiees par ce fichier ; elles sont
--     affichees pour que l'on voie de ses yeux que la meme forme de question
--     attend ailleurs la fiche, et donc pourquoi on n'impose pas le contenu.
-- ---------------------------------------------------------------------------
SELECT '0b. Les trois evaluations jumelles, laissees intactes' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 40) AS QUESTION,
       LEFT(ASSERTIONS_QUERY_RESULT, 60) AS ASSERTION
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (444, 1064, 2158);

-- ---------------------------------------------------------------------------
-- 1. L'IDENTIFIANT DE LA COLLECTION, verifie plutot que recopie.
--    Doit rendre 5035. Si un autre nombre sort, corriger la section 2 avant de
--    la lancer : l'identifiant vient de l'export du run FR du 2026-08-31.
-- ---------------------------------------------------------------------------
SELECT '1. Identifiant de la collection Criterion' AS SECTION;

SELECT ID_T2S_COLLECTION, COLLECTION_NAME, MOVIE_COUNT, SERIE_COUNT
FROM T_WC_T2S_COLLECTION
WHERE COLLECTION_NAME = 'The Criterion Collection';

-- ---------------------------------------------------------------------------
-- 2. LA CORRECTION. Deux gestes.
--
--    (a) ASSERTIONS_QUERY_RESULT accepte desormais la fiche OU le contenu. La
--        liste des vingt identifiants est reprise MOT POUR MOT, sans rien y
--        changer : elle est juste et la vitrine s'appuie dessus.
--    (b) COMMENT explique pourquoi, parce qu'une assertion permissive sans note
--        finit par etre prise pour un relachement.
-- ---------------------------------------------------------------------------

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT = 'ID_T2S_COLLECTION IN (5035) OR ID_MOVIE IN (777, 346, 940, 7857, 147, 648, 10971, 10835, 11782, 36040, 490, 11031, 274, 31372, 31374, 31378, 5336, 26031, 25504, 14924)',
    LONG_DESC = CONCAT(
      '2026-09-16. DEUX REPONSES SONT JUSTES et l''assertion les accepte toutes les deux, ',
      'par un OR. La question est un nom de collection NU : elle peut demander la FICHE de la ',
      'collection (ID_T2S_COLLECTION 5035, qui porte MOVIE_COUNT et SERIE_COUNT) ou son CONTENU ',
      '(les oeuvres). L''API rendait la fiche en francais et les films en anglais, et le francais ',
      'etait compte faux a tort. Trois evaluations jumelles posent la meme forme de question et ',
      'attendent la fiche : 1064 Tora San, 2158 James Bond, 444 Flamenco. ',
      'LISTE FIGEE : ASSERTION_REFRESH_SQL est a NULL volontairement. Ces vingt ID alimentent une ',
      'ligne defilante de la vitrine voice-agent, un rafraichissement nocturne la ferait bouger ',
      'sous la demonstration. Ils sont justes, verifie sur le run 1.1.18 du 2026-08-31 : ce sont ',
      'exactement les vingt PREMIERES lignes rendues, positions 1 a 20, dans l''ordre des tranches ',
      'Criterion. NE PAS LES RECALCULER. ',
      'NE PAS AJOUTER D''AUTRE OPERATEUR : l''analyseur d''assertions n''a ni precedence ni ',
      'parentheses de groupement, voir EVALUATIONS-010 et -011. ',
      'CE QUE CETTE EVAL NE TESTE PLUS : l''asymetrie EN/FR (FASTAPI-TEXT2SQL-265) et l''absence ',
      'des onze series (FASTAPI-TEXT2SQL-264), les deux cotes passant desormais au vert. Le temoin ',
      'de -264 est la paire de questions Criterion sans mot de type, ajoutee le meme jour.'
    ),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 3. APRES. L'assertion doit commencer par ID_T2S_COLLECTION IN (5035) OR et
--    contenir les vingt identifiants inchanges, 777 en tete.
-- ---------------------------------------------------------------------------
SELECT '3. Etat apres correction' AS SECTION;

SELECT ID_T2S_EVALUATION,
       ASSERTIONS_QUERY_RESULT,
       ASSERTION_REFRESH_SQL AS DOIT_RESTER_NULL,
       LEFT(COMMENT, 120) AS DEBUT_DU_COMMENTAIRE
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION = 44;

-- ---------------------------------------------------------------------------
-- 4. CONTROLE. Rejouer l'evaluation 44 dans LES DEUX langues. Les deux doivent
--    desormais etre vertes, l'anglais par la branche ID_MOVIE, le francais par la
--    branche ID_T2S_COLLECTION. Si le francais reste rouge, ce n'est plus un
--    probleme d'assertion : lire le SQL rendu.
-- ---------------------------------------------------------------------------
