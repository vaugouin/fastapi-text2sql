-- =============================================================================
-- VOICE-AGENT-072 — seed curated SHOWCASE questions for the voice-agent launch
-- screen (manga/anime + series/actors/creators).
--
-- Showcase rows live in T_WC_T2S_EVALUATION with IS_SHOWCASE = 1. The API
-- (/samples?set=showcase) turns each row's ASSERTIONS_QUERY_RESULT — an entity-id
-- set of the form "<ID_COL> IN (id1, id2, ...)" — into a simulated result of
-- poster/portrait cards. So a showcase question = one row here, grounded in real
-- in-DB entity ids.
--
-- Every id below was verified via MCP on 2026-07-09 to exist AND carry an image
-- (POSTER_PATH / PROFILE_PATH), so VOICE-AGENT-068 (hide image-less showcase cards)
-- drops none of them.
--
-- DECISIONS FOR PHILIPPE before running:
--   * Categories: this script CREATES two new top-level categories (ID_PARENT = 1).
--     Change DISPLAY_ORDER, or point the questions at existing categories instead,
--     if you prefer. Showcase draws from IS_SHOWCASE=1 across the whole tree.
--   * Showcase-only: rows are IS_SAMPLE = 0. Set IS_SAMPLE = 1 too if you also want
--     them in the classic samples panel.
--   * "Creators" angle (item 11) is not seeded yet — needs person ids for a few
--     directors/showrunners (e.g. Miyazaki). Ask and I'll ground them.
-- Run once on the shared MariaDB.
-- =============================================================================

-- 1) Categories (top-level: ID_PARENT = 1) ------------------------------------
INSERT INTO T_WC_T2S_EVALUATION_CATEGORY
  (DESCRIPTION, DESCRIPTION_FR, ID_PARENT, DELETED, DISPLAY_ORDER, DAT_CREAT)
VALUES ('Anime & Manga', 'Anime et manga', 1, 0, 100, CURDATE());
SET @cat_anime = LAST_INSERT_ID();

INSERT INTO T_WC_T2S_EVALUATION_CATEGORY
  (DESCRIPTION, DESCRIPTION_FR, ID_PARENT, DELETED, DISPLAY_ORDER, DAT_CREAT)
VALUES ('Series, cast & creators', 'Séries, interprètes et créateurs', 1, 0, 101, CURDATE());
SET @cat_people = LAST_INSERT_ID();

-- 2) Showcase questions -------------------------------------------------------

-- Anime films — the acclaimed Studio Ghibli catalogue (movies, all have posters)
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_SHOWCASE, IS_SAMPLE, IS_EVAL,
   ID_T2S_EVALUATION_CATEGORY, DELETED, DISPLAY_ORDER, DAT_CREAT, TIM_UPDATED,
   ASSERTIONS_QUERY_RESULT)
VALUES
  ('What are the greatest Studio Ghibli films?',
   'Quels sont les plus grands films du Studio Ghibli ?',
   1, 0, 0, @cat_anime, 0, 10, CURDATE(), NOW(),
   -- Spirited Away, Grave of the Fireflies, Princess Mononoke, Howl's Moving Castle,
   -- My Neighbor Totoro, Castle in the Sky, Kiki's Delivery Service, Ponyo
   'ID_MOVIE IN (129, 12477, 128, 4935, 8392, 10515, 16859, 12429)');

-- Series — grounded neighbours of a modern classic ("if you loved Breaking Bad")
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_SHOWCASE, IS_SAMPLE, IS_EVAL,
   ID_T2S_EVALUATION_CATEGORY, DELETED, DISPLAY_ORDER, DAT_CREAT, TIM_UPDATED,
   ASSERTIONS_QUERY_RESULT)
VALUES
  ('Which TV series should I watch if I loved Breaking Bad?',
   'Quelles séries regarder si j''ai adoré Breaking Bad ?',
   1, 0, 0, @cat_people, 0, 10, CURDATE(), NOW(),
   -- Better Call Saul, Narcos: Mexico, Snowfall, Narcos, Dark Winds,
   -- Animal Kingdom, Queen of the South, Mr Inbetween
   'ID_SERIE IN (60059, 80968, 71694, 63351, 128904, 66025, 66676, 81358)');

-- Actors — the main cast of Breaking Bad (persons, all have portraits)
INSERT INTO T_WC_T2S_EVALUATION
  (QUESTION, QUESTION_FR, IS_SHOWCASE, IS_SAMPLE, IS_EVAL,
   ID_T2S_EVALUATION_CATEGORY, DELETED, DISPLAY_ORDER, DAT_CREAT, TIM_UPDATED,
   ASSERTIONS_QUERY_RESULT)
VALUES
  ('Who are the main actors of Breaking Bad?',
   'Qui sont les acteurs principaux de Breaking Bad ?',
   1, 0, 0, @cat_people, 0, 20, CURDATE(), NOW(),
   -- Bryan Cranston, Aaron Paul, Anna Gunn, RJ Mitte, Dean Norris,
   -- Betsy Brandt, Bob Odenkirk, Jonathan Banks
   'ID_PERSON IN (17419, 84497, 134531, 209674, 14329, 1217934, 59410, 783)');
