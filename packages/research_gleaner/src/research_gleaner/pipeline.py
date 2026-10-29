from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_gleaner.export import write_capture_batch
from research_gleaner.models import CaptureBatch, CaptureIntent
from research_gleaner.notion.extractor import ColorRule, NotionExtractor
from research_gleaner.notion.query import NotionQuery, query_pages
from research_gleaner.remarkable.client import RemarkableLibrary
from research_gleaner.remarkable.extractor import (
    REMARKABLE_EXTRACTOR_VERSION,
    extract_document,
)
from research_gleaner.store import CaptureStore


def run_notion_capture(
    client: Any,
    store: CaptureStore,
    query: NotionQuery,
    output_path: Path,
    *,
    color_rules: dict[str, ColorRule] | None = None,
) -> CaptureBatch:
    started_at = datetime.now(UTC)
    pages = query_pages(client, query)
    extractor = NotionExtractor(
        client,
        color_rules=color_rules,
        title_property=query.title_property,
        topics_property=query.topics_property,
        resource_type_property=query.resource_type_property,
    )
    captures = tuple(capture for page in pages for capture in extractor.extract_page(page))
    new_ids = tuple(store.register_many(captures))
    batch = CaptureBatch(
        run_id=uuid.uuid4().hex,
        source_kind="notion",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        captures=captures,
        new_capture_ids=new_ids,
    )
    write_capture_batch(batch, output_path)
    return batch


def run_remarkable_capture(
    library: RemarkableLibrary,
    store: CaptureStore,
    output_path: Path,
    *,
    modified_since: datetime,
    routes: dict[str, CaptureIntent] | None = None,
) -> CaptureBatch:
    started_at = datetime.now(UTC)
    captures = []
    new_ids = []
    for document in library.list_documents():
        uri = _remarkable_uri(document.path)
        processed_revision = _remarkable_processed_revision(document.revision)
        store.record_document(
            source_kind="remarkable",
            document_id=document.document_id,
            uri=uri,
            title=document.title,
            path=document.path,
            remote_modified_at=_iso(document.modified_at),
            metadata={"revision": document.revision},
        )
        if document.modified_at is None or document.modified_at < modified_since:
            continue
        if store.processed_revision("remarkable", document.document_id) == processed_revision:
            continue
        file_type = library.file_type(document)
        if file_type != "pdf":
            store.record_document(
                source_kind="remarkable",
                document_id=document.document_id,
                uri=uri,
                title=document.title,
                path=document.path,
                file_type=file_type,
                remote_modified_at=_iso(document.modified_at),
                processed_revision=processed_revision,
                metadata={"revision": document.revision},
                processed=True,
            )
            continue

        document_captures = extract_document(
            document,
            library.download(document),
            routes=routes,
        )
        new_ids.extend(store.register_many(document_captures))
        store.reconcile_document(
            "remarkable",
            document.document_id,
            (capture.capture_id for capture in document_captures),
        )
        store.record_document(
            source_kind="remarkable",
            document_id=document.document_id,
            uri=uri,
            title=document.title,
            path=document.path,
            file_type=file_type,
            remote_modified_at=_iso(document.modified_at),
            processed_revision=processed_revision,
            metadata={"revision": document.revision},
            processed=True,
        )
        captures.extend(document_captures)

    batch = CaptureBatch(
        run_id=uuid.uuid4().hex,
        source_kind="remarkable",
        started_at=started_at,
        completed_at=datetime.now(UTC),
        captures=tuple(captures),
        new_capture_ids=tuple(new_ids),
    )
    write_capture_batch(batch, output_path)
    return batch


def _remarkable_uri(path: str) -> str:
    from urllib.parse import quote

    return f"remarkable:///{quote(path.lstrip('/'))}"


def _remarkable_processed_revision(revision: str) -> str:
    return f"{revision}:extractor-v{REMARKABLE_EXTRACTOR_VERSION}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
