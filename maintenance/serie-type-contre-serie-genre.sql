-- Serie_type against Serie_genre: the measurement that settles a modelling decision.
--
-- READ-ONLY, four SELECTs. Nothing is written. Query 2 is the one that decides.
--
-- THE PROBLEM
-- Four values live in BOTH vocabularies: Documentary, News, Reality and Talk / Talk Show.
-- The same word therefore maps to two placeholders and two different columns, and nothing in
-- the question arbitrates. Measured on 2026-08-20 against the deployed prompt:
--   "Show me documentary series"          -> Serie_genre1, never Serie_type1
--   "Reality TV series"                   -> Serie_genre1, never Serie_type1
--   "What talk shows are in the database" -> Serie_type1, stable, the opposite arbitration
-- The bank carries the same split personality: evaluation #2378 "Best documentary TV series"
-- resolves to Serie_type, while the near-identical "Show me documentary series" resolves to
-- Serie_genre. No prompt example fixes this, because the ambiguity is in the vocabulary, not
-- in the wording.
--
-- THE DECISION TAKEN, PENDING THESE NUMBERS
-- Make the two vocabularies DISJOINT rather than deleting Serie_type outright. The ambiguity
-- covers four of its seven values; the other three have no genre equivalent:
--   Miniseries  a FORMAT, not a genre. A miniseries can be crime, historical or comic, so no
--               genre substitutes for it and "list miniseries" would become unanswerable.
--   Scripted    TMDb's default type. Near-useless as a filter, most series carry it.
--   Video       TMDb's catch-all for non-broadcast content. Near-useless as a filter.
-- So the plan is to drop Documentary, News, Reality and Talk Show from Serie_type, keep
-- Miniseries, and decide on Scripted and Video from query 3. That removes the collision by
-- construction while keeping the one distinction genre cannot express.
--
-- WHAT THESE QUERIES MUST CONFIRM FIRST
-- Routing the four shared values to the genre side is only harmless if the two columns cover
-- the same population. If a series with SERIE_TYPE = 'Documentary' does NOT also carry the
-- Documentary genre, then routing to genre silently changes the answer the user gets, and it
-- fails the way this project keeps finding: an empty result with no error.
--
-- Serie_type resolves to T_WC_T2S_SERIE.SERIE_TYPE (closed_vocab.py, _SERIE_TYPE_QUERY).
-- Serie_genre resolves to an ID_GENRE, filtered through T_WC_T2S_SERIE_GENRE.
--
-- IF THE OVERLAP IS HIGH: three edits, and they belong BEFORE the full evaluation run, not
-- after. Drop the four values from the Serie_type section of data/entity_extraction.md, drop
-- their aliases from data/closed_vocabularies.json, and revisit the assertion on #2378, which
-- currently expects Serie_type. Otherwise the baseline will carry failures everyone already
-- knows come from a pending modelling decision rather than from the prompt.
--
-- IF THE OVERLAP IS LOW: neither deletion nor disjunction is right, and the answer becomes an
-- explicit disambiguation rule in the prompt. Re-open the question at that point.


-- ===========================================================================
-- 1. What SERIE_TYPE actually holds, and at what volume.
-- ===========================================================================
SELECT COALESCE(SERIE_TYPE, '(NULL)') AS serie_type, COUNT(*) AS series
FROM T_WC_T2S_SERIE
GROUP BY SERIE_TYPE
ORDER BY series DESC;


-- ===========================================================================
-- 2. THE DECIDING QUERY. For each shared value: how many series carry it as a
--    type, how many carry the genre of the same name, and how many carry both.
--    A high pct_of_type_covered_by_genre licenses the disjunction. A low one
--    forbids it.
-- ===========================================================================
SELECT g.name                                                  AS shared_value,
       SUM(s.SERIE_TYPE = g.name)                              AS by_type,
       SUM(sg.ID_SERIE IS NOT NULL)                            AS by_genre,
       SUM(s.SERIE_TYPE = g.name AND sg.ID_SERIE IS NOT NULL)  AS by_both,
       ROUND(100 * SUM(s.SERIE_TYPE = g.name AND sg.ID_SERIE IS NOT NULL)
             / NULLIF(SUM(s.SERIE_TYPE = g.name), 0), 1)       AS pct_of_type_covered_by_genre
FROM T_WC_TMDB_GENRE g
CROSS JOIN T_WC_T2S_SERIE s
LEFT JOIN T_WC_T2S_SERIE_GENRE sg
       ON sg.ID_SERIE = s.ID_SERIE AND sg.ID_GENRE = g.id
      AND (sg.DELETED IS NULL OR sg.DELETED = 0)
WHERE g.APPLIES_TO_SERIE = 1
  AND g.name IN ('Documentary', 'News', 'Reality', 'Talk')
GROUP BY g.name
ORDER BY g.name;


-- ===========================================================================
-- 3. What the three non-overlapping values are worth. Miniseries is the only
--    real stake; Scripted and Video are TMDb defaults.
-- ===========================================================================
SELECT SERIE_TYPE, COUNT(*) AS series
FROM T_WC_T2S_SERIE
WHERE SERIE_TYPE IN ('Miniseries', 'Scripted', 'Video')
GROUP BY SERIE_TYPE
ORDER BY series DESC;


-- ===========================================================================
-- 4. Counter-check on Miniseries. If they spread across every genre, then no
--    genre can stand in for the format, which is the argument for keeping it.
-- ===========================================================================
SELECT g.name AS genre, COUNT(*) AS miniseries
FROM T_WC_T2S_SERIE s
JOIN T_WC_T2S_SERIE_GENRE sg ON sg.ID_SERIE = s.ID_SERIE
                            AND (sg.DELETED IS NULL OR sg.DELETED = 0)
JOIN T_WC_TMDB_GENRE g ON g.id = sg.ID_GENRE
WHERE s.SERIE_TYPE = 'Miniseries'
GROUP BY g.name
ORDER BY miniseries DESC
LIMIT 12;
