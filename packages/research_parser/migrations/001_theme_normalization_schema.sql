-- Phase 3A: Schema scaffolding for theme normalization
-- This migration creates the relational tables with loose contracts
-- (nullable columns, JSONB) to allow iteration before Phase 3B constraint tightening.

-- =============================================================================
-- Add query-friendly columns to parsed_research
-- =============================================================================

ALTER TABLE parsed_research
    ADD COLUMN IF NOT EXISTS document_title TEXT NULL,
    ADD COLUMN IF NOT EXISTS publisher TEXT NULL,
    ADD COLUMN IF NOT EXISTS area TEXT NULL,
    ADD COLUMN IF NOT EXISTS region TEXT NULL,
    ADD COLUMN IF NOT EXISTS asset_focus TEXT NULL,
    ADD COLUMN IF NOT EXISTS document_link TEXT NULL,
    ADD COLUMN IF NOT EXISTS theme_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS trade_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS document_hash TEXT NULL;

-- Indexes for common document filters
CREATE INDEX IF NOT EXISTS idx_parsed_research_source_date ON parsed_research(source_date);
CREATE INDEX IF NOT EXISTS idx_parsed_research_source ON parsed_research(source);
CREATE INDEX IF NOT EXISTS idx_parsed_research_area ON parsed_research(area);
CREATE INDEX IF NOT EXISTS idx_parsed_research_region ON parsed_research(region);
CREATE INDEX IF NOT EXISTS idx_parsed_research_asset_focus ON parsed_research(asset_focus);
CREATE INDEX IF NOT EXISTS idx_parsed_research_document_hash ON parsed_research(document_hash);

-- =============================================================================
-- Table: research_themes
-- One row per final merged theme for a document
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_themes (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    theme_order INTEGER NOT NULL,
    label TEXT NOT NULL,
    scope TEXT NULL,
    primary_category TEXT NULL,
    relevance TEXT[] NOT NULL DEFAULT '{}',
    classification TEXT NOT NULL DEFAULT 'Description',
    strength TEXT NOT NULL DEFAULT 'Secondary',
    confidence TEXT NOT NULL DEFAULT 'Medium',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 0,
    context TEXT NOT NULL DEFAULT '',
    directionality JSONB NULL,
    argument_structure JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_research_themes_research_theme_order UNIQUE (research_id, theme_order)
);

-- Indexes for common theme filters and joins
CREATE INDEX IF NOT EXISTS idx_research_themes_research_id ON research_themes(research_id);
CREATE INDEX IF NOT EXISTS idx_research_themes_label ON research_themes(label);
CREATE INDEX IF NOT EXISTS idx_research_themes_primary_category ON research_themes(primary_category);
CREATE INDEX IF NOT EXISTS idx_research_themes_strength ON research_themes(strength);
CREATE INDEX IF NOT EXISTS idx_research_themes_confidence ON research_themes(confidence);
CREATE INDEX IF NOT EXISTS idx_research_themes_classification ON research_themes(classification);

-- =============================================================================
-- Table: research_theme_excerpts
-- One row per excerpt associated with a theme
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_theme_excerpts (
    id BIGSERIAL PRIMARY KEY,
    theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    excerpt_order INTEGER NOT NULL,
    excerpt_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_theme_excerpts_theme_id ON research_theme_excerpts(theme_id);

-- =============================================================================
-- Table: research_theme_links
-- One row per explicit relationship between two themes in the same document
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_theme_links (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    from_theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    to_theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_themes CHECK (from_theme_id <> to_theme_id)
);

-- Indexes for link queries
CREATE INDEX IF NOT EXISTS idx_research_theme_links_research_id ON research_theme_links(research_id);
CREATE INDEX IF NOT EXISTS idx_research_theme_links_from_theme_id ON research_theme_links(from_theme_id);
CREATE INDEX IF NOT EXISTS idx_research_theme_links_to_theme_id ON research_theme_links(to_theme_id);
CREATE INDEX IF NOT EXISTS idx_research_theme_links_relationship ON research_theme_links(relationship);

-- Composite index for common query pattern: get all links for a document with theme details
CREATE INDEX IF NOT EXISTS idx_research_theme_links_research_from_to 
    ON research_theme_links(research_id, from_theme_id, to_theme_id);

-- =============================================================================
-- Comments for documentation
-- =============================================================================

COMMENT ON TABLE research_themes IS 'Normalized theme rows extracted from research documents';
COMMENT ON TABLE research_theme_excerpts IS 'Verbatim excerpts supporting theme identification';
COMMENT ON TABLE research_theme_links IS 'Explicit relationships between themes within a document';

COMMENT ON COLUMN research_themes.argument_structure IS 'JSONB structure capturing argument architecture: conditionals, confidence_basis, dependencies, contradictions';
COMMENT ON COLUMN parsed_research.document_hash IS 'Hash of cleaned extracted text for idempotent backfill and duplicate detection';
