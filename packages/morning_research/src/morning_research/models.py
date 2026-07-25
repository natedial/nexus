"""Shared data models for the morning-research pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CandidateDoc:
    """A Google Drive PDF pulled down for this run, before/after prefiltering."""

    file_id: str
    name: str
    mime_type: str
    modified_time: datetime
    created_time: datetime
    size_bytes: int
    content_hash: str
    """sha256:<hex> of the downloaded bytes."""
    local_path: Path
    head_revision_id: str | None = None
    md5_checksum: str | None = None
    excluded: bool = False
    exclusion_reason: str | None = None

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "modified_time": self.modified_time.isoformat(),
            "created_time": self.created_time.isoformat(),
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "local_path": str(self.local_path),
            "head_revision_id": self.head_revision_id,
            "md5_checksum": self.md5_checksum,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass
class ProcessedDocumentRecord:
    """A single entry in state.processed_documents."""

    file_id: str
    file_name: str
    content_hash: str
    publication_date: str | None
    drive_modified_timestamp: str
    date_first_processed: str
    date_last_processed: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "content_hash": self.content_hash,
            "publication_date": self.publication_date,
            "drive_modified_timestamp": self.drive_modified_timestamp,
            "date_first_processed": self.date_first_processed,
            "date_last_processed": self.date_last_processed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessedDocumentRecord:
        return cls(
            file_id=data["file_id"],
            file_name=data.get("file_name", ""),
            content_hash=data.get("content_hash", ""),
            publication_date=data.get("publication_date"),
            drive_modified_timestamp=data.get("drive_modified_timestamp", ""),
            date_first_processed=data.get("date_first_processed", ""),
            date_last_processed=data.get("date_last_processed", ""),
        )


@dataclass
class RunState:
    """In-memory representation of research_digest_state.json."""

    last_successful_run: str | None = None
    processed_documents: dict[str, ProcessedDocumentRecord] = field(default_factory=dict)
    last_created_notion_page_id: str | None = None

    def content_hashes(self) -> set[str]:
        return {rec.content_hash for rec in self.processed_documents.values() if rec.content_hash}

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_successful_run": self.last_successful_run,
            "processed_documents": {
                file_id: rec.to_dict() for file_id, rec in self.processed_documents.items()
            },
            "last_created_notion_page_id": self.last_created_notion_page_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        processed = {
            file_id: ProcessedDocumentRecord.from_dict(rec)
            for file_id, rec in (data.get("processed_documents") or {}).items()
        }
        return cls(
            last_successful_run=data.get("last_successful_run"),
            processed_documents=processed,
            last_created_notion_page_id=data.get("last_created_notion_page_id"),
        )


@dataclass
class RunReceipt:
    """Parsed representation of receipt.json produced by Codex (or DRY_RUN stub)."""

    page_title: str
    documents_analyzed: list[str]
    window_start: str
    window_end: str
    used_fallback_window: bool
    documents_excluded: list[dict[str, Any]] = field(default_factory=list)
    word_count: int | None = None
    exceptional_length_reason: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunReceipt:
        return cls(
            page_title=data.get("page_title", ""),
            documents_analyzed=list(data.get("documents_analyzed") or []),
            window_start=data.get("window_start", ""),
            window_end=data.get("window_end", ""),
            used_fallback_window=bool(data.get("used_fallback_window", False)),
            documents_excluded=list(data.get("documents_excluded") or []),
            word_count=data.get("word_count"),
            exceptional_length_reason=data.get("exceptional_length_reason"),
            error=data.get("error"),
            raw=data,
        )
