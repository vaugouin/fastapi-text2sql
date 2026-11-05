-- FASTAPI-TEXT2SQL-360: export of the company, network and collection name pools for the offline
-- lexical bench (scope decided 2026-11-05: every type but topics moves off ChromaDB).
--
-- Read-only, voie 1. Written 2026-11-05. Feeds checks/bench-lexical-360-names.py, which replays the
-- Company_name, Network_name and Collection_name mentions of the campaigns against a lexical
-- candidate generator and compares it with what ChromaDB (companies, networks) or the RapidFuzz
-- strategy (collections) returned.
--
-- One row per living entity. Same packing as check-360-export-title-pool.sql: the client prints a
-- padded table, so records are packed 400 per row with GROUP_CONCAT, fields separated by CHAR(31),
-- records by the literal '@@REC@@', control characters inside values replaced by spaces.
-- The result is a data file, NOT committed beside this .sql: the bench reads it from
-- shared_data/fastapi-text2sql/bench-360/.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION group_concat_max_len = 16777216;

-- Header, for the parser: FAM, ID, POP, MOVIES, SERIES, NAME, NAME_FR

SELECT COUNT(*) AS COMPANIES FROM T_WC_T2S_COMPANY WHERE COALESCE(DELETED, 0) = 0;
SELECT COUNT(*) AS NETWORKS FROM T_WC_T2S_NETWORK WHERE COALESCE(DELETED, 0) = 0;
SELECT COUNT(*) AS COLLECTIONS FROM T_WC_T2S_COLLECTION WHERE COALESCE(DELETED, 0) = 0;

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR '@@REC@@') AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY c.ID_COMPANY) AS RN,
      CONCAT_WS(CHAR(31),
         'c',
         c.ID_COMPANY,
         ROUND(COALESCE(c.POPULARITY, 0), 3),
         COALESCE(c.MOVIE_COUNT, 0),
         COALESCE(c.SERIE_COUNT, 0),
         REGEXP_REPLACE(COALESCE(c.COMPANY_NAME, ''), '[[:cntrl:]]', ' '),
         '') AS REC
      FROM T_WC_T2S_COMPANY c
     WHERE COALESCE(c.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR '@@REC@@') AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY n.ID_NETWORK) AS RN,
      CONCAT_WS(CHAR(31),
         'n',
         n.ID_NETWORK,
         0,
         0,
         COALESCE(n.SERIE_COUNT, 0),
         REGEXP_REPLACE(COALESCE(n.NETWORK_NAME, ''), '[[:cntrl:]]', ' '),
         '') AS REC
      FROM T_WC_T2S_NETWORK n
     WHERE COALESCE(n.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;

SELECT GROUP_CONCAT(REC ORDER BY RN SEPARATOR '@@REC@@') AS RECS
  FROM (
    SELECT ROW_NUMBER() OVER (ORDER BY k.ID_T2S_COLLECTION) AS RN,
      CONCAT_WS(CHAR(31),
         'k',
         k.ID_T2S_COLLECTION,
         ROUND(COALESCE(k.POPULARITY, 0), 3),
         COALESCE(k.MOVIE_COUNT, 0),
         COALESCE(k.SERIE_COUNT, 0),
         REGEXP_REPLACE(COALESCE(k.COLLECTION_NAME, ''), '[[:cntrl:]]', ' '),
         REGEXP_REPLACE(COALESCE(k.COLLECTION_NAME_FR, ''), '[[:cntrl:]]', ' ')) AS REC
      FROM T_WC_T2S_COLLECTION k
     WHERE COALESCE(k.DELETED, 0) = 0
  ) x
 GROUP BY (RN - 1) DIV 400;
