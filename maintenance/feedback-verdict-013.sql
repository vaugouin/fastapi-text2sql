-- Verdict on user feedback #13 (analyse-feedback skill, 2026-11-15).
-- Writes T_WC_T2S_FEEDBACK only (agent-writable). 1 row, analysed: the cache stays bypassed for this question.

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'presentation : the rated answer is right (3 pins Montmartre 3950, Paris 38, Porte des Lilas - Cinema 6585, bounds about 5 km; ground truth maintenance/feedback-013-amelie-locations-20261115.txt), but the voice-agent place map frames at least 160 units of a 2000-unit world outline (about 29 degrees, Western Europe), so the three pins merge into one disc; no zoom control, and the agent has no zoom tool (refused at 12:45:51). Also entity_resolution, same session: the first phrasing "all the Parisian locations for the movie Amelie" failed twice (logs 20261115-124313, -124405): Parisian not extracted as Location_name, literal Paris rejected by the provenance guard, then the stronger model declared authoritative_empty although no SQL ran.',
  TICKET_ID = 'VOICE-AGENT-269, FASTAPI-TEXT2SQL-391', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 13;

SELECT ID_FEEDBACK, ANALYSIS_STATUS, TICKET_ID, TIM_ANALYSED, LEFT(ANALYSIS_NOTE, 80) AS NOTE_START
FROM T_WC_T2S_FEEDBACK WHERE ID_FEEDBACK = 13;
