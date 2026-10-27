from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

CAPTURE_SCHEMA_VERSION = 2


class CaptureIntent(StrEnum):
    HOLD = "hold"
    RESEARCH = "research"
    RELAY = "relay"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class SourceDocumentRef:
    source_kind: str
    document_id: str
    uri: str
    title: str
    modified_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceLocator:
    block_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    annotation_id: str | None = None
    coordinates: tuple[float, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "page_number": self.page_number,
            "annotation_id": self.annotation_id,
            "coordinates": list(self.coordinates) if self.coordinates else None,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class CapturedExcerpt:
    capture_id: str
    document: SourceDocumentRef
    locator: SourceLocator
    text: str
    context_text: str
    heading_path: tuple[str, ...]
    source_style: str
    intent: CaptureIntent
    captured_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CAPTURE_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        document: SourceDocumentRef,
        locator: SourceLocator,
        text: str,
        context_text: str,
        heading_path: tuple[str, ...] = (),
        source_style: str,
        intent: CaptureIntent = CaptureIntent.HOLD,
        captured_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapturedExcerpt:
        normalized = normalize_text(text)
        if not normalized:
            raise ValueError("captured excerpt text must not be empty")
        return cls(
            capture_id=make_capture_id(
                document=document,
                locator=locator,
                source_style=source_style,
                text=normalized,
            ),
            document=document,
            locator=locator,
            text=normalized,
            context_text=normalize_text(context_text),
            heading_path=tuple(heading_path),
            source_style=source_style.strip().lower(),
            intent=intent,
            captured_at=captured_at or datetime.now(UTC),
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capture_id": self.capture_id,
            "document": {
                "source_kind": self.document.source_kind,
                "document_id": self.document.document_id,
                "uri": self.document.uri,
                "title": self.document.title,
                "modified_at": _iso(self.document.modified_at),
                "metadata": self.document.metadata,
            },
            "locator": self.locator.identity_dict(),
            "text": self.text,
            "context_text": self.context_text,
            "heading_path": list(self.heading_path),
            "source_style": self.source_style,
            "intent": self.intent.value,
            "captured_at": _iso(self.captured_at),
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class CaptureBatch:
    run_id: str
    source_kind: str
    started_at: datetime
    completed_at: datetime
    captures: tuple[CapturedExcerpt, ...]
    new_capture_ids: tuple[str, ...]
    schema_version: int = CAPTURE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_kind": self.source_kind,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "capture_count": len(self.captures),
            "new_capture_count": len(self.new_capture_ids),
            "new_capture_ids": list(self.new_capture_ids),
            "captures": [capture.to_dict() for capture in self.captures],
        }


def normalize_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    return unicodedata.normalize("NFKC", collapsed)


def make_capture_id(
    *,
    document: SourceDocumentRef,
    locator: SourceLocator,
    source_style: str,
    text: str,
) -> str:
    payload = {
        "version": CAPTURE_SCHEMA_VERSION,
        "source_kind": document.source_kind.strip().lower(),
        "document_id": document.document_id.strip(),
        "locator": locator.identity_dict(),
        "source_style": source_style.strip().lower(),
        "text": normalize_text(text),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "cap_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
