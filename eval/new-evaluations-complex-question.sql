-- ============================================================================
-- Evaluations pour les questions qui passent par le modele complexe
-- ============================================================================
--
-- SECTIONS 0 A 2 APPLIQUEES le 2026-08-27 (INSERT charges en base, pas encore
-- executes ni exportes en JSON). SECTIONS 3 ET 4 A LANCER. 3 evaluations, anglais et francais,
-- trois categories differentes. Couvre FASTAPI-TEXT2SQL-222 et -223.
--
-- CE QUI S'EST PASSE
-- Trois questions decrivant une personne sans la nommer ont ete lancees le
-- 2026-08-27 en preparant la video #6. Elles ont produit la mesure suivante :
--
--   question                                   exec SQL     total    resultat
--   ----------------------------------------   ---------   -------   ----------------
--   psychiatre qui est un cannibale             100.64 s    112.59 s  Anthony Hopkins
--   film du requin puis de l archeologue          0.009 s     19.12 s  Steven Spielberg
--   reine qui a refuse de se marier              98.68 s    106.60 s  RIEN
--
-- Les trois premieres requetes rendent zero ligne. La difference de cout tient
-- entierement a la forme du predicat : une egalite sur colonne indexee repond en
-- neuf millisecondes, un LIKE a joker en tete fait lire toute la table des credits.
-- data/text_to_sql.md:752 interdit deja le LIKE, mais la ligne 22 interdit au
-- modele d abandonner, et une description comme "un psychiatre cannibale" n a
-- aucune chaine exacte a egaler : le prompt prescrit donc la violation.
--
-- LES TROIS QUESTIONS ORDONNEES, POSEES AVANT D ECRIRE CE FICHIER
--   * Une question de la banque couvre-t-elle le cas ? Non. Aucune fiche ne
--     contient "cannibal", "psychiatrist" ni "archaeologist" sur l export du
--     2026-08-27.
--   * Porte-t-elle une assertion ? Sans objet, il n y a pas de question.
--   * Une assertion existante aurait-elle attrape CE defaut ? Non. Sur les 38
--     fiches qui portent une ASSERTIONS_SQL_QUERY, toutes sont des assertions
--     POSITIVES sur une colonne ou une valeur attendue. Aucune ne verifie ce que
--     le SQL ne doit PAS contenir.
--
-- ============================================================================
-- LE POINT CONTRE-INTUITIF, ET C EST LE COEUR DU FICHIER
-- ============================================================================
-- L assertion de forme du SQL n a de sens QUE sur la question 2, et il faut
-- comprendre pourquoi avant de "completer" les deux autres.
--
-- Le harnais applique la regex sur response_json["sql_query"] (text2sql-eval.py,
-- section "SQL query regex evaluation"). Or quand la reprise par le modele fort
-- REUSSIT, main.py renvoie la reponse INTERNE (commentaire explicite ligne 2524),
-- donc sql_query porte la requete FINALE, propre, du type
-- PERSON_NAME = 'Anthony Hopkins'. Le LIKE fautif de la premiere passe a disparu
-- du champ observable.
--
--   question 1 (Hopkins)    reprise reussie  -> sql_query final propre  -> une
--                           assertion negative serait VERTE aujourd hui, avant
--                           tout correctif. Instrument qui ment.
--   question 3 (Spielberg)  idem.
--   question 2 (la reine)   reprise ECHOUE (le modele fort declare la question
--                           trop vague) -> sql_query reste la requete FAUTIVE ->
--                           l assertion negative est ROUGE aujourd hui et ne
--                           passera au vert que quand -223 sera deploye.
--
-- C est la lecon -216 : une evaluation verte pour la mauvaise raison coute plus
-- cher qu une evaluation absente. NE PAS ajouter d ASSERTIONS_SQL_QUERY aux
-- questions 1 et 3 sans avoir relu ce paragraphe.
--
-- CE QUI S EST PASSE ENSUITE, LE 2026-08-27 AU SOIR
-- -223 etait deja deploye. La ligne de base rouge est donc PERDUE, et la fiche 2
-- naitra verte. Ce n est pas grave, mais il faut le savoir : elle ne prouve plus
-- que le garde-fou a corrige quelque chose, elle garde qu il ne regresse pas.
-- Verifie a la trace le meme soir : LIKE rejete avant execution, 0,006 s au lieu
-- de 98,68 s, 15,14 s bout en bout au lieu de 106,60 s.
-- Et la reprise a RESOLU la question au lieu d abandonner, ce qui invalide
-- l assertion COUNT(*) = 0 de la fiche 2. D ou la section 3.
--
-- ============================================================================
-- LE PIEGE MYSQL DE L ANTISLASH
-- ============================================================================
-- Par defaut MySQL/MariaDB traite l antislash comme un caractere d echappement
-- DANS les litteraux de chaine. Ecrit simple, '\A' deviendrait 'A', '\b' un
-- backspace invisible et '\s' un 's'. La regex serait donc silencieusement
-- detruite a l insertion. Les antislashs sont doubles ci-dessous pour cette
-- raison.
--   ATTENTION : si le serveur tourne avec NO_BACKSLASH_ESCAPES, le doublement
--   serait au contraire conserve tel quel et casserait la regex dans l autre
--   sens. La section 2 affiche la valeur STOCKEE, precisement pour trancher a
--   l oeil. Elle doit montrer un seul antislash devant A, b et s.
--
-- ASSERTIONS_ENTITY_EXTRACTION LAISSEE NULLE
-- La methode maison demande trois passes dans chaque langue, et ces questions
-- n ont ete lancees qu une fois, en anglais, a la main. On n assertionne pas ce
-- qui n a pas ete joue.
--
-- LES IDENTIFIANTS SONT LUS, PAS MEMORISES
-- Anthony Hopkins 4173 et Steven Spielberg 488, releves et fournis par Philippe
-- le 2026-08-27. Un nombre exact affirme sans source n est jamais rouvert, c est
-- le cas le plus dangereux : voir l en-tete de new-evaluations-person-alias.sql.
--
-- GARDE DE RE-EXECUTION
-- Chaque INSERT est un INSERT ... SELECT garde par NOT EXISTS sur la question
-- anglaise, enveloppe dans une table derivee pour que l erreur MySQL 1093 ne se
-- declenche pas. Meme idiome que new-evaluations-person-alias.sql ; comme lui, ce
-- fichier n a PAS ete execute contre un serveur depuis cette machine, et n est
-- valide que syntaxiquement.
--
-- COMMENT LANCER
--   Section 0, puis les trois INSERT, puis la section 2 pour verifier la regex.
--   mysql <db> < eval/new-evaluations-complex-question.sql
--   Puis la phase 31 pour rafraichir l export JSON, et les phases 11 + 20 pour
--   jouer et scorer. Rappel : la question 2 doit etre jouee AVANT le deploiement
--   de -223.


-- ---------------------------------------------------------------------------
-- 0. Pre-vol. A lancer EN PREMIER. Doit rendre zero ligne.
--    Une ligne ici signifie que la question est deja dans la banque et que la
--    section 1 la sautera, ce qui est la garde qui fait son travail.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY, LEFT(QUESTION, 70) AS QUESTION
FROM T_WC_T2S_EVALUATION
WHERE QUESTION IN (
  'Who is the actor who plays the psychiatrist which is a cannibal?',
  'Who is the actress who played the queen who refused to marry?',
  'Who is the director who made the film about the shark, and then the one about the archaeologist?'
);


-- ---------------------------------------------------------------------------
-- 1. Les nouvelles evaluations
-- ---------------------------------------------------------------------------

-- ===== categorie 32 : Persons - Character Queries =====

-- 1/3. La question qui a coute 100,64 s d execution pour zero ligne, puis a ete
-- rattrapee par le modele fort. On assertionne l IDENTITE RENDUE, pas le chemin :
-- que la reponse vienne de la premiere passe ou de la reprise, l utilisateur doit
-- obtenir Anthony Hopkins. Pas d assertion de forme du SQL ici, voir l en-tete.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is the actor who plays the psychiatrist which is a cannibal?',
       'Qui est l acteur qui joue le psychiatre qui est un cannibale ?',
       1, 0, 32, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_PERSON IN (4173)',
       'Description d un personnage sans nommer ni la personne ni le film. Mesure du 2026-08-27 : le generateur a ecrit CAST_CHARACTER LIKE deux fois avec joker en tete, la base a lu toute la table des credits en 100,64 s pour rendre zero ligne, et la reprise par le modele fort a resolu Anthony Hopkins en une seconde. Assertion sur l identite rendue, valable avant comme apres FASTAPI-TEXT2SQL-223.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is the actor who plays the psychiatrist which is a cannibal?') AS existing);


-- ===== categorie 54 : Persons - Questions with no answer =====

-- 2/3. LA SEULE QUI MESURE LE DEFAUT. La reprise echoue ici (le modele fort
-- declare la question trop vague), donc sql_query conserve la requete fautive et
-- l assertion de forme mord vraiment. Rouge aujourd hui, verte apres -223.
-- La regex refuse un LIKE a joker en tete, ancree par \A parce que le harnais
-- utilise re.search : sans ancre, la lookahead negative serait satisfaite plus
-- loin dans la chaine et l assertion passerait toujours.
-- Verifiee sur 7 cas le 2026-08-27, dont DISLIKE_COUNT, que \b ecarte.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is the actress who played the queen who refused to marry?',
       'Qui est l actrice qui a joue la reine qui a refuse de se marier ?',
       1, 0, 54, 0, CURDATE(), NOW(),
       '(?is)\\A(?!.*\\bLIKE\\s*&#039;%)',
       'COUNT(*) = 0',
       'Question sans reponse unique, et le seul des trois cas ou la reprise par le modele fort abandonne : elle a repondu que plusieurs films montrent une reine qui refuse de se marier. Consequence, sql_query conserve la requete de premiere passe, CAST_CHARACTER LIKE deux fois avec joker en tete, 98,68 s d execution pour zero ligne et 106,60 s bout en bout sans aucune reponse. L assertion de forme du SQL est donc rouge tant que FASTAPI-TEXT2SQL-223 n est pas deploye, et c est exactement ce qu elle doit mesurer. A jouer AVANT le deploiement pour enregistrer la ligne de base.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is the actress who played the queen who refused to marry?') AS existing);


-- ===== categorie 16 : Persons - Basic queries =====

-- 3/3. LE TEMOIN POSITIF, et il n y a rien a y attraper aujourd hui : c est le but.
-- Ici le generateur a traduit la description en TITRES, MOVIE_TITLE = 'Jaws' et
-- = 'Indiana Jones', donc egalite sur colonne indexee et 0,009 s d execution. Si
-- un jour une correction du prompt pousse le modele a revenir au texte libre sur
-- ce type de question, cette fiche vire au rouge alors que les deux autres
-- resteraient vertes.
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE, ID_T2S_EVALUATION_CATEGORY, DELETED,
   DAT_CREAT, TIM_UPDATED, ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 'Who is the director who made the film about the shark, and then the one about the archaeologist?',
       'Qui est le realisateur qui a fait le film sur le requin, puis celui sur l archeologue ?',
       1, 0, 16, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_PERSON IN (488)',
       'Meme geste que la fiche du psychiatre cannibale, decrire une personne sans la nommer, mais le generateur reconnait les FILMS et ecrit des egalites sur MOVIE_TITLE au lieu de fouiller CAST_CHARACTER. Resultat mesure le 2026-08-27 : 0,009 s d execution contre 100,64 s, soit un rapport de 1 a 11 000 pour la meme issue, zero ligne suivie de la reprise. Aucun titre exact "Indiana Jones" n existe, donc la requete rapide etait fausse ; elle a simplement eu la politesse de le prouver instantanement. Temoin de non-regression du bon chemin.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM (SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
                 WHERE QUESTION = 'Who is the director who made the film about the shark, and then the one about the archaeologist?') AS existing);


-- ---------------------------------------------------------------------------
-- 2. Verification de la regex STOCKEE. A lancer APRES les INSERT.
--    La colonne DOIT afficher :  (?is)\A(?!.*\bLIKE\s*&#039;%)
--    Un seul antislash devant A, b et s.
--      deux antislashs      -> le serveur est en NO_BACKSLASH_ESCAPES, retirer le
--                              doublement dans l INSERT 2 et rejouer.
--      A, s, et un trou     -> le doublement a saute, les antislashs ont ete
--                              manges a l insertion, meme correction en sens
--                              inverse.
-- ---------------------------------------------------------------------------
SELECT ID_T2S_EVALUATION,
       LEFT(QUESTION, 60) AS QUESTION,
       ASSERTIONS_SQL_QUERY,
       LENGTH(ASSERTIONS_SQL_QUERY) AS LONGUEUR
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Who is the actress who played the queen who refused to marry?';


-- ---------------------------------------------------------------------------
-- 3. Correction de la fiche 2, ecrite le 2026-08-27 au soir apres verification
--    du garde-fou -223 en production. A lancer si la section 1 a deja ete jouee.
--
--    CE QUI A CHANGE. La fiche supposait que la reprise par le modele fort
--    abandonnait toujours sur cette question. Mesure du soir : elle resout
--    Cate Blanchett, qui a joue Elisabeth I dans Elizabeth, en 15,14 s contre
--    106,60 s et aucune reponse le matin. Meme question, meme prompt de reprise,
--    sortie differente : non-determinisme d echantillonnage.
--
--    TROIS CORRECTIONS. La categorie 54 « questions sans reponse » est fausse,
--    la question en a une et meme plusieurs legitimes (Judi Dench a joue la meme
--    reine). L assertion COUNT(*) = 0 est fausse. Et aucune assertion de resultat
--    ne la remplace : asserter une actrice precise serait vert pour la mauvaise
--    raison sur une question volontairement ambigue.
-- ---------------------------------------------------------------------------
UPDATE T_WC_T2S_EVALUATION
SET ID_T2S_EVALUATION_CATEGORY = 32,
    ASSERTIONS_QUERY_RESULT = NULL,
    LONG_DESC = 'Description d un personnage sans nommer ni la personne ni le film, sur une question volontairement ambigue : plusieurs actrices ont joue une reine qui refuse de se marier. Mesure du 2026-08-27 : avant le garde-fou FASTAPI-TEXT2SQL-223, le generateur ecrivait CAST_CHARACTER LIKE deux fois avec joker en tete, 98,68 s d execution pour zero ligne et 106,60 s bout en bout sans aucune reponse. Apres le garde-fou, 0,006 s d execution et 15,14 s bout en bout, la reprise resolvant Cate Blanchett. AUCUNE assertion de resultat ici, volontairement : la reponse est legitimement non deterministe sur une question ambigue. Seule l assertion de forme du SQL est posee, et elle est UNILATERALE : son rouge signale que le SQL fautif a atteint la reponse, donc une regression du garde-fou ; son vert ne prouve rien, puisque le SQL final propre le satisfait aussi.',
    TIM_UPDATED = NOW()
WHERE QUESTION = 'Who is the actress who played the queen who refused to marry?';

-- Verification. Doit rendre une ligne, categorie 32, ASSERTIONS_QUERY_RESULT a NULL,
-- et la regex intacte avec UN SEUL antislash devant A, b et s.
SELECT ID_T2S_EVALUATION, ID_T2S_EVALUATION_CATEGORY,
       ASSERTIONS_SQL_QUERY, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION
WHERE QUESTION = 'Who is the actress who played the queen who refused to marry?';


-- ---------------------------------------------------------------------------
-- 4. Purge des executions, pour rejouer sur 1.1.18 sans etre saute
--
--    POURQUOI C EST NECESSAIRE. text2sql-eval.py filtre les executions
--    existantes sur API_VERSION plus les trois modeles (lignes 412 et 452) et
--    saute les combinaisons deja presentes. Comme strapiversion n a
--    DELIBEREMENT pas ete incremente pour -223, une execution anterieure sur
--    1.1.18 empeche le rejeu et masquerait le correctif.
--
--    A LANCER AVANT les phases 11 et 20. Verifier d abord ce qui va disparaitre.
-- ---------------------------------------------------------------------------
SELECT ID_ROW, ID_T2S_EVALUATION, LANG, API_VERSION, TEXT2SQL_MODEL
FROM T_WC_T2S_EVALUATION_EXECUTION
WHERE ID_T2S_EVALUATION IN (
  SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
  WHERE QUESTION IN (
    'Who is the actor who plays the psychiatrist which is a cannibal?',
    'Who is the actress who played the queen who refused to marry?',
    'Who is the director who made the film about the shark, and then the one about the archaeologist?'
  )
);

-- Puis, une fois la liste ci-dessus jugee correcte :
-- DELETE FROM T_WC_T2S_EVALUATION_EXECUTION
-- WHERE ID_T2S_EVALUATION IN (
--   SELECT ID_T2S_EVALUATION FROM T_WC_T2S_EVALUATION
--   WHERE QUESTION IN (
--     'Who is the actor who plays the psychiatrist which is a cannibal?',
--     'Who is the actress who played the queen who refused to marry?',
--     'Who is the director who made the film about the shark, and then the one about the archaeologist?'
--   )
-- );
