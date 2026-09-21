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
    archive_kind: str = "pdfs"
    archive_html_drive_id: str = ""

    def document_id(self) -> str:
        return relay_document_id(self.relay_key)

    def is_html_only(self) -> bool:
        return self.archive_kind == "html"

    def primary_pdf_path(self) -> Path | None:
        for item in self.attachments:
            if item.path.lower().endswith(".pdf"):
                return self.manifest_path.parent / item.path
        return None

    def primary_html_path(self) -> Path | None:
        for item in self.attachments:
            if item.path.lower().endswith(".html"):
                return self.manifest_path.parent / item.path
        return None

    def is_processable(self) -> bool:
        if self.is_html_only():
            return bool(self.body.strip()) or self.primary_html_path() is not None
        return self.primary_pdf_path() is not None

    def intake_file_name(self) -> str:
        if self.is_html_only():
            html_path = self.primary_html_path()
            if html_path is not None:
                return html_path.name
            return f"{self.source_date() or 'relay'}_{self.subject or 'message'}.html"
        pdf_path = self.primary_pdf_path()
        if pdf_path is not None:
            return pdf_path.name
        return f"{self.source_date() or 'relay'}_relay.pdf"

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
        archive_kind=str(data.get("archive_kind", "pdfs")),
        archive_html_drive_id=str(data.get("archive_html_drive_id", "")),
    )
