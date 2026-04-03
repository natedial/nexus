from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np


def _add_shared_workspace_paths() -> None:
    module_path = Path(__file__).resolve()
    repo_root = module_path.parents[1]

    candidates: list[Path] = []
    env_root = os.getenv("RESEARCH_PROCESSING_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([repo_root.parent, repo_root])

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not (candidate / "research_pipeline_ops").exists():
            continue
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


_add_shared_workspace_paths()

from distill_tool.pipeline import distill_markdown
from research_pipeline_ops import PipelineOpsClient, make_document_key


@dataclass(frozen=True)
class SupabaseDocument:
    id: int
    source_date: str | None
    source: str | None
    document_name: str | None
    document_hash: str | None
    file_id: str | None
    parsed_data: Any


@dataclass(frozen=True)
class IndexingStats:
    scanned: int
    claimed: int
    indexed: int
    failed: int
    reclaimed: int = 0

    def __add__(self, other: object) -> IndexingStats:
        if not isinstance(other, IndexingStats):
            return NotImplemented
        return IndexingStats(
            scanned=self.scanned + other.scanned,
            claimed=self.claimed + other.claimed,
            indexed=self.indexed + other.indexed,
            failed=self.failed + other.failed,
            reclaimed=self.reclaimed + other.reclaimed,
        )


class TransientSupabaseError(RuntimeError):
    """Raised for network or service failures that a background worker should retry."""


class SupabaseRestClient:
    def __init__(
        self,
        *,
        url: str,
        key: str,
        table: str = "parsed_research",
        schema: str = "public",
        timeout_seconds: float = 30.0,
    ):
        self.url = url.rstrip("/")
        self.key = key
        self.table = table
        self.schema = schema
        self.timeout_seconds = timeout_seconds

    def fetch_pending_documents(self, *, limit: int) -> list[SupabaseDocument]:
        rows = self._request_json(
            "GET",
            f"/rest/v1/{self.table}",
            query={
                "select": "id,source_date,source,document_name,document_hash,parsed_data",
                "index_status": "eq.pending",
                "order": "id.asc",
                "limit": str(limit),
            },
        )

        return self._rows_to_documents(rows)

    def fetch_stale_processing_documents(
        self, *, limit: int, stale_before_batch_id: int
    ) -> list[SupabaseDocument]:
        rows = self._request_json(
            "GET",
            f"/rest/v1/{self.table}",
            query={
                "select": "id,source_date,source,document_name,document_hash,parsed_data",
                "index_status": "eq.processing",
                "indexing_batch_id": f"lt.{stale_before_batch_id}",
                "order": "indexing_batch_id.asc,id.asc",
                "limit": str(limit),
            },
        )
        return self._rows_to_documents(rows)

    def claim_document(self, *, doc_id: int, batch_id: int) -> bool:
        rows = self._request_json(
            "PATCH",
            f"/rest/v1/{self.table}",
            query={
                "id": f"eq.{doc_id}",
                "index_status": "eq.pending",
            },
            payload={
                "index_status": "processing",
                "indexed_at": None,
                "index_error": None,
                "indexing_batch_id": batch_id,
            },
            return_representation=True,
        )
        return bool(rows)

    def reclaim_document(
        self, *, doc_id: int, batch_id: int, stale_before_batch_id: int
    ) -> bool:
        rows = self._request_json(
            "PATCH",
            f"/rest/v1/{self.table}",
            query={
                "id": f"eq.{doc_id}",
                "index_status": "eq.processing",
                "indexing_batch_id": f"lt.{stale_before_batch_id}",
            },
            payload={
                "index_status": "processing",
                "indexed_at": None,
                "index_error": None,
                "indexing_batch_id": batch_id,
            },
            return_representation=True,
        )
        return bool(rows)

    def mark_indexed(
        self,
        *,
        doc_id: int,
        batch_id: int,
        index_version: str,
    ) -> None:
        self._request_json(
            "PATCH",
            f"/rest/v1/{self.table}",
            query={
                "id": f"eq.{doc_id}",
                "indexing_batch_id": f"eq.{batch_id}",
            },
            payload={
                "index_status": "indexed",
                "indexed_at": _utc_now_iso(),
                "index_error": None,
                "index_version": index_version,
            },
        )

    def mark_failed(self, *, doc_id: int, batch_id: int, error: str) -> None:
        message = error.strip() or "Unknown indexing error"
        if len(message) > 2000:
            message = message[:2000]

        self._request_json(
            "PATCH",
            f"/rest/v1/{self.table}",
            query={
                "id": f"eq.{doc_id}",
                "indexing_batch_id": f"eq.{batch_id}",
            },
            payload={
                "index_status": "failed",
                "indexed_at": None,
                "index_error": message,
            },
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        return_representation: bool = False,
    ) -> Any:
        query_string = ""
        if query:
            query_string = "?" + urlencode(query)

        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Profile": self.schema,
            "Content-Profile": self.schema,
        }
        if return_representation:
            headers["Prefer"] = "return=representation"

        req = Request(
            f"{self.url}{path}{query_string}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return []
                return json.loads(raw)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error_message = (
                f"Supabase request failed ({method} {path}{query_string}): "
                f"HTTP {exc.code} {error_body}"
            )
            if exc.code in {408, 425, 429, 500, 502, 503, 504}:
                raise TransientSupabaseError(error_message) from exc
            raise RuntimeError(error_message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TransientSupabaseError(
                f"Supabase request failed ({method} {path}{query_string}): {exc}"
            ) from exc

    @staticmethod
    def _rows_to_documents(rows: Any) -> list[SupabaseDocument]:
        docs: list[SupabaseDocument] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_id = row.get("id")
            if raw_id is None:
                continue
            doc_id = int(raw_id)
            docs.append(
                SupabaseDocument(
                    id=doc_id,
                    source_date=(
                        str(row.get("source_date")).strip()
                        if row.get("source_date") is not None
                        else None
                    ),
                    source=(
                        str(row.get("source")).strip()
                        if row.get("source") is not None
                        else None
                    ),
                    document_name=(
                        str(row.get("document_name")).strip()
                        if row.get("document_name") is not None
                        else None
                    ),
                    document_hash=(
                        str(row.get("document_hash")).strip()
                        if row.get("document_hash") is not None
                        else None
                    ),
                    file_id=_extract_file_id(row.get("parsed_data")),
                    parsed_data=row.get("parsed_data"),
                )
            )
        return docs


class EmbeddingCorpus:
    def __init__(self, chunk_ids: np.ndarray, embeddings: np.ndarray):
        self.chunk_ids = chunk_ids.astype(str)
        self.embeddings = embeddings.astype("float32")

    @classmethod
    def load(cls, npz_path: Path) -> EmbeddingCorpus:
        if not npz_path.exists():
            return cls(np.array([], dtype=str), np.empty((0, 0), dtype="float32"))

        data = np.load(npz_path)
        chunk_ids = data["chunk_ids"].astype(str)
        embeddings = data["embeddings"].astype("float32")
        return cls(chunk_ids=chunk_ids, embeddings=embeddings)

    def upsert(self, chunk_ids: np.ndarray, embeddings: np.ndarray) -> None:
        chunk_ids = chunk_ids.astype(str)
        embeddings = embeddings.astype("float32")

        if chunk_ids.shape[0] != embeddings.shape[0]:
            raise ValueError("chunk_ids and embeddings row count mismatch")

        existing_dim = (
            self.embeddings.shape[1]
            if self.embeddings.ndim == 2 and self.embeddings.size
            else 0
        )
        incoming_dim = (
            embeddings.shape[1] if embeddings.ndim == 2 and embeddings.size else 0
        )

        if existing_dim and incoming_dim and existing_dim != incoming_dim:
            raise ValueError(
                f"embedding dimension mismatch: existing={existing_dim} incoming={incoming_dim}"
            )
        if existing_dim and incoming_dim == 0 and len(chunk_ids) > 0:
            raise ValueError(
                "incoming embeddings are zero-width while corpus has non-zero dimension"
            )

        if self.chunk_ids.size == 0:
            self.chunk_ids = chunk_ids
            self.embeddings = embeddings
            return

        replace_ids = set(chunk_ids.tolist())
        keep_mask = np.array(
            [cid not in replace_ids for cid in self.chunk_ids], dtype=bool
        )

        kept_ids = self.chunk_ids[keep_mask]
        kept_embeddings = self.embeddings[keep_mask]

        if kept_embeddings.size == 0 and embeddings.size == 0:
            merged_embeddings = np.empty(
                (len(kept_ids) + len(chunk_ids), 0), dtype="float32"
            )
        elif kept_embeddings.size == 0:
            merged_embeddings = embeddings
        elif embeddings.size == 0:
            merged_embeddings = kept_embeddings
        else:
            merged_embeddings = np.concatenate([kept_embeddings, embeddings], axis=0)

        self.chunk_ids = np.concatenate([kept_ids, chunk_ids], axis=0)
        self.embeddings = merged_embeddings

    def save(self, npz_path: Path) -> None:
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix="embeddings_", suffix=".npz", delete=False, dir=npz_path.parent
        ) as tmp:
            tmp_path = Path(tmp.name)
        np.savez_compressed(tmp_path, chunk_ids=self.chunk_ids, embeddings=self.embeddings)
        tmp_path.replace(npz_path)


def extract_full_text(row: dict[str, Any]) -> str:
    parsed_data = row.get("parsed_data")
    if not isinstance(parsed_data, dict):
        raise ValueError(f"row {row.get('id')} has invalid parsed_data payload")

    full_text = parsed_data.get("full_text")
    if not isinstance(full_text, str) or not full_text.strip():
        raise ValueError(f"row {row.get('id')} missing parsed_data.full_text")

    return full_text.strip()


def index_pending_documents(
    *,
    supabase_url: str,
    supabase_key: str,
    db_path: str | Path,
    npz_path: str | Path,
    dictionary_path: str | Path | None = None,
    model_name: str = "all-MiniLM-L6-v2",
    max_keywords: int = 20,
    overlap_paragraphs: int = 1,
    page_marker_regex: str | None = None,
    fallback_target_chars: int = 2000,
    fallback_min_chars: int = 700,
    batch_size: int = 32,
    skip_embeddings: bool = False,
    poll_limit: int = 25,
    stale_processing_seconds: float = 3600.0,
    index_version: str = "v1",
    table: str = "parsed_research",
    schema: str = "public",
) -> IndexingStats:
    db_path = Path(db_path)
    npz_path = Path(npz_path)
    ops = PipelineOpsClient.from_env(
        default_spool_db_path=str(db_path.parent / "pipeline_ops_spool.db"),
        emitted_by="research_store",
    )
    ops.flush()
    ops_run_key = ops.start_run(
        repo_name="research_store",
        stage_family="store",
        run_type="index_cycle",
        trigger_source="supabase_indexer",
        batch_key=str(int(datetime.now(tz=timezone.utc).timestamp() * 1000)),
        stats={
            "poll_limit": poll_limit,
            "index_version": index_version,
            "skip_embeddings": skip_embeddings,
        },
    )

    client = SupabaseRestClient(
        url=supabase_url,
        key=supabase_key,
        table=table,
        schema=schema,
    )

    stale_docs: list[SupabaseDocument] = []
    if stale_processing_seconds > 0 and poll_limit > 0:
        stale_before_batch_id = (
            int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            - int(stale_processing_seconds * 1000)
        )
        stale_docs = client.fetch_stale_processing_documents(
            limit=poll_limit,
            stale_before_batch_id=stale_before_batch_id,
        )
    else:
        stale_before_batch_id = 0

    remaining_slots = max(0, poll_limit - len(stale_docs))
    pending_docs = (
        client.fetch_pending_documents(limit=remaining_slots) if remaining_slots > 0 else []
    )
    scanned = len(stale_docs) + len(pending_docs)
    claimed = 0
    indexed = 0
    failed = 0
    reclaimed = 0

    batch_id = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    corpus = EmbeddingCorpus.load(npz_path)

    claim_targets = [(doc, True) for doc in stale_docs] + [(doc, False) for doc in pending_docs]

    try:
        for doc, is_reclaim in claim_targets:
            document_key = make_document_key(
                file_id=doc.file_id,
                research_id=doc.id,
                document_hash=doc.document_hash,
            )
            document_fields = {
                "document_name": doc.document_name,
                "source": doc.source,
                "source_date": doc.source_date,
            }
            if is_reclaim:
                claimed_doc = client.reclaim_document(
                    doc_id=doc.id,
                    batch_id=batch_id,
                    stale_before_batch_id=stale_before_batch_id,
                )
            else:
                claimed_doc = client.claim_document(doc_id=doc.id, batch_id=batch_id)
            if not claimed_doc:
                continue

            claimed += 1
            if is_reclaim:
                reclaimed += 1
            ops.emit_stage_event(
                repo_name="research_store",
                stage_name="store.claim_index_job",
                status="succeeded",
                run_key=ops_run_key,
                document_key=document_key,
                file_id=doc.file_id,
                research_id=doc.id,
                document_hash=doc.document_hash,
                payload={"reclaimed": is_reclaim, "index_version": index_version},
                document_fields=document_fields,
            )
            try:
                full_text = extract_full_text(
                    {"id": doc.id, "parsed_data": doc.parsed_data}
                )
                with ops.track_stage(
                    repo_name="research_store",
                    stage_name="store.distill_document",
                    run_key=ops_run_key,
                    document_key=document_key,
                    file_id=doc.file_id,
                    research_id=doc.id,
                    document_hash=doc.document_hash,
                    payload={"skip_embeddings": skip_embeddings},
                    document_fields=document_fields,
                ):
                    distill_markdown(
                        markdown=full_text,
                        source_path=f"supabase:{doc.id}",
                        source_date=doc.source_date,
                        db_path=db_path,
                        npz_path=npz_path,
                        dictionary_path=dictionary_path,
                        model_name=model_name,
                        max_keywords=max_keywords,
                        overlap_paragraphs=overlap_paragraphs,
                        page_marker_regex=page_marker_regex,
                        fallback_target_chars=fallback_target_chars,
                        fallback_min_chars=fallback_min_chars,
                        batch_size=batch_size,
                        skip_embeddings=skip_embeddings,
                        embedding_model=None,
                    )

                with ops.track_stage(
                    repo_name="research_store",
                    stage_name="store.persist_corpus",
                    run_key=ops_run_key,
                    document_key=document_key,
                    file_id=doc.file_id,
                    research_id=doc.id,
                    document_hash=doc.document_hash,
                    payload={"skip_embeddings": skip_embeddings},
                    document_fields=document_fields,
                ):
                    fresh = EmbeddingCorpus.load(npz_path)
                    corpus.upsert(fresh.chunk_ids, fresh.embeddings)
                    corpus.save(npz_path)

                client.mark_indexed(
                    doc_id=doc.id,
                    batch_id=batch_id,
                    index_version=index_version,
                )
                ops.emit_stage_event(
                    repo_name="research_store",
                    stage_name="store.mark_indexed",
                    status="succeeded",
                    run_key=ops_run_key,
                    document_key=document_key,
                    file_id=doc.file_id,
                    research_id=doc.id,
                    document_hash=doc.document_hash,
                    payload={"index_version": index_version},
                    document_fields=document_fields,
                )
                ops.emit_stage_event(
                    repo_name="research_store",
                    stage_name="store.complete",
                    status="succeeded",
                    run_key=ops_run_key,
                    document_key=document_key,
                    file_id=doc.file_id,
                    research_id=doc.id,
                    document_hash=doc.document_hash,
                    payload={"index_version": index_version, "reclaimed": is_reclaim},
                    document_fields=document_fields,
                )
                indexed += 1
            except Exception as exc:
                client.mark_failed(doc_id=doc.id, batch_id=batch_id, error=str(exc))
                ops.emit_stage_event(
                    repo_name="research_store",
                    stage_name="store.complete",
                    status="failed",
                    run_key=ops_run_key,
                    document_key=document_key,
                    file_id=doc.file_id,
                    research_id=doc.id,
                    document_hash=doc.document_hash,
                    error_type=exc.__class__.__name__,
                    error_text=str(exc),
                    payload={"index_version": index_version, "reclaimed": is_reclaim},
                    document_fields=document_fields,
                )
                failed += 1

        stats = IndexingStats(
            scanned=scanned,
            claimed=claimed,
            indexed=indexed,
            failed=failed,
            reclaimed=reclaimed,
        )
        ops.update_run(
            ops_run_key,
            status="completed",
            stats={
                "scanned": stats.scanned,
                "claimed": stats.claimed,
                "indexed": stats.indexed,
                "failed": stats.failed,
                "reclaimed": stats.reclaimed,
            },
            completed=True,
        )
        ops.flush()
        return stats
    except Exception as exc:
        ops.update_run(
            ops_run_key,
            status="failed",
            error_text=str(exc),
            stats={
                "scanned": scanned,
                "claimed": claimed,
                "indexed": indexed,
                "failed": failed,
                "reclaimed": reclaimed,
            },
            completed=True,
        )
        ops.flush()
        raise


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_file_id(parsed_data: Any) -> str | None:
    if not isinstance(parsed_data, dict):
        return None
    metadata = parsed_data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw_file_id = metadata.get("document_id")
    if raw_file_id is None:
        return None
    text = str(raw_file_id).strip()
    return text or None
