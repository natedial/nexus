-- Migration: Research memory substrate
-- Date: 2026-05-18
-- Description:
--   Add durable span, retrieval, evidence, claim, entity, relation, and memory
--   event tables. This migration is additive and keeps existing parser,
--   analyst, dispatcher, and research-store flows compatible.

-- =============================================================================
-- Table: research_document_artifacts
-- Durable references to parser outputs and parse metadata.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_document_artifacts (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parse_backend TEXT NULL,
    parse_confidence_score NUMERIC NULL,
    parse_confidence_status TEXT NULL,
    raw_markdown_path TEXT NULL,
    clean_text_path TEXT NULL,
    figure_manifest JSONB NOT NULL DEFAULT '[]',
    artifact_manifest JSONB NOT NULL DEFAULT '{}',
    clean_text_hash TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, parser_version)
);

CREATE INDEX IF NOT EXISTS idx_research_document_artifacts_research_id
    ON research_document_artifacts(research_id);
CREATE INDEX IF NOT EXISTS idx_research_document_artifacts_document_hash
    ON research_document_artifacts(document_hash);

-- =============================================================================
-- Table: research_spans
-- Stable source-grounded text spans. Claims and evidence cite spans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_spans (
    id BIGSERIAL PRIMARY KEY,
    span_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    span_version TEXT NOT NULL,
    span_type TEXT NOT NULL,
    span_order INTEGER NOT NULL,
    page_start INTEGER NULL,
    page_end INTEGER NULL,
    section_path TEXT[] NOT NULL DEFAULT '{}',
    paragraph_start INTEGER NULL,
    paragraph_end INTEGER NULL,
    char_start INTEGER NULL,
    char_end INTEGER NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    coordinates JSONB NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, span_version, span_order)
);

CREATE INDEX IF NOT EXISTS idx_research_spans_research_id
    ON research_spans(research_id);
CREATE INDEX IF NOT EXISTS idx_research_spans_document_hash
    ON research_spans(document_hash);
CREATE INDEX IF NOT EXISTS idx_research_spans_type
    ON research_spans(span_type);
CREATE INDEX IF NOT EXISTS idx_research_spans_page_range
    ON research_spans(research_id, page_start, page_end);
CREATE INDEX IF NOT EXISTS idx_research_spans_text_hash
    ON research_spans(text_hash);

-- =============================================================================
-- Table: research_retrieval_chunks
-- Search-oriented chunks backed by one or more spans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_retrieval_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    chunk_order INTEGER NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'semantic',
    title TEXT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    span_keys TEXT[] NOT NULL DEFAULT '{}',
    page_start INTEGER NULL,
    page_end INTEGER NULL,
    token_count INTEGER NULL,
    embedding_model TEXT NULL,
    embedding_version TEXT NULL,
    embedding_id TEXT NULL,
    lexical_terms JSONB NOT NULL DEFAULT '[]',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(research_id, chunker_version, chunk_order)
);

CREATE INDEX IF NOT EXISTS idx_research_retrieval_chunks_research_id
    ON research_retrieval_chunks(research_id);
CREATE INDEX IF NOT EXISTS idx_research_retrieval_chunks_document_hash
    ON research_retrieval_chunks(document_hash);
CREATE INDEX IF NOT EXISTS idx_research_retrieval_chunks_embedding
    ON research_retrieval_chunks(embedding_model, embedding_version);
CREATE INDEX IF NOT EXISTS idx_research_retrieval_chunks_page_range
    ON research_retrieval_chunks(research_id, page_start, page_end);

-- =============================================================================
-- Table: research_evidence_units
-- Compact exact evidence excerpts used to support claims and relations.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_evidence_units (
    id BIGSERIAL PRIMARY KEY,
    evidence_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    span_key TEXT NULL REFERENCES research_spans(span_key) ON DELETE SET NULL,
    chunk_key TEXT NULL REFERENCES research_retrieval_chunks(chunk_key) ON DELETE SET NULL,
    evidence_order INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    page_ref TEXT NULL,
    source_ref JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_evidence_units_research_id
    ON research_evidence_units(research_id);
CREATE INDEX IF NOT EXISTS idx_research_evidence_units_span_key
    ON research_evidence_units(span_key);
CREATE INDEX IF NOT EXISTS idx_research_evidence_units_chunk_key
    ON research_evidence_units(chunk_key);
CREATE INDEX IF NOT EXISTS idx_research_evidence_units_text_hash
    ON research_evidence_units(text_hash);

-- =============================================================================
-- Table: research_entities
-- Canonical entity and concept registry.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_entities (
    id BIGSERIAL PRIMARY KEY,
    entity_key TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    canonical_label TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    description TEXT NULL,
    resolver_version TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_entities_type
    ON research_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_research_entities_label
    ON research_entities(canonical_label);

-- =============================================================================
-- Table: research_claims
-- Atomic assertions extracted from evidence.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_claims (
    id BIGSERIAL PRIMARY KEY,
    claim_key TEXT NOT NULL UNIQUE,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    subject_text TEXT NOT NULL,
    predicate TEXT NULL,
    object_text TEXT NULL,
    subject_entity_key TEXT NULL REFERENCES research_entities(entity_key) ON DELETE SET NULL,
    object_entity_key TEXT NULL REFERENCES research_entities(entity_key) ON DELETE SET NULL,
    text TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    polarity TEXT NOT NULL DEFAULT 'not_applicable',
    modality TEXT NULL,
    time_horizon TEXT NULL,
    time_anchor TEXT NULL,
    condition_text TEXT NULL,
    qualifier_text TEXT NULL,
    confidence_label TEXT NOT NULL DEFAULT 'medium',
    extraction_confidence TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'proposed',
    authority_band TEXT NOT NULL DEFAULT 'seed',
    extractor_version TEXT NOT NULL,
    resolver_version TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_claims_research_id
    ON research_claims(research_id);
CREATE INDEX IF NOT EXISTS idx_research_claims_document_hash
    ON research_claims(document_hash);
CREATE INDEX IF NOT EXISTS idx_research_claims_type
    ON research_claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_research_claims_subject_entity
    ON research_claims(subject_entity_key);
CREATE INDEX IF NOT EXISTS idx_research_claims_object_entity
    ON research_claims(object_entity_key);
CREATE INDEX IF NOT EXISTS idx_research_claims_status
    ON research_claims(status);

-- =============================================================================
-- Table: research_claim_evidence
-- Many-to-many claim to evidence linkage.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_claim_evidence (
    claim_key TEXT NOT NULL REFERENCES research_claims(claim_key) ON DELETE CASCADE,
    evidence_key TEXT NOT NULL REFERENCES research_evidence_units(evidence_key) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'supporting',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_key, evidence_key, role)
);

CREATE INDEX IF NOT EXISTS idx_research_claim_evidence_evidence_key
    ON research_claim_evidence(evidence_key);

-- =============================================================================
-- Table: research_relations
-- Typed cross-entity relations for graph and world-model use.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_relations (
    id BIGSERIAL PRIMARY KEY,
    relation_key TEXT NOT NULL UNIQUE,
    from_entity_key TEXT NULL REFERENCES research_entities(entity_key) ON DELETE SET NULL,
    to_entity_key TEXT NULL REFERENCES research_entities(entity_key) ON DELETE SET NULL,
    relation_type TEXT NOT NULL,
    sign TEXT NULL,
    directionality TEXT NOT NULL DEFAULT 'directed',
    time_horizon TEXT NULL,
    condition_text TEXT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    authority_band TEXT NOT NULL DEFAULT 'seed',
    maturity TEXT NOT NULL DEFAULT 'trace',
    support_count INTEGER NOT NULL DEFAULT 1,
    source_diversity INTEGER NOT NULL DEFAULT 1,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolver_version TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_relations_from_entity
    ON research_relations(from_entity_key);
CREATE INDEX IF NOT EXISTS idx_research_relations_to_entity
    ON research_relations(to_entity_key);
CREATE INDEX IF NOT EXISTS idx_research_relations_type
    ON research_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_research_relations_status
    ON research_relations(status);
CREATE INDEX IF NOT EXISTS idx_research_relations_last_seen
    ON research_relations(last_seen_at);

-- =============================================================================
-- Table: research_relation_evidence
-- Relation evidence and claim provenance.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_relation_evidence (
    relation_key TEXT NOT NULL REFERENCES research_relations(relation_key) ON DELETE CASCADE,
    claim_key TEXT NULL REFERENCES research_claims(claim_key) ON DELETE SET NULL,
    evidence_key TEXT NULL REFERENCES research_evidence_units(evidence_key) ON DELETE SET NULL,
    research_id BIGINT NULL REFERENCES parsed_research(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'supporting',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_relation_evidence_has_source
        CHECK (claim_key IS NOT NULL OR evidence_key IS NOT NULL OR research_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_research_relation_evidence_relation_key
    ON research_relation_evidence(relation_key);
CREATE INDEX IF NOT EXISTS idx_research_relation_evidence_claim_key
    ON research_relation_evidence(claim_key);
CREATE INDEX IF NOT EXISTS idx_research_relation_evidence_evidence_key
    ON research_relation_evidence(evidence_key);

-- =============================================================================
-- Table: research_memory_events
-- Append-only deltas for daily digests and world-model export.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research_memory_events (
    id BIGSERIAL PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    research_id BIGINT NULL REFERENCES parsed_research(id) ON DELETE SET NULL,
    document_hash TEXT NULL,
    claim_key TEXT NULL REFERENCES research_claims(claim_key) ON DELETE SET NULL,
    relation_key TEXT NULL REFERENCES research_relations(relation_key) ON DELETE SET NULL,
    entity_key TEXT NULL REFERENCES research_entities(entity_key) ON DELETE SET NULL,
    source_date DATE NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_version TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_memory_events_event_type
    ON research_memory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_event_time
    ON research_memory_events(event_time);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_source_date
    ON research_memory_events(source_date);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_research_id
    ON research_memory_events(research_id);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_claim_key
    ON research_memory_events(claim_key);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_relation_key
    ON research_memory_events(relation_key);
CREATE INDEX IF NOT EXISTS idx_research_memory_events_entity_key
    ON research_memory_events(entity_key);

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE research_document_artifacts IS 'Parser artifact metadata for research documents';
COMMENT ON TABLE research_spans IS 'Stable source-grounded spans for page, section, paragraph, table, or figure text';
COMMENT ON TABLE research_retrieval_chunks IS 'Search-oriented span-backed chunks for hybrid retrieval and agent context';
COMMENT ON TABLE research_evidence_units IS 'Exact cited evidence excerpts supporting claims and relations';
COMMENT ON TABLE research_entities IS 'Canonical entities and concepts used by claims and relations';
COMMENT ON TABLE research_claims IS 'Atomic extracted assertions with provenance and versioning';
COMMENT ON TABLE research_claim_evidence IS 'Many-to-many mapping from claims to supporting or contradicting evidence';
COMMENT ON TABLE research_relations IS 'Typed relations for graph retrieval and world-model export';
COMMENT ON TABLE research_relation_evidence IS 'Evidence and claim provenance for typed relations';
COMMENT ON TABLE research_memory_events IS 'Append-only memory deltas for daily digests and export workflows';

COMMENT ON COLUMN research_spans.span_key IS 'Stable key derived from document hash, span version, and source position';
COMMENT ON COLUMN research_retrieval_chunks.span_keys IS 'Ordered span keys included in the retrieval chunk';
COMMENT ON COLUMN research_claims.claim_key IS 'Stable key derived from normalized claim content and extractor version';
COMMENT ON COLUMN research_relations.relation_key IS 'Stable key derived from relation endpoints, type, condition, and resolver version';
COMMENT ON COLUMN research_memory_events.event_key IS 'Stable idempotency key for append-only memory events';
