"""Product-facing validation helpers for claim notes."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from src.claim_notes.models import (
    ClaimNote,
    DexterFinding,
    DexterResearchPass,
    DexterSource,
    TimeWindow,
)
from src.claim_notes.validate import (
    ClaimNoteValidationError,
    live_findings_allowed,
    require_live_findings,
    validate_claim_note,
)


def _completed_pass() -> DexterResearchPass:
    return DexterResearchPass(
        pass_id="d1",
        requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 4, 1, tzinfo=timezone.utc),
        query="payrolls",
        status="completed",
        sources=[
            DexterSource(name="BLS", retrieved_at=date(2026, 10, 4))
        ],
        findings=[
            DexterFinding(
                label="payrolls",
                value="120000",
                as_of=date(2026, 9, 1),
                source_index=0,
            )
        ],
    )


class ValidateTests(unittest.TestCase):
    def test_validate_accepts_dict(self):
        note = validate_claim_note(
            {
                "note_id": "n1",
                "claim": "c",
                "speaker": "GS strategist",
                "publisher": "Goldman Sachs",
                "thread_role": "assert",
                "time_window": {"label": "H1"},
                "support_kind": "ingested_document_text",
                "speaker_weight": "research_author",
                "cause_edges": [{"cause": "x", "effect": "y"}],
            }
        )
        self.assertEqual(len(note.cause_edges), 1)
        self.assertEqual(note.speaker_weight, "research_author")

    def test_awaiting_pointer_valid_but_findings_blocked(self):
        note = ClaimNote(
            note_id="n2",
            claim="ISM below 50",
            speaker="desk",
            thread_role="assert",
            time_window=TimeWindow(label="latest"),
            support_kind="live_data",
            speaker_weight="research_author",
            dexter_pass=DexterResearchPass(
                pass_id="d2",
                requested_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
                query="ISM",
                status="awaiting",
            ),
        )
        validate_claim_note(note)
        self.assertFalse(live_findings_allowed(note))
        with self.assertRaises(ClaimNoteValidationError) as ctx:
            require_live_findings(note)
        self.assertIn("awaiting", str(ctx.exception))

    def test_completed_attachment_allows_findings(self):
        note = ClaimNote(
            note_id="n3",
            claim="payrolls miss",
            speaker="desk",
            thread_role="assert",
            time_window=TimeWindow(label="Sep"),
            support_kind="live_data",
            speaker_weight="research_author",
            dexter_pass=_completed_pass(),
        )
        self.assertTrue(live_findings_allowed(note))
        require_live_findings(note)


if __name__ == "__main__":
    unittest.main()
