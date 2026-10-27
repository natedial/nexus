from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RemarkableDocument:
    document_id: str
    revision: str
    title: str
    path: str
    modified_at: datetime | None
    raw: Any


class RemarkableLibrary:
    def __init__(self) -> None:
        try:
            from remarkable_mcp.api import get_rmapi
        except ImportError as exc:
            raise RuntimeError(
                "remarkable-mcp is required; install the research-gleaner package dependencies"
            ) from exc
        self.client = get_rmapi()

    def list_documents(self) -> list[RemarkableDocument]:
        from remarkable_mcp.api import get_item_path, get_items_by_id

        collection = self.client.get_meta_items()
        items_by_id = get_items_by_id(collection)
        documents = []
        for item in collection:
            if item.is_folder or getattr(item, "deleted", False):
                continue
            modified_at = _aware(getattr(item, "ModifiedClient", None))
            documents.append(
                RemarkableDocument(
                    document_id=str(item.ID),
                    revision=str(getattr(item, "hash", "") or modified_at or item.ID),
                    title=str(item.VissibleName),
                    path=get_item_path(item, items_by_id),
                    modified_at=modified_at,
                    raw=item,
                )
            )
        return sorted(
            documents,
            key=lambda document: document.modified_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def file_type(self, document: RemarkableDocument) -> str:
        from remarkable_mcp.api import get_file_type

        return str(get_file_type(self.client, document.raw)).lower()

    def download(self, document: RemarkableDocument) -> bytes:
        return bytes(self.client.download(document.raw))


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
