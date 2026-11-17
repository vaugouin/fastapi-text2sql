-- Verdicts on user feedback #14 and #15 (voice-agent 1.15.6, API 1.1.20, video shoot of 2026-11-15).
-- Voie 1: T_WC_T2S_FEEDBACK is agent-writable. Writes 2 rows. Both stay open (analysed), so the API keeps
-- bypassing the cache for these two questions until the client fixes ship.

UPDATE T_WC_T2S_FEEDBACK SET
  ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'presentation : the API is right (value-cards, focus_columns BUDGET and REVENUE, request 00709700). The Values view shows only the first focus column (Budget); the table lists 13 columns in base order, technical ones first, budget and revenue last under the webcam overlay. The agent had first switched the previous result (no budget column) to a table instead of searching again.',
  TICKET_ID = 'VOICE-AGENT-273',
  TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 14 AND ANALYSIS_STATUS = 'new';

UPDATE T_WC_T2S_FEEDBACK SET
  ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'presentation : the API is right (map, 50 countries, United States 3,137, request bc8db668). The client draws the world map about 450 px wide in a panel of about 800 px, legend in small type. Zoom is VOICE-AGENT-269. The answer took 18.7 s (complex retry, year constraint added), not the subject of the comment.',
  TICKET_ID = 'VOICE-AGENT-274',
  TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 15 AND ANALYSIS_STATUS = 'new';

SELECT ID_FEEDBACK, ANALYSIS_STATUS, TICKET_ID, LEFT(ANALYSIS_NOTE, 80) AS NOTE_START, TIM_ANALYSED
FROM T_WC_T2S_FEEDBACK WHERE ID_FEEDBACK IN (14, 15);
