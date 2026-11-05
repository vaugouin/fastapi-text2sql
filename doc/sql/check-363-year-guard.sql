-- FASTAPI-TEXT2SQL-363: years of the films behind the fuzzy false positive of 2204 FR. Read-only. 2026-11-05.
-- 152750 'La guerre des mamies' (the fuzzy hit), 531097 (the expected film, 'La Guerre des momies' 1973),
-- 62928 (the ChromaDB candidate of 1.1.19). The guard drops a fuzzy hit only when its year is known.
-- Voie 1: ssh vps-agent run fastapi-text2sql-blue/doc/sql/check-363-year-guard.sql
SELECT ID_MOVIE, MOVIE_TITLE, MOVIE_TITLE_FR, ORIGINAL_TITLE, RELEASE_YEAR, DAT_RELEASE, IMDB_VOTES
FROM T_WC_T2S_MOVIE
WHERE ID_MOVIE IN (152750, 531097, 62928);
