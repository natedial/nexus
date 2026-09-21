"""In-memory SourceStore for unit tests."""

from __future__ import annotations

from typing import Any

from src.research_memory import ResearchArtifactContext, build_memory_records
from src.research_memory.persist import replace_memory_records
from src.source import SourceDocument
from src.storage.source_store import SourceStore, build_parsed_research_record


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client: _FakePostgrestClient, name: str):
        self._client = client
        self._name = name
        self._action = "select"
        self._filters: list[tuple[str, str, object]] = []
        self._payload = None
        self._limit: int | None = None
        self._on_conflict: list[str] = []

    def select(self, _columns: str):
        self._action = "select"
        return self

    def eq(self, column: str, value):
        self._filters.append(("eq", column, value))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def update(self, payload: dict):
        self._action = "update"
        self._payload = payload
        return self

    def insert(self, payload: dict):
        self._action = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: dict, on_conflict: str):
        self._action = "upsert"
        self._payload = payload
        self._on_conflict = [item.strip() for item in on_conflict.split(",") if item]
        return self

    def delete(self):
        self._action = "delete"
        return self

    def execute(self):
        rows = self._client.tables.setdefault(self._name, [])
        filtered = [row for row in rows if self._matches(row)]
        if self._limit is not None:
            filtered = filtered[: self._limit]

        if self._action == "select":
            return _FakeResponse([dict(row) for row in filtered])

        if self._action == "update":
            updated = []
            for row in filtered:
                row.update(self._payload)
                updated.append(dict(row))
            return _FakeResponse(updated)

        if self._action == "insert":
            row = dict(self._payload)
            if "id" not in row:
                row["id"] = self._client.next_ids.setdefault(self._name, 1)
                self._client.next_ids[self._name] += 1
            rows.append(row)
            return _FakeResponse([dict(row)])

        if self._action == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            stored = []
            for payload in payloads:
                updated = False
                for row in rows:
                    if all(row.get(column) == payload.get(column) for column in self._on_conflict):
                        row.update(payload)
                        stored.append(dict(row))
                        updated = True
                        break
                if not updated:
                    row = dict(payload)
                    if "id" not in row:
                        row["id"] = self._client.next_ids.setdefault(self._name, 1)
                        self._client.next_ids[self._name] += 1
                    rows.append(row)
                    stored.append(dict(row))
            return _FakeResponse(stored)

        if self._action == "delete":
            kept = [row for row in rows if not self._matches(row)]
            self._client.tables[self._name] = kept
            return _FakeResponse([])

        raise AssertionError(f"Unsupported action: {self._action}")

    def _matches(self, row: dict) -> bool:
        for op, column, value in self._filters:
            if op == "eq" and row.get(column) != value:
                return False
        return True


class _FakePostgrestClient:
    """Minimal table client used by legacy persist.replace_memory_records."""

    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {
            "parsed_research": [],
            "research_themes": [],
            "research_theme_excerpts": [],
            "research_document_artifacts": [],
            "research_spans": [],
            "research_retrieval_chunks": [],
        }
        self.next_ids = {
            "parsed_research": 1,
            "research_themes": 1,
            "research_theme_excerpts": 1,
        }

    def table(self, name: str):
        return _FakeTable(self, name)


class FakeSourceStore(SourceStore):
    """SourceStore backed by in-memory tables."""

    def __init__(self, client: _FakePostgrestClient | None = None):
        self._client = client or _FakePostgrestClient()

    @property
    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return self._client.tables

    def insert_research(
        self,
        source: SourceDocument,
        document_name: str,
        *,
        artifact_context: ResearchArtifactContext | None = None,
    ) -> dict:
        record = build_parsed_research_record(
            source,
            document_name,
            artifact_context=artifact_context,
        )
        upserted = (
            self._client.table("parsed_research")
            .upsert(record, on_conflict="document_id")
            .execute()
        )
        if upserted.data:
            research_row = upserted.data[0]
        else:
            fetched = (
                self._client.table("parsed_research")
                .select("*")
                .eq("document_id", record["document_id"])
                .limit(1)
                .execute()
            )
            if not fetched.data:
                raise RuntimeError(f"Failed to persist research for {document_name}")
            research_row = fetched.data[0]

        research_id = research_row.get("id")
        if not research_id:
            raise RuntimeError(f"Persisted research row is missing id for {document_name}")

        records = build_memory_records(
            research_id=int(research_id),
            document_hash=record["document_hash"],
            clean_text=source.full_text,
            context=artifact_context,
        )
        replace_memory_records(self._client, records)
        return research_row
