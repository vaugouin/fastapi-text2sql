-- ============================================================================
-- Renforcement des assertions 2486 et 2487, après la mesure du 2026-09-10
-- ============================================================================
--
-- NON ENCORE APPLIQUÉ. Suite de new-evaluations-award-flattening.sql, dont
-- l'exécution du 2026-09-10 a rendu deux enseignements que ce fichier exploite.
--
-- CE QUE LA MESURE A PROUVÉ, et c'est l'essentiel : la correction amont tient.
-- T_WC_T2S_AWARD ne contient, pour les deux témoins, que de vraies récompenses.
-- Ni cérémonie, ni œuvre, ni être humain. Cord Jefferson porte UNE récompense,
-- « Academy Award for Best Writing, Adapted Screenplay », là où l'aplatissement de
-- V1 en rendait trois. C'est le critère d'acceptation de FASTAPI-TEXT2SQL-238,
-- atteint au nombre près.
--
-- ⚠ CONSÉQUENCE SUR LES ASSERTIONS : mes deux contre-exemples nomment des chaînes
-- ABSENTES de la base. C'est normal et voulu, un contre-exemple nomme ce qui ne
-- doit PAS apparaître, pas ce qui est là. Mais il faut en tirer la conséquence :
-- ces deux assertions ne peuvent plus rien attraper aujourd'hui, elles ne se
-- réveilleront qu'en cas de régression. Le travail réel est fait par le plancher,
-- et `COUNT(*) > 0` est le plancher le plus faible qui soit. La mesure permet
-- maintenant de le remplacer par quelque chose de justifié, ce qu'elle seule
-- pouvait autoriser.
--
-- ============================================================================
-- 1. CORD JEFFERSON, 2486 : le plancher devient une égalité
-- ============================================================================
--
-- Il porte exactement UNE récompense. Le README §4.5 dit que `COUNT(*) == 1`
-- appartient à toute recherche par identifiant, « faute de quoi une requête qui
-- aurait ignoré l'identifiant et rendu cent lignes dont la bonne passerait quand
-- même ». Ici l'argument est plus fort encore : sous l'aplatissement de V1 la
-- réponse comptait TROIS lignes, la récompense, la 96e cérémonie et American
-- Fiction. Une égalité à 1 est donc exactement la frontière entre le défaut et sa
-- correction, et elle discrimine là où `> 0` laisse passer les deux.
--
-- ⚠ CE QUE CETTE ASSERTION COÛTE, à savoir avant de l'écrire : elle devient rouge
-- le jour où Cord Jefferson reçoit un second prix. C'est un vrai coût de
-- maintenance, assumé ici pour une raison précise : ce cas n'est pas une
-- évaluation ordinaire, c'est le TÉMOIN de la migration, et un témoin dont la
-- valeur est un nombre exact vaut mieux qu'un témoin qui accepte tout. Le jour où
-- elle tombe, elle demandera dix secondes de lecture, ce qui est le prix d'une
-- assertion qui mesure vraiment quelque chose.
-- ============================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

SELECT '1. Avant, evaluation 2486' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2486;

UPDATE T_WC_T2S_EVALUATION
SET ASSERTIONS_QUERY_RESULT =
      'COUNT(*) == 1 AND AWARD_NAME NOT IN (''96th Academy Awards'', ''American Fiction'')',
    LONG_DESC = CONCAT(LONG_DESC,
      ' Mesure du 2026-09-10 : la base rend exactement une recompense pour lui, '
      '"Academy Award for Best Writing, Adapted Screenplay". Le plancher COUNT(*) > 0 '
      'est donc remplace par une egalite a 1, qui est la frontiere exacte entre '
      'l''aplatissement de V1, trois lignes, et sa correction, une seule.'),
    TIM_UPDATED = NOW()
WHERE ID_T2S_EVALUATION = 2486;

-- ============================================================================
-- 2. JOHN WILLIAMS, 2487 : le plancher NE BOUGE PAS, et voici pourquoi
-- ============================================================================
--
-- ⚠ MA REQUÊTE DE MESURE ÉTAIT FAUSSE, ET SON RÉSULTAT LE MONTRE. La section 1
-- du fichier précédent groupait sur `PERSON_NAME`, pas sur `ID_PERSON`. Elle a
-- donc fondu en une seule ligne TOUS les hommes nommés John Williams. Les 21
-- récompenses affichées ne sont pas celles d'une personne.
--
-- La liste le trahit d'elle-même, et c'est ce qui m'a mis la puce à l'oreille :
-- un compositeur ne reçoit pas un « National Book Award », ni un « Tony Award for
-- Best Featured Actor in a Play », ni un « Donaldson Award », qui est un prix de
-- théâtre. Ces trois-là appartiennent à d'autres John Williams. Les Oscars, Grammy,
-- Emmy, Saturn de la meilleure musique, Kennedy Center Honors, AFI Life
-- Achievement, Disney Legends et Princesse des Asturies vont bien au compositeur.
--
-- CE QUE CELA INTERDIT : poser un plancher chiffré sur cette évaluation. J'allais
-- écrire `COUNT(*) > 15` en m'appuyant sur les 21 mesurées. L'API, elle, résout la
-- question vers UNE personne, donc rendra le sous-ensemble d'un seul John Williams.
-- Un plancher calibré sur l'agrégat de plusieurs homonymes aurait produit un rouge
-- sur une réponse parfaitement correcte. Le plancher reste donc `COUNT(*) > 0`.
--
-- CE QUE CELA N'ENTAME PAS : le contre-exemple. Que la question soit ambiguë ne
-- change rien à l'invariant qu'elle porte, une liste de prix ne contient jamais un
-- être humain, et c'est vrai de n'importe lequel des John Williams.
--
-- La section 3 ci-dessous compte les homonymes. Elle n'est pas là pour ce ticket
-- mais pour la question qu'elle ouvre : si l'API résout « John Williams » vers le
-- mauvais homme, c'est un défaut de résolution d'entité, distinct de -238, et qui
-- mérite son propre ticket plutôt que d'être absorbé dans celui-ci.
-- ============================================================================

SELECT '2. Evaluation 2487, assertion inchangee' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION, ASSERTIONS_QUERY_RESULT
FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2487;

-- ============================================================================
-- 3. LES HOMONYMES, ce que ma mesure avait fondu en une ligne
-- ============================================================================

SELECT '3. Combien de John Williams, et lequel porte quoi' AS SECTION;

SELECT p.ID_PERSON, p.PERSON_NAME, p.ID_WIKIDATA,
       COUNT(DISTINCT pa.ID_AWARD) AS RECOMPENSES,
       GROUP_CONCAT(DISTINCT a.AWARD_NAME ORDER BY a.AWARD_NAME SEPARATOR ' | ') AS DETAIL
FROM T_WC_T2S_PERSON p
LEFT JOIN T_WC_T2S_PERSON_AWARD pa ON pa.ID_PERSON = p.ID_PERSON
LEFT JOIN T_WC_T2S_AWARD a ON a.ID_AWARD = pa.ID_AWARD
WHERE p.PERSON_NAME = 'John Williams'
GROUP BY p.ID_PERSON, p.PERSON_NAME, p.ID_WIKIDATA
ORDER BY RECOMPENSES DESC;

-- Et le témoin, pour comparaison : un nom sans homonyme.
SELECT p.ID_PERSON, p.PERSON_NAME, p.ID_WIKIDATA,
       COUNT(DISTINCT pa.ID_AWARD) AS RECOMPENSES
FROM T_WC_T2S_PERSON p
LEFT JOIN T_WC_T2S_PERSON_AWARD pa ON pa.ID_PERSON = p.ID_PERSON
WHERE p.PERSON_NAME = 'Cord Jefferson'
GROUP BY p.ID_PERSON, p.PERSON_NAME, p.ID_WIKIDATA;

-- ============================================================================
-- 4. Après
-- ============================================================================

SELECT '4. Etat apres mise a jour' AS SECTION;

SELECT ID_T2S_EVALUATION, LEFT(QUESTION, 45) AS QUESTION,
       ASSERTIONS_QUERY_RESULT, ASSERTION_REFRESH_SQL
FROM T_WC_T2S_EVALUATION
WHERE ID_T2S_EVALUATION IN (2486, 2487)
ORDER BY ID_T2S_EVALUATION;

-- ============================================================================
-- APRÈS. Rejouer la phase 11 puis la phase 20 sur les deux. La phase 20 étant du
-- scoring hors ligne, une assertion corrigée se rejoue sans redépenser un jeton.
--
-- Lire le message avant de conclure sur un rouge, les trois causes se ressemblent
-- dans la colonne de score : colonne absente du résultat (le modèle a nommé la
-- colonne autrement, ce n'est pas un échec de -238), contre-exemple qui remonte
-- vraiment (là c'est le vrai signal), ou plancher en échec (défaut de résolution
-- d'entité). Sur 2486, un `COUNT(*) == 1` en échec avec 3 lignes rendues est la
-- signature exacte de l'aplatissement qui revient.
--
-- ⚠ COLLATION. Lancer avec --force.
-- ============================================================================
