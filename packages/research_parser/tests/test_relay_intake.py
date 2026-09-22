from __future__ import annotations

import json
from pathlib import Path

from src.intake.relay_adapter import RelayIntakeAdapter
from src.intake.relay_contract import relay_document_id
from src.pipeline import build_source_document_from_relay
from src.source import SourceDocument
from src.storage.source_store import build_parsed_research_record
from src.storage.state import StateStore


def _write_bundle(
    handoff_dir: Path,
    relay_key: str,
    content_hash: str,
    *,
    archive_pdf_drive_ids: dict[str, str] | None = None,
) -> None:
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
        "archive_pdf_drive_ids": (
            {pdf_name: "drive-pdf-1"}
            if archive_pdf_drive_ids is None
            else archive_pdf_drive_ids
        ),
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


def test_storage_document_id_uses_primary_pdf_drive_id(tmp_path: Path) -> None:
    relay_key = "proton:<abc@example.com>"
    _write_bundle(tmp_path, relay_key, "hash-1")
    artifact = RelayIntakeAdapter(tmp_path).list_pending()[0]
    pdf_name = "2026-03-21_note_report.pdf"

    assert artifact.document_id() == relay_document_id(relay_key)
    assert artifact.storage_document_id() == "drive-pdf-1"

    source = build_source_document_from_relay(artifact, pdf_name, "Cleaned note text")
    assert source.document_id == "drive-pdf-1"
    assert source.relay_key == relay_key
    assert source.document_uri == f"relay://{relay_key}"
    assert source.document_link == "https://drive.google.com/file/d/drive-pdf-1/view"

    record = build_parsed_research_record(source, pdf_name)
    assert record["document_id"] == "drive-pdf-1"
    assert record["parsed_data"]["identity"]["document_id"] == "drive-pdf-1"
    assert record["parsed_data"]["identity"]["relay_key"] == relay_key
    assert record["parsed_data"]["identity"]["document_uri"] == f"relay://{relay_key}"


def test_storage_document_id_falls_back_to_relay_hash(tmp_path: Path) -> None:
    relay_key = "proton:<abc@example.com>"
    _write_bundle(tmp_path, relay_key, "hash-1", archive_pdf_drive_ids={})
    artifact = RelayIntakeAdapter(tmp_path).list_pending()[0]

    assert artifact.storage_document_id() == relay_document_id(relay_key)
    assert artifact.document_id() == relay_document_id(relay_key)

    source = build_source_document_from_relay(artifact, "note.pdf", "Cleaned note text")
    assert source.document_id == relay_document_id(relay_key)
    assert source.relay_key == relay_key
    assert source.document_link is None

    record = build_parsed_research_record(source, "note.pdf")
    assert record["document_id"] == relay_document_id(relay_key)
    assert record["parsed_data"]["identity"]["relay_key"] == relay_key


def test_parsed_identity_omits_relay_key_when_unset() -> None:
    source = SourceDocument(
        document_id="drive-file-9",
        document_name="note.pdf",
        full_text="Cleaned note text",
        source="Goldman Sachs",
        source_date="2026-03-21",
    )
    record = build_parsed_research_record(source, "note.pdf")
    assert "relay_key" not in record["parsed_data"]["identity"]
