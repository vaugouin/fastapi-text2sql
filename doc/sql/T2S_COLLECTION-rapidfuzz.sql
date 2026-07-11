-- RapidFuzz generated columns + indexes for collection-name resolution.
-- Mirrors doc/sql/T2S_PERSON-rapidfuzz.sql. Run once on the target database to
-- enable the `rapidfuzz` search strategy for the `Collection_name` placeholder
-- (see data/entity_resolution.json).
--
-- STORED generated columns are computed for existing rows at ALTER time, so no
-- separate backfill is needed. Until these columns exist, the rapidfuzz strategy
-- no-ops (its SQL errors are caught) and resolution falls back to the embeddings
-- strategy, so deploying the config before this migration is safe.

ALTER TABLE T_WC_T2S_COLLECTION
  ADD COLUMN COLLECTION_NAME_NORM VARCHAR(255)
  AS (
    LOWER(
      REGEXP_REPLACE(
        REGEXP_REPLACE(COLLECTION_NAME, '[^[:alnum:] ]', ' '), -- drop punctuation
        ' +', ' '                                              -- collapse spaces
      )
    )
  ) STORED;

CREATE INDEX IDX_T2S_COLLECTION_NAME_NORM ON T_WC_T2S_COLLECTION (COLLECTION_NAME_NORM);

ALTER TABLE T_WC_T2S_COLLECTION
  ADD COLUMN COLLECTION_NAME_KEY VARCHAR(255)
  AS (REPLACE(COLLECTION_NAME_NORM, ' ', '')) STORED;

CREATE INDEX IDX_T2S_COLLECTION_NAME_KEY ON T_WC_T2S_COLLECTION (COLLECTION_NAME_KEY);

-- Optional but recommended: FULLTEXT fallback for candidate fetch.
ALTER TABLE T_WC_T2S_COLLECTION
  ADD FULLTEXT INDEX ft_collection_name_norm (COLLECTION_NAME_NORM);
