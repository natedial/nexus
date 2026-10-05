"""Load claim-note fixtures / JSONL dumps."""

from __future__ import annotations

import json
from pathlib import Path

from src.claim_notes.models import ClaimNote
from src.claim_notes.validate import validate_claim_note


def load_claim_notes(path: str | Path, *, validate: bool = True) -> list[ClaimNote]:
    """Load one ClaimNote JSON object per line from a JSONL file."""
    notes: list[ClaimNote] = []
    text = Path(path).read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        note = (
            validate_claim_note(payload)
            if validate
            else ClaimNote.model_validate(payload)
        )
        notes.append(note)
    return notes
