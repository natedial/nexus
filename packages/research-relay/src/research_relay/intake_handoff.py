"""Write parser-facing intake handoff bundles after archive completion."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from research_relay.intake_contract import (
    IntakeAttachment,
    IntakeManifest,
    SCHEMA_VERSION,
    compute_content_hash,
)
from research_relay.ledger import ArchiveRow, Ledger
from research_relay.reconstruct import Reconstruction

log = logging.getLogger("research_relay")


def _sanitized_body_text(reconstructed: Reconstruction) -> str:
    part = reconstructed.message.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    content = part.get_content()
    return content if isinstance(content, str) else str(content)


def write_intake_handoff(
    handoff_dir: Path,
    *,
    relay_key: str,
    reconstructed: Reconstruction,
    original_date: str | None,
    row: ArchiveRow,
    file_payloads: dict[str, tuple[bytes, str]],
    bundle_id: str,
    archive_kind: str,
) -> IntakeManifest | None:
    """Persist a manifest and archived file copies for parser intake."""
    if not file_payloads:
        return None
    bundle_dir = handoff_dir / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    subject = str(reconstructed.message.get("Subject") or "")
    body = _sanitized_body_text(reconstructed)
    attachments: list[IntakeAttachment] = []
    digests: list[str] = []
    for archive_name, (payload, content_type) in sorted(file_payloads.items()):
        target = bundle_dir / archive_name
        target.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        digests.append(digest)
        attachments.append(
            IntakeAttachment(
                safe_filename=archive_name,
                content_type=content_type,
                sha256=digest,
                path=archive_name,
            )
        )

    manifest = IntakeManifest(
        schema_version=SCHEMA_VERSION,
        relay_key=relay_key,
        content_hash=compute_content_hash(subject, body, digests),
        subject=subject,
        body=body,
        sender_address=reconstructed.sender_address,
        original_date=original_date,
        attachments=tuple(attachments),
        archive_pdf_drive_ids=dict(row.pdf_ids),
        bundle_id=bundle_id,
        archive_kind=archive_kind,
        archive_html_drive_id=row.html_id,
    )
    (bundle_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    log.info(
        "intake handoff written key=%s bundle=%s kind=%s files=%d",
        relay_key[-24:],
        bundle_id,
        archive_kind,
        len(file_payloads),
    )
    return manifest


def maybe_write_intake_handoff(
    handoff_dir: Path,
    ledger: Ledger,
    *,
    relay_key: str,
    reconstructed: Reconstruction,
    original_date: str | None,
    row: ArchiveRow,
    file_payloads: dict[str, tuple[bytes, str]],
    bundle_id: str,
    archive_kind: str,
) -> bool:
    if row.intake_written_at:
        return False
    manifest = write_intake_handoff(
        handoff_dir,
        relay_key=relay_key,
        reconstructed=reconstructed,
        original_date=original_date,
        row=row,
        file_payloads=file_payloads,
        bundle_id=bundle_id,
        archive_kind=archive_kind,
    )
    if manifest is None:
        return False
    ledger.mark_intake_written(relay_key, manifest.content_hash, manifest.bundle_id)
    return True
