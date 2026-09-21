from __future__ import annotations

import json
from pathlib import Path

from src.intake.relay_adapter import RelayIntakeAdapter
from src.intake.relay_contract import relay_document_id
from src.storage.state import StateStore


def _write_bundle(handoff_dir: Path, relay_key: str, content_hash: str) -> None:
    bundle_id = relay_document_id(relay_key).removeprefix("relay:")
    bundle_dir = handoff_dir / bundle_id
    bundle_dir.mkdir(parents=True)
    pdf_name = "2026-03-21_note_report.pdf"
    (bundle_dir / pdf_name).write_bytes(b"%PDF-1.4 test")
    manifest = {
        "schema_version": 1,
        "relay_key": relay_key,
        "content_hash": content_hash,
        "subject": "Rates note",
        "body": "Sanitized body",
        "sender_address": "sender@example.com",
        "original_date": "2026-03-21T12:00:00+00:00",
        "attachments": [
            {
                "safe_filename": pdf_name,
                "content_type": "application/pdf",
                "sha256": "abc",
                "path": pdf_name,
            }
        ],
        "archive_pdf_drive_ids": {pdf_name: "drive-pdf-1"},
        "bundle_id": bundle_id,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_relay_intake_adapter_lists_manifests(tmp_path: Path) -> None:
    relay_key = "proton:<abc@example.com>"
    _write_bundle(tmp_path, relay_key, "hash-1")
    artifacts = RelayIntakeAdapter(tmp_path).list_pending()
    assert len(artifacts) == 1
    assert artifacts[0].relay_key == relay_key
    assert artifacts[0].document_id() == relay_document_id(relay_key)


def test_relay_intake_idempotency(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.db")
    relay_key = "proton:<abc@example.com>"
    content_hash = "hash-1"
    document_id = relay_document_id(relay_key)
    assert not state.is_relay_intake_complete(relay_key, content_hash)
    state.record_relay_intake(
        relay_key,
        content_hash=content_hash,
        document_id=document_id,
        file_id=document_id,
        storage_ok=True,
    )
    assert state.is_relay_intake_complete(relay_key, content_hash)
    assert not state.is_relay_intake_complete(relay_key, "hash-2")
