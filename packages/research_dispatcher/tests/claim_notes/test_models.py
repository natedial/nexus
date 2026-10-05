"""Unit tests for claim-note-v1 models."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError

from src.claim_notes.models import (
    CLAIM_NOTE_SCHEMA_VERSION,
    CauseEdge,
    ClaimNote,
    DexterFinding,
    DexterResearchPass,
    DexterSource,
    TimeWindow,
)


def _base_kwargs(**overrides):
    data = {
        "note_id": "n1",
        "claim": "test claim",
        "speaker": "GS strategist",
        "publisher": "Goldman Sachs",
        "thread_role": "assert",
        "time_window": TimeWindow(label="2026 H1"),
        "support_kind": "ingested_document_text",
        "speaker_weight": "research_author",
    }
    data.update(overrides)
    return data


class ClaimNoteModelTests(unittest.TestCase):
    def test_schema_version_constant(self):
        self.assertEqual(CLAIM_NOTE_SCHEMA_VERSION, "claim-note-v1")
        note = ClaimNote(**_base_kwargs())
        self.assertEqual(note.schema_version, "claim-note-v1")

    def test_speaker_weight_is_role_not_float(self):
        for role in (
            "chair",
            "voter",
            "non-voter",
            "interview",
            "research_author",
        ):
            note = ClaimNote(**_base_kwargs(speaker_weight=role))
            self.assertEqual(note.speaker_weight, role)
        with self.assertRaises(ValidationError):
            ClaimNote(**_base_kwargs(speaker_weight=0.8))
        with self.assertRaises(ValidationError):
            ClaimNote(**_base_kwargs(speaker_weight="primary"))

    def test_speaker_and_publisher_stay_distinct(self):
        note = ClaimNote(
            **_base_kwargs(
                speaker="Jerome Powell",
                publisher="Federal Reserve Board",
                speaker_weight="chair",
            )
        )
        self.assertEqual(note.speaker, "Jerome Powell")
        self.assertEqual(note.publisher, "Federal Reserve Board")
        self.assertNotEqual(note.speaker, note.publisher)

    def test_cause_edge_is_own_field_separate_from_thread_role(self):
        note = ClaimNote(
            **_base_kwargs(
                thread_role="assert",
                cause_edges=[
                    CauseEdge(
                        cause="sticky inflation",
                        effect="delayed cuts",
                        polarity="supports",
                        as_stated="inflation keeps policy restrictive",
                    )
                ],
            )
        )
        self.assertEqual(note.thread_role, "assert")
        self.assertEqual(len(note.cause_edges), 1)
        self.assertEqual(note.cause_edges[0].cause, "sticky inflation")
        self.assertFalse(hasattr(note.cause_edges[0], "verified"))
        self.assertFalse(hasattr(note.cause_edges[0], "world_model_id"))

    def test_empty_cause_edges_allowed(self):
        note = ClaimNote(**_base_kwargs(cause_edges=[]))
        self.assertEqual(note.cause_edges, [])

    def test_cause_edge_rejects_blank(self):
        with self.assertRaises(ValidationError):
            CauseEdge(cause="  ", effect="x")

    def test_extend_requires_thread_target(self):
        with self.assertRaises(ValidationError):
            ClaimNote(**_base_kwargs(thread_role="extend"))

    def test_break_with_target_ok(self):
        note = ClaimNote(
            **_base_kwargs(
                thread_role="break",
                thread_target_note_id="n0",
            )
        )
        self.assertEqual(note.thread_target_note_id, "n0")

    def test_live_data_requires_dexter_pass(self):
        with self.assertRaises(ValidationError):
            ClaimNote(**_base_kwargs(support_kind="live_data"))

    def test_ingested_rejects_dexter_pass(self):
        pass_ = DexterResearchPass(
            pass_id="d1",
            requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
            query="q",
            status="awaiting",
        )
        with self.assertRaises(ValidationError):
            ClaimNote(**_base_kwargs(dexter_pass=pass_))

    def test_awaiting_pointer_forbids_findings(self):
        with self.assertRaises(ValidationError):
            DexterResearchPass(
                pass_id="d1",
                requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
                query="q",
                status="awaiting",
                sources=[
                    DexterSource(name="BLS", retrieved_at=date(2026, 10, 4))
                ],
                findings=[
                    DexterFinding(
                        label="x",
                        value="1",
                        as_of=date(2026, 9, 1),
                        source_index=0,
                    )
                ],
            )

    def test_completed_dexter_pass_requires_sources_and_findings(self):
        with self.assertRaises(ValidationError):
            DexterResearchPass(
                pass_id="d1",
                requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
                completed_at=datetime(2026, 10, 4, 1, tzinfo=timezone.utc),
                query="q",
                status="completed",
            )

    def test_completed_dexter_attachment_ok(self):
        pass_ = DexterResearchPass(
            pass_id="d1",
            requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
            completed_at=datetime(2026, 10, 4, 1, tzinfo=timezone.utc),
            query="payrolls",
            status="completed",
            sources=[
                DexterSource(
                    name="BLS",
                    retrieved_at=date(2026, 10, 4),
                    published_at=date(2026, 10, 3),
                )
            ],
            findings=[
                DexterFinding(
                    label="payrolls",
                    value="120000",
                    unit="jobs",
                    as_of=date(2026, 9, 1),
                    source_index=0,
                )
            ],
        )
        note = ClaimNote(
            **_base_kwargs(support_kind="live_data", dexter_pass=pass_)
        )
        self.assertEqual(note.dexter_pass.findings[0].value, "120000")
        self.assertEqual(note.dexter_pass.status, "completed")

    def test_time_window_requires_anchor(self):
        with self.assertRaises(ValidationError):
            TimeWindow()

    def test_json_roundtrip_preserves_cause_edges_and_role(self):
        note = ClaimNote(
            **_base_kwargs(
                speaker_weight="voter",
                cause_edges=[
                    CauseEdge(cause="a", effect="b", polarity="undermines")
                ],
            )
        )
        restored = ClaimNote.model_validate_json(note.model_dump_json())
        self.assertEqual(restored.cause_edges[0].polarity, "undermines")
        self.assertEqual(restored.speaker_weight, "voter")
        self.assertEqual(restored.schema_version, "claim-note-v1")


if __name__ == "__main__":
    unittest.main()
