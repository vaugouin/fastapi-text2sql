-- Regression evaluations for FASTAPI-TEXT2SQL-250 through -254.
-- Not applied automatically. Run against the evaluation database before export.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO T_WC_T2S_EVALUATION
  (ID_T2S_EVALUATION, QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE,
   ID_T2S_EVALUATION_CATEGORY, DELETED, DAT_CREAT, TIM_UPDATED,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 2489,
       'a surveillance expert records a couple and fears they will be killed',
       'un expert en surveillance enregistre un couple et craint qu''ils ne soient tués',
       1, 0, 29, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (592)',
       'FASTAPI-TEXT2SQL-250 à -254. La première passe ne doit jamais déduire The Conversation de mémoire. La résolution complexe doit identifier le film de 1974.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2489
);

INSERT INTO T_WC_T2S_EVALUATION
  (ID_T2S_EVALUATION, QUESTION, QUESTION_FR, IS_EVAL, IS_SAMPLE,
   ID_T2S_EVALUATION_CATEGORY, DELETED, DAT_CREAT, TIM_UPDATED,
   ASSERTIONS_QUERY_RESULT, LONG_DESC)
SELECT 2490,
       'a man lends his flat to his boss for his affairs and his boss dates the woman he has a crush on',
       'un homme prête son appartement à son patron pour ses aventures et son patron fréquente la femme dont il est amoureux',
       1, 0, 29, 0, CURDATE(), NOW(),
       'COUNT(*) &gt; 0 AND ID_MOVIE IN (284)',
       'FASTAPI-TEXT2SQL-250 à -254. La première passe ne doit jamais déduire The Apartment de mémoire. La résolution complexe doit identifier le film de Billy Wilder sorti en 1960.'
FROM DUAL WHERE NOT EXISTS (
  SELECT 1 FROM T_WC_T2S_EVALUATION WHERE ID_T2S_EVALUATION = 2490
);
