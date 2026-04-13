from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import (
    AnalysisChunkDraft,
    AssertionDraft,
    EvidenceUnitDraft,
    EdgeResolution,
    HydratedParsedDocument,
    NodeResolution,
    ParsedDocument,
)
from research_analysis_layer.services.lifecycle import LifecycleService
from research_analysis_layer.services.review_harness import ReviewHarness


def make_settings(db_path: Path) -> Settings:
    return Settings(
        analysis_db_url=f"sqlite:///{db_path}",
        parsed_db_url="https://example.supabase.co",
        parsed_db_key="secret",
        calendar_db_url="https://calendar.example.supabase.co",
        calendar_db_key="calendar-secret",
        calendar_match_source="economic_events",
        calendar_source_name="economic_events",
        state_db_path=Path("data/state.db"),
        batch_size=25,
        cron_mode_enabled=True,
        analysis_version="bootstrap-v1",
        chunker_version="deterministic-theme-v1",
        assertion_extractor_version="deterministic-theme-v2",
        resolver_version="bootstrap-v2",
        request_timeout_seconds=30,
        min_full_text_chars=500,
        min_quality_score=0.6,
        min_usable_theme_ratio=0.6,
        backfill_require_warning_free=True,
    )


class LifecycleAndReviewTest(unittest.TestCase):
    def test_refreshes_lifecycle_and_builds_document_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(Path(tmpdir) / "analysis.db")
            store = AnalysisStore(settings.analysis_db_path)
            run = store.create_run("debug", "test", settings)
            document = HydratedParsedDocument(
                document=ParsedDocument(
                    id=42,
                    document_name="macro_note.pdf",
                    source="Goldman Sachs",
                    source_date="2026-03-31",
                    parsed_data={"metadata": {"document_id": "file-42"}},
                    document_link="https://example.com/doc.pdf",
                    theme_count=1,
                    document_hash="hash-42",
                ),
                themes=[],
                file_id="file-42",
            )
            store.replace_document_analysis(
                run_id=run.id,
                parser_updated_at=datetime.fromisoformat("2026-03-31T00:00:00+00:00"),
                document=document,
                chunks=[
                    AnalysisChunkDraft(
                        chunk_order=1,
                        chunk_type="market_view",
                        title="Dollar pressure",
                        text="Higher tariff risk drives a stronger dollar.",
                    )
                ],
                evidence_units=[
                    EvidenceUnitDraft(
                        chunk_order=1,
                        evidence_order=1,
                        evidence_type="theme_context",
                        text="Higher tariff risk drives a stronger dollar.",
                    )
                ],
                assertions=[
                    AssertionDraft(
                        chunk_order=1,
                        assertion_order=1,
                        assertion_type="market_impact",
                        text="Higher tariff risk drives a stronger dollar.",
                        normalized_text="higher tariff risk drives a stronger dollar",
                        summary_text="Dollar pressure",
                        subject_text="Higher tariff risk",
                        object_text="a stronger dollar",
                    )
                ],
            )
            store.set_document_analysis_version(
                research_id=42,
                analysis_version=settings.analysis_version,
                run_id=run.id,
            )
            nodes = [
                NodeResolution(
                    node_key="concept:higher tariff risk",
                    node_type="concept",
                    canonical_label="Higher tariff risk",
                    evidence_text="Higher tariff risk drives a stronger dollar.",
                    chunk_order=1,
                    assertion_order=1,
                ),
                NodeResolution(
                    node_key="concept:a stronger dollar",
                    node_type="concept",
                    canonical_label="a stronger dollar",
                    evidence_text="Higher tariff risk drives a stronger dollar.",
                    chunk_order=1,
                    assertion_order=1,
                ),
            ]
            edges = [
                EdgeResolution(
                    edge_key="impacts:concept:higher tariff risk->concept:a stronger dollar",
                    from_node_key="concept:higher tariff risk",
                    to_node_key="concept:a stronger dollar",
                    edge_type="impacts",
                    evidence_text="Higher tariff risk drives a stronger dollar.",
                    chunk_order=1,
                    assertion_order=1,
                )
            ]

            store.upsert_world_nodes(nodes)
            store.upsert_world_edges(edges)
            store.record_graph_provenance(
                run_id=run.id,
                research_id=42,
                document_hash="hash-42",
                nodes=nodes,
                edges=edges,
            )
            lifecycle = LifecycleService(store)
            lifecycle.evaluate_temporal_updates(nodes, edges)

            payload = ReviewHarness(store).review_document(research_id=42)

        assert payload is not None
        self.assertEqual(len(payload["world_nodes"]), 2)
        self.assertEqual(len(payload["world_edges"]), 1)
        self.assertGreaterEqual(payload["review_id"], 1)


if __name__ == "__main__":
    unittest.main()
