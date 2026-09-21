"""R2 intake artifact contract shared by relay (producer) and parser (consumer)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from research_relay.attachments import AttachmentDecision
from research_relay.reconstruct import Reconstruction

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IntakeAttachment:
    safe_filename: str
    content_type: str
    sha256: str
    path: str


@dataclass(frozen=True)
class IntakeManifest:
    schema_version: int
    relay_key: str
    content_hash: str
    subject: str
    body: str
    sender_address: str
    original_date: str | None
    attachments: tuple[IntakeAttachment, ...]
    archive_pdf_drive_ids: dict[str, str]
    bundle_id: str
    archive_kind: str = "pdfs"
    archive_html_drive_id: str = ""

    def to_json(self) -> str:
        payload = asdict(self)
        payload["attachments"] = [asdict(item) for item in self.attachments]
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeManifest":
        attachments = tuple(
            IntakeAttachment(
                safe_filename=str(item["safe_filename"]),
                content_type=str(item.get("content_type", "application/octet-stream")),
                sha256=str(item["sha256"]),
                path=str(item["path"]),
            )
            for item in data.get("attachments", [])
        )
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            relay_key=str(data["relay_key"]),
            content_hash=str(data["content_hash"]),
            subject=str(data.get("subject", "")),
            body=str(data.get("body", "")),
            sender_address=str(data.get("sender_address", "")),
            original_date=str(data["original_date"]) if data.get("original_date") else None,
            attachments=attachments,
            archive_pdf_drive_ids={
                str(key): str(value)
                for key, value in dict(data.get("archive_pdf_drive_ids", {})).items()
            },
            bundle_id=str(data["bundle_id"]),
            archive_kind=str(data.get("archive_kind", "pdfs")),
            archive_html_drive_id=str(data.get("archive_html_drive_id", "")),
        )


def bundle_id_for_relay_key(relay_key: str) -> str:
    return hashlib.sha256(relay_key.encode("utf-8")).hexdigest()[:32]


def compute_content_hash(subject: str, body: str, attachment_digests: list[str]) -> str:
    parts = [subject, body] + sorted(attachment_digests)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _sanitized_body_text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    content = part.get_content()
    return content if isinstance(content, str) else str(content)


def _original_date_iso(original: EmailMessage) -> str | None:
    raw = str(original.get("Date") or "").strip()
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.isoformat()


def build_intake_manifest(
    *,
    relay_key: str,
    reconstructed: Reconstruction,
    original: EmailMessage,
    archive_pdf_names: dict[str, str],
    archive_pdf_drive_ids: dict[str, str],
    attachment_files: dict[str, bytes],
) -> IntakeManifest:
    subject = str(reconstructed.message.get("Subject") or "")
    body = _sanitized_body_text(reconstructed.message)
    digests: list[str] = []
    attachments: list[IntakeAttachment] = []
    for item in reconstructed.attachments:
        if item.action != AttachmentDecision.ALLOW:
            continue
        digest = hashlib.sha256(item.payload).hexdigest()
        digests.append(digest)
        archive_name = archive_pdf_names.get(item.safe_filename)
        if archive_name is None:
            continue
        local_name = attachment_files.get(archive_name)
        if local_name is None:
            continue
        attachments.append(
            IntakeAttachment(
                safe_filename=item.safe_filename,
                content_type=item.content_type,
                sha256=digest,
                path=local_name,
            )
        )
    content_hash = compute_content_hash(subject, body, digests)
    bundle_id = bundle_id_for_relay_key(relay_key)
    return IntakeManifest(
        schema_version=SCHEMA_VERSION,
        relay_key=relay_key,
        content_hash=content_hash,
        subject=subject,
        body=body,
        sender_address=reconstructed.sender_address,
        original_date=_original_date_iso(original),
        attachments=tuple(attachments),
        archive_pdf_drive_ids=dict(archive_pdf_drive_ids),
        bundle_id=bundle_id,
    )
