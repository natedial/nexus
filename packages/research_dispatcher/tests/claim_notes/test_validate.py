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
        commissioned_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
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
                "speaker": "GS",
                "thread_role": "assert",
                "time_window": {"label": "H1"},
                "support_kind": "ingested_document_text",
                "speaker_weight": 0.2,
                "cause_edges": [{"cause": "x", "effect": "y"}],
            }
        )
        self.assertEqual(len(note.cause_edges), 1)

    def test_commissioned_live_note_valid_but_findings_blocked(self):
        note = ClaimNote(
            note_id="n2",
            claim="ISM below 50",
            speaker="desk",
            thread_role="assert",
            time_window=TimeWindow(label="latest"),
            support_kind="live_data",
            speaker_weight=0.3,
            dexter_pass=DexterResearchPass(
                pass_id="d2",
                commissioned_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
                query="ISM",
                status="commissioned",
            ),
        )
        validate_claim_note(note)
        self.assertFalse(live_findings_allowed(note))
        with self.assertRaises(ClaimNoteValidationError):
            require_live_findings(note)

    def test_completed_pass_allows_findings(self):
        note = ClaimNote(
            note_id="n3",
            claim="payrolls miss",
            speaker="desk",
            thread_role="assert",
            time_window=TimeWindow(label="Sep"),
            support_kind="live_data",
            speaker_weight=0.9,
            dexter_pass=_completed_pass(),
        )
        self.assertTrue(live_findings_allowed(note))
        require_live_findings(note)


if __name__ == "__main__":
    unittest.main()
