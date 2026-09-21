-- Nexus parser schema (Phase 2)
-- Consolidated from research_parser migrations 001-005 and 004 (partial).
-- Excludes parser 004 claims/entities/relations tables — analyst argument_map
-- is the canonical semantic store.

CREATE TABLE IF NOT EXISTS parsed_research (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL,
    parsed_data JSONB NOT NULL,
    source_date DATE,
    source TEXT,
    document_name TEXT,
    document_title TEXT,
    publisher TEXT,
    area TEXT,
    region TEXT,
    asset_focus TEXT,
    document_link TEXT,
    theme_count INTEGER NOT NULL DEFAULT 0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    document_hash TEXT,
    index_status TEXT NOT NULL DEFAULT 'pending',
    indexed_at TIMESTAMPTZ,
    index_error TEXT,
    index_version TEXT,
    indexing_batch_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_parsed_research_document_identity
    ON parsed_research(document_id);
CREATE INDEX IF NOT EXISTS idx_parsed_research_source_date ON parsed_research(source_date);
CREATE INDEX IF NOT EXISTS idx_parsed_research_source ON parsed_research(source);
CREATE INDEX IF NOT EXISTS idx_parsed_research_area ON parsed_research(area);
CREATE INDEX IF NOT EXISTS idx_parsed_research_region ON parsed_research(region);
CREATE INDEX IF NOT EXISTS idx_parsed_research_asset_focus ON parsed_research(asset_focus);
CREATE INDEX IF NOT EXISTS idx_parsed_research_document_hash ON parsed_research(document_hash);

CREATE TABLE IF NOT EXISTS research_themes (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    theme_order INTEGER NOT NULL,
    label TEXT NOT NULL,
    scope TEXT,
    primary_category TEXT,
    relevance TEXT[] NOT NULL DEFAULT '{}',
    classification TEXT NOT NULL DEFAULT 'Description',
    strength TEXT NOT NULL DEFAULT 'Secondary',
    confidence TEXT NOT NULL DEFAULT 'Medium',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 0,
    context TEXT NOT NULL DEFAULT '',
    directionality JSONB,
    argument_structure JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_research_themes_research_theme_order UNIQUE (research_id, theme_order)
);

CREATE INDEX IF NOT EXISTS idx_research_themes_research_id ON research_themes(research_id);
CREATE INDEX IF NOT EXISTS idx_research_themes_label ON research_themes(label);

CREATE TABLE IF NOT EXISTS research_theme_excerpts (
    id BIGSERIAL PRIMARY KEY,
    theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    excerpt_order INTEGER NOT NULL,
    excerpt_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_theme_excerpts_theme_id ON research_theme_excerpts(theme_id);

CREATE TABLE IF NOT EXISTS research_theme_links (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    from_theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    to_theme_id BIGINT NOT NULL REFERENCES research_themes(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_themes CHECK (from_theme_id <> to_theme_id),
    CONSTRAINT chk_relationship_values CHECK (
        relationship IN ('drives', 'amplifies', 'contradicts', 'hedges', 'enables')
    )
);

CREATE INDEX IF NOT EXISTS idx_research_theme_links_research_id ON research_theme_links(research_id);

CREATE TABLE IF NOT EXISTS research_document_artifacts (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parse_backend TEXT,
    parse_confidence_score NUMERIC,
    parse_confidence_status TEXT,
    raw_markdown_path TEXT,
    clean_text_path TEXT,
    figure_manifest JSONB NOT NULL DEFAULT '[]',
    artifact_manifest JSONB NOT NULL DEFAULT '{}',
    clean_text_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, parser_version)
);

CREATE INDEX IF NOT EXISTS idx_research_document_artifacts_research_id
    ON research_document_artifacts(research_id);

CREATE TABLE IF NOT EXISTS research_spans (
    id BIGSERIAL PRIMARY KEY,
    span_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    span_version TEXT NOT NULL,
    span_type TEXT NOT NULL,
    span_order INTEGER NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    section_path TEXT[] NOT NULL DEFAULT '{}',
    paragraph_start INTEGER,
    paragraph_end INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    coordinates JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, span_version, span_order)
);

CREATE INDEX IF NOT EXISTS idx_research_spans_research_id ON research_spans(research_id);

CREATE TABLE IF NOT EXISTS research_retrieval_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    chunk_order INTEGER NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'semantic',
    title TEXT,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    span_keys TEXT[] NOT NULL DEFAULT '{}',
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER,
    embedding_model TEXT,
    embedding_version TEXT,
    embedding_id TEXT,
    lexical_terms JSONB NOT NULL DEFAULT '[]',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, chunker_version, chunk_order)
);

CREATE INDEX IF NOT EXISTS idx_research_retrieval_chunks_research_id
    ON research_retrieval_chunks(research_id);
