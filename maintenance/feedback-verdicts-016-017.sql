-- Verdicts on user feedback #16 and #17 (t2s-front, API 1.1.20, 2026-11-16): a pie asked by name.
-- Voie 1: T_WC_T2S_FEEDBACK is agent-writable. Writes 2 rows. Both stay open (analysed), so the API
-- keeps bypassing the cache for these two questions until FASTAPI-TEXT2SQL-411 ships.
-- Evidence: logs 20261116-112907 and -113352, replay of 2026-11-17 on Blue (8 calls), ground truth
-- feedback-016-017-pie-ground-truth-20261117.txt, evaluations 2942 to 2945.

UPDATE T_WC_T2S_FEEDBACK SET
  ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'sql_generation : with "représente par un camembert" the SQL lists his films with a per-row black-and-white flag (50 rows, value-cards; replay card-grid, also in English and with "Show it as a pie chart"), so no share is built. Without the pie the same question gives one row, 0.76, share-bar. Truth: 44 of the 61 films he directed (0.72).',
  TICKET_ID = 'FASTAPI-TEXT2SQL-411',
  EVALUATION_IDS = '2942',
  TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 16 AND ANALYSIS_STATUS = 'new';

UPDATE T_WC_T2S_FEEDBACK SET
  ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'sql_generation : with "représente par un camembert" the SQL lists the winners with a French / other category per row (50 rows, ranked-bars; replay value-cards with a share repeated per row, card-grid in English). Without the pie, the award row with the share among its columns (fact-card, eval 2944). Truth: Palme d''Or 84 films, 40 with a French production country.',
  TICKET_ID = 'FASTAPI-TEXT2SQL-411',
  EVALUATION_IDS = '2943,2944',
  TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 17 AND ANALYSIS_STATUS = 'new';

SELECT ID_FEEDBACK, ANALYSIS_STATUS, TICKET_ID, EVALUATION_IDS, LEFT(ANALYSIS_NOTE, 80) AS NOTE_START, TIM_ANALYSED
FROM T_WC_T2S_FEEDBACK WHERE ID_FEEDBACK IN (16, 17);
