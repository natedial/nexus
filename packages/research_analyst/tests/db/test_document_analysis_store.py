"""Tests for document_analysis and debate review payloads."""

import json

from research_analysis_layer.db.analysis_store import AnalysisStore


def test_build_document_review_includes_latest_debate_session(tmp_path):
    store = AnalysisStore(tmp_path / "analysis.db")

    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_documents (
                research_id, file_id, document_hash, source, source_date,
                document_name, title, publisher, area, region, asset_focus,
                document_link, ingested_at, last_analyzed_at,
                latest_analysis_version, latest_successful_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                101,
                "file-101",
                "hash-101",
                "test",
                "2026-04-15",
                "doc.pdf",
                "Doc",
                "Publisher",
                None,
                None,
                None,
                None,
                "2026-04-15T00:00:00+00:00",
                "2026-04-15T00:00:00+00:00",
                "v1",
                11,
            ),
        )
        conn.execute(
            """
            INSERT INTO analysis_chunks (
                research_id, document_hash, chunk_order, chunk_type, section_name,
                title, text, topic_tags_json, entity_tags_json, horizon_tag,
                parser_theme_id, created_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                101,
                "hash-101",
                1,
                "theme",
                None,
                "Title",
                "Chunk text",
                json.dumps(["rates"]),
                json.dumps(["UST"]),
                "weeks",
                None,
                11,
            ),
        )
        conn.execute(
            """
            INSERT INTO analysis_assertions (
                research_id, document_hash, chunk_order, assertion_order, assertion_type,
                text, normalized_text, summary_text, polarity, confidence_label,
                extraction_confidence, time_horizon, time_anchor, condition_text,
                qualifier_text, status, authority_band, created_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                101,
                "hash-101",
                1,
                1,
                "forecast",
                "Rates stay high.",
                "rates stay high",
                "Higher for longer rates",
                "positive",
                "high",
                "high",
                "weeks",
                None,
                None,
                None,
                "supported",
                "high",
                11,
            ),
        )
        conn.execute(
            """
            INSERT INTO analysis_run_items (
                run_id, file_id, research_id, document_hash, status, selected_reason,
                quality_score, quality_summary_json, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                11,
                "file-101",
                101,
                "hash-101",
                "success",
                "selected",
                0.9,
                json.dumps({"passed": True, "warnings": []}),
                "2026-04-15T00:00:00+00:00",
                "2026-04-15T00:01:00+00:00",
            ),
        )

    store.write_document_analysis(
        document_key="doc:101:hash-101",
        research_id=101,
        document_hash="hash-101",
        analysis_version="v1",
        run_id="11",
        payload_json=json.dumps({"thesis": "thesis"}),
        thesis="thesis",
        confidence=0.8,
        total_input_tokens=10,
        total_output_tokens=5,
        total_tool_calls=0,
        total_duration_ms=250,
    )
    store.create_debate_session("sess-101", 101, "hash-101", "v1", 11)
    store.write_debate_turn(
        "turn-1",
        "sess-101",
        "proposal",
        1,
        "proposer_thesis",
        [],
        "Opened the thesis case.",
    )
    store.write_debate_arguments(
        [
            {
                "argument_id": "arg-1",
                "session_id": "sess-101",
                "turn_name": "proposal",
                "agent_name": "proposer_thesis",
                "thesis_type": "thesis",
                "argument_text": "Rates stay higher for longer.",
                "cited_assertion_keys": ["chunk-1:assertion-1"],
            }
        ]
    )
    store.write_debate_scores(
        [
            {
                "score_id": "score-1",
                "session_id": "sess-101",
                "argument_id": "arg-1",
                "deterministic_features": {"evidence_count": 1},
                "final_score": 0.71,
            }
        ]
    )
    store.write_debate_verdicts(
        [
            {
                "verdict_id": "verdict-1",
                "session_id": "sess-101",
                "argument_id": "arg-1",
                "verdict_label": "accepted",
                "reason": "Best-supported argument.",
                "synthesizes_from": [],
            }
        ]
    )

    review = store.build_document_review(research_id=101, document_hash="hash-101")

    assert review is not None
    assert review["document_analysis"]["document_key"] == "doc:101:hash-101"
    assert review["debate_session"]["session_id"] == "sess-101"
    assert review["debate_turns"][0]["turn_name"] == "proposal"
    assert review["debate_arguments"][0]["argument_id"] == "arg-1"
    assert review["debate_scores"][0]["argument_id"] == "arg-1"
    assert review["debate_verdicts"][0]["verdict_label"] == "accepted"


def _argument_map_analysis_payload() -> str:
    from research_analysis_layer.models.agent_outputs import (
        AgentExecutionMetadata,
        ClaimNode,
        DocumentAnalysis,
        EvidenceRef,
    )

    analysis = DocumentAnalysis(
        document_key="doc:101:hash-101",
        research_id=101,
        document_hash="hash-101",
        analysis_version="argmap-v1",
        thesis="thesis",
        contrarian_view="counter",
        recommended_positioning="hold",
        confidence=0.8,
        metadata=AgentExecutionMetadata(
            research_id=101,
            document_hash="hash-101",
            analysis_version="argmap-v1",
            agent_type="synthesizer",
            model_requested="m",
            model_used="m",
            prompt_path="p",
            prompt_version="v",
            run_id=11,
            attempt_count=1,
        ),
        argument_map=[
            ClaimNode(
                claim="the Fed is done hiking",
                rationale="dots dropped the last hike",
                support_strength="evidenced",
                evidence=[
                    EvidenceRef(text="December dots", ref_key="assertion:chunk-2:1")
                ],
            ),
            ClaimNode(
                claim="first cut in Q2",
                rationale="median dot implies an earlier move",
                support_strength="reasoned",
            ),
        ],
    )
    return analysis.model_dump_json()


def test_build_document_review_surfaces_argument_map(tmp_path):
    store = AnalysisStore(tmp_path / "analysis.db")

    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_documents (
                research_id, file_id, document_hash, source, source_date,
                document_name, title, publisher, area, region, asset_focus,
                document_link, ingested_at, last_analyzed_at,
                latest_analysis_version, latest_successful_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                101,
                "file-101",
                "hash-101",
                "test",
                "2026-04-15",
                "doc.pdf",
                "Doc",
                "Publisher",
                None,
                None,
                None,
                None,
                "2026-04-15T00:00:00+00:00",
                "2026-04-15T00:00:00+00:00",
                "argmap-v1",
                11,
            ),
        )

    store.write_document_analysis(
        document_key="doc:101:hash-101",
        research_id=101,
        document_hash="hash-101",
        analysis_version="argmap-v1",
        run_id="11",
        payload_json=_argument_map_analysis_payload(),
        thesis="thesis",
        confidence=0.8,
        total_input_tokens=10,
        total_output_tokens=5,
        total_tool_calls=0,
        total_duration_ms=250,
    )

    review = store.build_document_review(research_id=101, document_hash="hash-101")
    assert review is not None
    argument_map = review["document_analysis"]["payload_json"]["argument_map"]
    assert [c["claim"] for c in argument_map] == [
        "the Fed is done hiking",
        "first cut in Q2",
    ]
    assert argument_map[0]["rationale"] == "dots dropped the last hike"
    assert argument_map[0]["support_strength"] == "evidenced"
    assert argument_map[1]["rationale"] == "median dot implies an earlier move"
    assert argument_map[1]["support_strength"] == "reasoned"
