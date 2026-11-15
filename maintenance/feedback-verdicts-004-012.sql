-- Verdicts on the user feedback rows #4 to #12 (analyse-feedback skill, 2026-11-15).
-- Writes T_WC_T2S_FEEDBACK only (agent-writable). 9 rows: 6 analysed, 3 not_a_defect.
-- not_a_defect on a 👍 has no cache effect; #4 shares its question with the 👎 #6, which stays open.

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'cache : served from the exact-question cache, which runs no entity resolution, so result_chain.plan anchored the lineage walk on the result rows (source_work 11237, movie 653) instead of Nosferatu 2024 (426063) and found no chain; fallback to ranked-bars with Dracula listed twice (log 20261115-092334). A fresh run and the replay with feedback bypass draw Dracula > Nosferatu 1922 > Nosferatu 2024. Cache row is right, do not retire it.',
  TICKET_ID = 'FASTAPI-TEXT2SQL-389', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 6;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'cache : on an exact cache hit entity_match_scores is empty, so result_chain.plan falls back to row anchors; the SQL excludes the named film (MOVIE_TITLE <> Seven Samurai), so the chain starts at The Magnificent Seven 1960 and drops Seven Samurai (346) and Samurai 7 (log 20261115-092534, cached_exact_question=true). Fresh runs (20261114-200000, -201919) and the replay with feedback bypass anchor 346 and draw 6 nodes.',
  TICKET_ID = 'FASTAPI-TEXT2SQL-389', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 7;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'entity_resolution : Nosferatu extracted as Character_name1 (no resolver, raw substitution), SQL matched CAST_CHARACTER = Nosferatu exactly and returned 6 fringe films (Nosferatu in Venice, SpongeBob Kreepaway Kamp...), missing 1922 (653), 1979 (6404) and 2024 (426063) (log 20261114-200720). The FR replay reads Collection_name1 and returns 0 rows. The question names a title family with no TMDb collection; timeline not caught as requested view.',
  TICKET_ID = 'FASTAPI-TEXT2SQL-390', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 5;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'presentation : API correct (3 rows, chain, log 20261115-093616). The tool result reached the client at 09:36:16 but the Realtime spoken answer only finished at 09:37:25, about 55 s late, after feedback #8; the feedback POST has no path into the Realtime channel, so the timing is a coincidence. Model latency vs a held response.create cannot be told apart: client.log drops response.created and output_audio_buffer events.',
  TICKET_ID = 'VOICE-AGENT-268', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK IN (8, 9);

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'analysed',
  ANALYSIS_NOTE = 'presentation : API correct (one row, LOCATION_NAME = Monument Valley, role label, no cache). voice-agent titleForRecord() (app.js) has no LOCATION_NAME since API 1.1.19 renamed it from ITEM_LABEL; only the card chain was updated, so the page title, image alt texts and the Brief me subject fall back to Result.',
  TICKET_ID = 'VOICE-AGENT-267', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 12;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'not_a_defect',
  ANALYSIS_NOTE = 'not_a_defect : fresh run (log 20261114-200611), lineage walk from 426063 gives Dracula > Nosferatu 1922 > Nosferatu 2024 as a chain; confirms evaluation 2935. The same question served from the exact cache loses the chain (feedback #6, FASTAPI-TEXT2SQL-389).',
  TICKET_ID = 'FASTAPI-TEXT2SQL-389', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 4;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'not_a_defect',
  ANALYSIS_NOTE = 'not_a_defect : fresh run (log 20261115-094222) anchored the novel Red Harvest (source work 6848) and drew a 9-node chain; covered by evaluation 2937. An exact-cache replay on 2026-11-15 returns the same 8 rows as card-grid with no chain: same cache-path defect as #7 (FASTAPI-TEXT2SQL-389).',
  TICKET_ID = 'FASTAPI-TEXT2SQL-389', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 10;

UPDATE T_WC_T2S_FEEDBACK SET ANALYSIS_STATUS = 'not_a_defect',
  ANALYSIS_NOTE = 'not_a_defect : confirmation after FASTAPI-TEXT2SQL-386 (tribute credits excluded): Ozu filming locations map shows Japan only.',
  TICKET_ID = 'FASTAPI-TEXT2SQL-386', TIM_ANALYSED = NOW(), TIM_UPDATED = NOW()
WHERE ID_FEEDBACK = 11;

SELECT ID_FEEDBACK, RATING, ANALYSIS_STATUS, TICKET_ID, TIM_ANALYSED
FROM T_WC_T2S_FEEDBACK WHERE ID_FEEDBACK BETWEEN 4 AND 12 ORDER BY ID_FEEDBACK;
