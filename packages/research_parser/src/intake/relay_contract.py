"""R2 relay intake artifact consumed by the parser."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RelayAttachment:
    safe_filename: str
    content_type: str
    sha256: str
    path: str


@dataclass(frozen=True)
class RelayIntakeArtifact:
    relay_key: str
    content_hash: str
    subject: str
    body: str
    sender_address: str
    original_date: str | None
    attachments: tuple[RelayAttachment, ...]
    archive_pdf_drive_ids: dict[str, str]
    bundle_id: str
    manifest_path: Path

    def document_id(self) -> str:
        return relay_document_id(self.relay_key)

    def storage_document_id(self) -> str:
        """Identity shared with a Drive poll of the same archived PDF.

        Bundle directories and ``document_id()`` stay on the relay-key hash.
        When the primary PDF was archived to Drive, storage uses that file id
        so one note is not stored twice.
        """
        pdf_path = self.primary_pdf_path()
        if pdf_path is not None:
            drive_id = str(self.archive_pdf_drive_ids.get(pdf_path.name, "")).strip()
            if drive_id:
                return drive_id
        return relay_document_id(self.relay_key)

    def primary_pdf_path(self) -> Path | None:
        for item in self.attachments:
            if item.path.lower().endswith(".pdf"):
                return self.manifest_path.parent / item.path
        return None

    def source_date(self) -> str | None:
        if not self.original_date:
            return None
        try:
            parsed = datetime.fromisoformat(self.original_date.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.date().isoformat()


def relay_document_id(relay_key: str) -> str:
    return "relay:" + hashlib.sha256(relay_key.encode("utf-8")).hexdigest()[:32]


def load_manifest(path: Path) -> RelayIntakeArtifact:
    data = json.loads(path.read_text(encoding="utf-8"))
    return artifact_from_dict(data, manifest_path=path)


def artifact_from_dict(data: dict[str, Any], *, manifest_path: Path) -> RelayIntakeArtifact:
    attachments = tuple(
        RelayAttachment(
            safe_filename=str(item["safe_filename"]),
            content_type=str(item.get("content_type", "application/octet-stream")),
            sha256=str(item["sha256"]),
            path=str(item["path"]),
        )
        for item in data.get("attachments", [])
    )
    return RelayIntakeArtifact(
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
        manifest_path=manifest_path,
    )
