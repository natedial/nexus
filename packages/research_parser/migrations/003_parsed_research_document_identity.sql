-- Phase 3C: Enforce document identity for idempotent parser writes
-- Remove duplicate rows created by read-then-insert races, then add
-- a unique index so parser writes can use atomic upsert semantics.

-- Keep the newest parsed_research row for each document identity key.
-- Drop normalized children for rows that will be removed; future parser
-- writes/backfills rebuild those children from the canonical row.
WITH ranked_duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY document_hash, document_name, source
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_hash IS NOT NULL
      AND document_name IS NOT NULL
      AND source IS NOT NULL
),
duplicate_rows AS (
    SELECT id
    FROM ranked_duplicates
    WHERE row_rank > 1
)
DELETE FROM research_theme_excerpts
WHERE theme_id IN (
    SELECT id
    FROM research_themes
    WHERE research_id IN (SELECT id FROM duplicate_rows)
);

WITH ranked_duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY document_hash, document_name, source
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_hash IS NOT NULL
      AND document_name IS NOT NULL
      AND source IS NOT NULL
),
duplicate_rows AS (
    SELECT id
    FROM ranked_duplicates
    WHERE row_rank > 1
)
DELETE FROM research_themes
WHERE research_id IN (SELECT id FROM duplicate_rows);

WITH ranked_duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY document_hash, document_name, source
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_hash IS NOT NULL
      AND document_name IS NOT NULL
      AND source IS NOT NULL
),
duplicate_rows AS (
    SELECT id
    FROM ranked_duplicates
    WHERE row_rank > 1
)
DELETE FROM parsed_research
WHERE id IN (SELECT id FROM duplicate_rows);

DROP INDEX IF EXISTS idx_parsed_research_document_identity;

-- Use a plain unique index so Postgres can infer the conflict target from
-- INSERT ... ON CONFLICT (document_hash, document_name, source). Nullable
-- columns still allow multiple rows when any key part is NULL.
CREATE UNIQUE INDEX idx_parsed_research_document_identity
    ON parsed_research(document_hash, document_name, source);
