-- Nexus analyst schema (Phase 3)
-- Consolidated from AnalysisStore SQLite bootstrap DDL.
-- Includes Slice 2 consensus tables and shadow_street_digest.
-- evals/eval.db and golden JSONL remain SQLite.

CREATE TABLE IF NOT EXISTS analysis_runs (
                    id BIGSERIAL PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_source TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    chunker_version TEXT NOT NULL,
                    assertion_extractor_version TEXT NOT NULL,
                    resolver_version TEXT NOT NULL,
                    selected_watermark TEXT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_run_items (
                    id BIGSERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    research_id INTEGER NULL,
                    document_hash TEXT NULL,
                    status TEXT NOT NULL,
                    selected_reason TEXT NOT NULL,
                    error_type TEXT NULL,
                    error_text TEXT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    assertion_count INTEGER NOT NULL DEFAULT 0,
                    node_upsert_count INTEGER NOT NULL DEFAULT 0,
                    edge_upsert_count INTEGER NOT NULL DEFAULT 0,
                    open_question_count INTEGER NOT NULL DEFAULT 0,
                    quality_score DOUBLE PRECISION NULL,
                    quality_summary_json TEXT NULL,
                    agent_success_count INTEGER NOT NULL DEFAULT 0,
                    agent_no_output_count INTEGER NOT NULL DEFAULT 0,
                    agent_error_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(run_id, file_id)
                );

                CREATE TABLE IF NOT EXISTS analysis_documents (
                    research_id INTEGER PRIMARY KEY,
                    file_id TEXT NULL,
                    document_hash TEXT NOT NULL,
                    source TEXT NULL,
                    source_date TEXT NULL,
                    document_name TEXT NULL,
                    title TEXT NULL,
                    publisher TEXT NULL,
                    area TEXT NULL,
                    region TEXT NULL,
                    asset_focus TEXT NULL,
                    document_link TEXT NULL,
                    parser_updated_at TEXT NULL,
                    ingested_at TEXT NOT NULL,
                    last_analyzed_at TEXT NULL,
                    latest_analysis_version TEXT NULL,
                    latest_successful_run_id INTEGER NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    chunk_type TEXT NOT NULL,
                    section_name TEXT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    topic_tags_json TEXT NOT NULL,
                    entity_tags_json TEXT NOT NULL,
                    horizon_tag TEXT NULL,
                    parser_theme_id INTEGER NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_evidence_units (
                    id BIGSERIAL PRIMARY KEY,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    evidence_order INTEGER NOT NULL,
                    evidence_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NULL,
                    page_ref TEXT NULL,
                    source_ref_json TEXT NOT NULL,
                    parser_theme_id INTEGER NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order, evidence_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_assertions (
                    id BIGSERIAL PRIMARY KEY,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    assertion_order INTEGER NOT NULL,
                    assertion_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    confidence_label TEXT NOT NULL,
                    extraction_confidence TEXT NOT NULL,
                    time_horizon TEXT NOT NULL,
                    time_anchor TEXT NULL,
                    condition_text TEXT NULL,
                    qualifier_text TEXT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_nodes (
                    id BIGSERIAL PRIMARY KEY,
                    node_key TEXT NOT NULL UNIQUE,
                    node_type TEXT NOT NULL,
                    canonical_label TEXT NOT NULL,
                    summary_text TEXT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    support_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_node_aliases (
                    id BIGSERIAL PRIMARY KEY,
                    node_key TEXT NOT NULL,
                    alias_key TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(node_key, alias_key)
                );

                CREATE TABLE IF NOT EXISTS world_edges (
                    id BIGSERIAL PRIMARY KEY,
                    edge_key TEXT NOT NULL UNIQUE,
                    from_node_key TEXT NOT NULL,
                    to_node_key TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    directionality TEXT NOT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    maturity TEXT NOT NULL,
                    support_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_node_evidence (
                    id BIGSERIAL PRIMARY KEY,
                    node_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    evidence_text TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(node_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_edge_evidence (
                    id BIGSERIAL PRIMARY KEY,
                    edge_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    evidence_text TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(edge_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_edge_history (
                    id BIGSERIAL PRIMARY KEY,
                    edge_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    maturity TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(edge_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS forecast_candidates (
                    id BIGSERIAL PRIMARY KEY,
                    research_id INTEGER NOT NULL,
                    file_id TEXT NULL,
                    document_hash TEXT NULL,
                    source TEXT NULL,
                    source_date TEXT NULL,
                    document_name TEXT NULL,
                    document_link TEXT NULL,
                    chunk_order INTEGER NOT NULL,
                    assertion_order INTEGER NOT NULL,
                    assertion_text TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    indicator_key TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    country TEXT NULL,
                    period_text TEXT NULL,
                    release_date TEXT NULL,
                    forecast_type TEXT NOT NULL,
                    forecast_value_numeric DOUBLE PRECISION NULL,
                    forecast_value_low DOUBLE PRECISION NULL,
                    forecast_value_high DOUBLE PRECISION NULL,
                    forecast_value_text TEXT NOT NULL,
                    forecast_unit TEXT NULL,
                    qualifier_text TEXT NULL,
                    extraction_confidence TEXT NOT NULL,
                    match_status TEXT NOT NULL DEFAULT 'unmatched',
                    matched_economic_event_id TEXT NULL,
                    matched_calendar_release_id TEXT NULL,
                    matched_calendar_source TEXT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    review_notes TEXT NULL,
                    upload_status TEXT NOT NULL DEFAULT 'not_uploaded',
                    uploaded_at TEXT NULL,
                    created_run_id INTEGER NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_reviews (
                    id BIGSERIAL PRIMARY KEY,
                    review_scope TEXT NOT NULL,
                    review_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_analysis (
                    id BIGSERIAL PRIMARY KEY,
                    document_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    thesis TEXT,
                    confidence DOUBLE PRECISION,
                    total_input_tokens INTEGER,
                    total_output_tokens INTEGER,
                    total_tool_calls INTEGER,
                    total_duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version)
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_runs_completed_at
                    ON analysis_runs(completed_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_run_items_run_id
                    ON analysis_run_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_analysis_documents_hash
                    ON analysis_documents(document_hash);
                CREATE INDEX IF NOT EXISTS idx_analysis_chunks_doc
                    ON analysis_chunks(research_id, document_hash);
                CREATE INDEX IF NOT EXISTS idx_analysis_assertions_doc
                    ON analysis_assertions(research_id, document_hash);
                CREATE INDEX IF NOT EXISTS idx_world_node_evidence_node_key
                    ON world_node_evidence(node_key);
                CREATE INDEX IF NOT EXISTS idx_world_edge_evidence_edge_key
                    ON world_edge_evidence(edge_key);
                CREATE INDEX IF NOT EXISTS idx_world_edge_history_edge_key
                    ON world_edge_history(edge_key);
                CREATE INDEX IF NOT EXISTS idx_forecast_candidates_review_status
                    ON forecast_candidates(review_status);
                CREATE INDEX IF NOT EXISTS idx_forecast_candidates_indicator_release
                    ON forecast_candidates(indicator_key, release_date);
                CREATE INDEX IF NOT EXISTS idx_analysis_reviews_scope_key
                    ON analysis_reviews(review_scope, review_key);
                CREATE INDEX IF NOT EXISTS document_analysis_research_id_idx
                    ON document_analysis(research_id);
                CREATE INDEX IF NOT EXISTS document_analysis_document_hash_idx
                    ON document_analysis(document_hash);

                -- Debate forum tables
                CREATE TABLE IF NOT EXISTS debate_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL UNIQUE,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version, run_id)
                );

                CREATE TABLE IF NOT EXISTS debate_turns (
                    id BIGSERIAL PRIMARY KEY,
                    turn_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    turn_name TEXT NOT NULL,
                    turn_order INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    target_argument_ids_json TEXT NOT NULL,
                    turn_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debate_arguments (
                    id BIGSERIAL PRIMARY KEY,
                    argument_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    turn_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    thesis_type TEXT NOT NULL,
                    argument_text TEXT NOT NULL,
                    target_claim_id TEXT NULL,
                    cited_chunk_keys_json TEXT NOT NULL,
                    cited_evidence_keys_json TEXT NOT NULL,
                    cited_assertion_keys_json TEXT NOT NULL,
                    uncertainty DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    qualifier_text TEXT NULL,
                    target_instrument TEXT NULL,
                    time_horizon TEXT NULL,
                    invalidation_condition TEXT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debate_relations (
                    id BIGSERIAL PRIMARY KEY,
                    relation_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    source_argument_id TEXT NOT NULL,
                    target_argument_id TEXT NOT NULL,
                    strength DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    explanation TEXT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debate_scores (
                    id BIGSERIAL PRIMARY KEY,
                    score_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    argument_id TEXT NOT NULL,
                    deterministic_features_json TEXT NOT NULL,
                    pairwise_wins INTEGER NOT NULL DEFAULT 0,
                    pairwise_losses INTEGER NOT NULL DEFAULT 0,
                    pairwise_ties INTEGER NOT NULL DEFAULT 0,
                    llm_judge_score DOUBLE PRECISION NULL,
                    final_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debate_verdicts (
                    id BIGSERIAL PRIMARY KEY,
                    verdict_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    argument_id TEXT NOT NULL,
                    verdict_label TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    synthesizes_from_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                -- Debate indexes
                CREATE INDEX IF NOT EXISTS idx_debate_sessions_doc
                    ON debate_sessions(research_id, document_hash, analysis_version);
                CREATE INDEX IF NOT EXISTS idx_debate_sessions_run
                    ON debate_sessions(run_id);
                CREATE INDEX IF NOT EXISTS idx_debate_turns_session
                    ON debate_turns(session_id);
                CREATE INDEX IF NOT EXISTS idx_debate_arguments_session
                    ON debate_arguments(session_id);
                CREATE INDEX IF NOT EXISTS idx_debate_arguments_target
                    ON debate_arguments(target_claim_id);
                CREATE INDEX IF NOT EXISTS idx_debate_relations_session
                    ON debate_relations(session_id);
                CREATE INDEX IF NOT EXISTS idx_debate_relations_source
                    ON debate_relations(source_argument_id);
                CREATE INDEX IF NOT EXISTS idx_debate_relations_target
                    ON debate_relations(target_argument_id);
                CREATE INDEX IF NOT EXISTS idx_debate_scores_session
                    ON debate_scores(session_id);
                CREATE INDEX IF NOT EXISTS idx_debate_scores_argument
                    ON debate_scores(argument_id);
                CREATE INDEX IF NOT EXISTS idx_debate_verdicts_session
                    ON debate_verdicts(session_id);
                CREATE INDEX IF NOT EXISTS idx_debate_verdicts_argument
                    ON debate_verdicts(argument_id);

                CREATE TABLE IF NOT EXISTS shadow_document_analysis (
                    research_id          INTEGER NOT NULL,
                    document_hash        TEXT    NOT NULL,
                    analysis_version     TEXT    NOT NULL,
                    run_id               TEXT    NOT NULL,
                    variant              TEXT    NOT NULL,
                    payload_json         TEXT    NOT NULL,
                    thesis               TEXT,
                    confidence           DOUBLE PRECISION,
                    total_input_tokens   INTEGER,
                    total_output_tokens  INTEGER,
                    total_duration_ms    INTEGER,
                    debate_session_id    TEXT,
                    created_at           TEXT    NOT NULL,
                    PRIMARY KEY (research_id, document_hash, analysis_version, run_id, variant)
                );
                CREATE INDEX IF NOT EXISTS ix_shadow_doc_analysis_session
                    ON shadow_document_analysis(debate_session_id);

                CREATE TABLE IF NOT EXISTS consensus_cluster_state (
                    cluster_key TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    horizon_bucket TEXT NOT NULL,
                    sign TEXT NOT NULL,
                    source_diversity INTEGER NOT NULL,
                    positions_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS consensus_shift_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    cluster_key TEXT NOT NULL,
                    claim_key TEXT NULL,
                    event_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shadow_street_digest (
                    batch_key TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (batch_key, generated_at)
                );
                CREATE INDEX IF NOT EXISTS ix_shadow_street_digest_batch
                    ON shadow_street_digest(batch_key);
                CREATE INDEX IF NOT EXISTS idx_consensus_shift_events_type
                    ON consensus_shift_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_consensus_shift_events_cluster
                    ON consensus_shift_events(cluster_key);


-- Agent output tables
-- Migration: Create agent analysis tables
-- Date: 2026-04-03
-- Description: Tables for multi-agent analysis framework

-- trading_analysis
CREATE TABLE IF NOT EXISTS trading_analysis (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id),
    agent_type TEXT NOT NULL DEFAULT 'trading_opportunities',
    opportunities JSONB NOT NULL DEFAULT '[]',
    no_opportunity_reason TEXT,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(research_id, agent_type)
);

CREATE INDEX IF NOT EXISTS idx_trading_analysis_research_id ON trading_analysis(research_id);
CREATE INDEX IF NOT EXISTS idx_trading_analysis_analyzed_at ON trading_analysis(analyzed_at);

-- short_time_horizon_analysis  
CREATE TABLE IF NOT EXISTS short_time_horizon_analysis (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id),
    agent_type TEXT NOT NULL DEFAULT 'short_time_horizon',
    insights JSONB NOT NULL DEFAULT '[]',
    summary TEXT,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(research_id, agent_type)
);

CREATE INDEX IF NOT EXISTS idx_short_time_horizon_research_id ON short_time_horizon_analysis(research_id);
CREATE INDEX IF NOT EXISTS idx_short_time_horizon_analyzed_at ON short_time_horizon_analysis(analyzed_at);

-- talking_points_analysis
CREATE TABLE IF NOT EXISTS talking_points_analysis (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES parsed_research(id),
    agent_type TEXT NOT NULL DEFAULT 'talking_points',
    talking_points JSONB NOT NULL DEFAULT '[]',
    primary_headline TEXT,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(research_id, agent_type)
);

CREATE INDEX IF NOT EXISTS idx_talking_points_research_id ON talking_points_analysis(research_id);
CREATE INDEX IF NOT EXISTS idx_talking_points_analyzed_at ON talking_points_analysis(analyzed_at);

-- Calendar matching tables (optional external data)
CREATE TABLE IF NOT EXISTS economic_events (
    id BIGSERIAL PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_date DATE,
    country TEXT,
    period TEXT,
    time_ny TEXT
);
CREATE INDEX IF NOT EXISTS idx_economic_events_event_date ON economic_events(event_date);

CREATE TABLE IF NOT EXISTS economic_event_forecasts (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS releases (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    fred_release_id TEXT,
    link TEXT,
    press_release TEXT
);

CREATE TABLE IF NOT EXISTS release_dates (
    id BIGSERIAL PRIMARY KEY,
    release_id BIGINT,
    release_date DATE
);
CREATE INDEX IF NOT EXISTS idx_release_dates_release_date ON release_dates(release_date);
