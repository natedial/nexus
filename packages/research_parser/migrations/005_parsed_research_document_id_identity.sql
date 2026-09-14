-- Phase 3D: Use Drive document_id as parsed_research identity.
--
-- parsed_research represents one Google Drive document's current markdown
-- representation. document_hash remains a content fingerprint for duplicate
-- detection and unchanged-content skips, but parser improvements can change
-- the hash for the same Drive document.

ALTER TABLE parsed_research
    ADD COLUMN IF NOT EXISTS document_id TEXT NULL,
    ADD COLUMN IF NOT EXISTS index_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS index_error TEXT NULL,
    ADD COLUMN IF NOT EXISTS index_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS indexing_batch_id BIGINT NULL;

ALTER TABLE parsed_research
    ALTER COLUMN index_status SET DEFAULT 'pending';

UPDATE parsed_research
SET index_status = 'pending'
WHERE index_status IS NULL;

UPDATE parsed_research
SET document_id = parsed_data->'metadata'->>'document_id'
WHERE document_id IS NULL
  AND parsed_data IS NOT NULL
  AND parsed_data ? 'metadata'
  AND parsed_data->'metadata' ? 'document_id'
  AND NULLIF(BTRIM(parsed_data->'metadata'->>'document_id'), '') IS NOT NULL;

WITH ranked_duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY document_id
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_id IS NOT NULL
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
            PARTITION BY document_id
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_id IS NOT NULL
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
            PARTITION BY document_id
            ORDER BY id DESC
        ) AS row_rank
    FROM parsed_research
    WHERE document_id IS NOT NULL
),
duplicate_rows AS (
    SELECT id
    FROM ranked_duplicates
    WHERE row_rank > 1
)
DELETE FROM parsed_research
WHERE id IN (SELECT id FROM duplicate_rows);

DROP INDEX IF EXISTS idx_parsed_research_document_identity;

CREATE UNIQUE INDEX idx_parsed_research_document_identity
    ON parsed_research(document_id);

CREATE INDEX IF NOT EXISTS idx_parsed_research_document_hash
    ON parsed_research(document_hash);

COMMENT ON COLUMN parsed_research.document_id IS 'Stable Google Drive file ID; canonical parsed_research identity';
COMMENT ON COLUMN parsed_research.document_hash IS 'Hash of cleaned extracted text for duplicate detection and unchanged-content skips';
