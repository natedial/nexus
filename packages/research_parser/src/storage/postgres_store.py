"""PostgreSQL implementation of SourceStore."""

from __future__ import annotations

from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from src.research_memory import ResearchArtifactContext, build_memory_records
from src.source import SourceDocument
from src.storage.source_store import SourceStore, build_parsed_research_record

logger = structlog.get_logger()

_PARSED_RESEARCH_UPSERT = """
INSERT INTO parsed_research (
    document_id,
    parsed_data,
    source_date,
    source,
    document_name,
    document_title,
    document_link,
    document_hash
) VALUES (
    %(document_id)s,
    %(parsed_data)s,
    %(source_date)s,
    %(source)s,
    %(document_name)s,
    %(document_title)s,
    %(document_link)s,
    %(document_hash)s
)
ON CONFLICT (document_id) DO UPDATE SET
    parsed_data = EXCLUDED.parsed_data,
    source_date = EXCLUDED.source_date,
    source = EXCLUDED.source,
    document_name = EXCLUDED.document_name,
    document_title = EXCLUDED.document_title,
    document_link = EXCLUDED.document_link,
    document_hash = EXCLUDED.document_hash
RETURNING *
"""


class PostgresSourceStore(SourceStore):
    """Persist parsed source documents to local PostgreSQL."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        logger.info("Initialized PostgreSQL source store")

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
        logger.info(
            "Inserting research",
            document_name=document_name,
            source=source.source,
            source_date=record["source_date"],
        )

        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                row = self._upsert_parsed_research(conn, record)
                research_id = row.get("id")
                if not research_id:
                    raise RuntimeError(f"Persisted research row is missing id for {document_name}")

                self._replace_memory_records(
                    conn,
                    research_id=int(research_id),
                    document_hash=record["document_hash"],
                    clean_text=source.full_text,
                    artifact_context=artifact_context,
                )
                return dict(row)

    def _upsert_parsed_research(self, conn: psycopg.Connection, record: dict) -> dict:
        params = {
            **record,
            "parsed_data": Json(record["parsed_data"]),
        }
        row = conn.execute(_PARSED_RESEARCH_UPSERT, params).fetchone()
        if not row:
            raise RuntimeError(f"Failed to persist research for {record['document_name']}")
        return dict(row)

    def _replace_memory_records(
        self,
        conn: psycopg.Connection,
        *,
        research_id: int,
        document_hash: str,
        clean_text: str,
        artifact_context: ResearchArtifactContext | None,
    ) -> None:
        records = build_memory_records(
            research_id=research_id,
            document_hash=document_hash,
            clean_text=clean_text,
            context=artifact_context,
        )
        artifact = records["artifact"]
        parser_version = artifact["parser_version"]
        span_version = artifact["artifact_manifest"]["span_version"]
        chunker_version = artifact["artifact_manifest"]["chunker_version"]

        conn.execute(
            """
            DELETE FROM research_document_artifacts
            WHERE research_id = %s AND parser_version = %s
            """,
            (research_id, parser_version),
        )
        conn.execute(
            """
            DELETE FROM research_retrieval_chunks
            WHERE research_id = %s AND chunker_version = %s
            """,
            (research_id, chunker_version),
        )
        conn.execute(
            """
            DELETE FROM research_spans
            WHERE research_id = %s AND span_version = %s
            """,
            (research_id, span_version),
        )

        conn.execute(
            """
            INSERT INTO research_document_artifacts (
                research_id,
                document_hash,
                parser_version,
                parse_backend,
                parse_confidence_score,
                parse_confidence_status,
                raw_markdown_path,
                clean_text_path,
                figure_manifest,
                artifact_manifest,
                clean_text_hash
            ) VALUES (
                %(research_id)s,
                %(document_hash)s,
                %(parser_version)s,
                %(parse_backend)s,
                %(parse_confidence_score)s,
                %(parse_confidence_status)s,
                %(raw_markdown_path)s,
                %(clean_text_path)s,
                %(figure_manifest)s,
                %(artifact_manifest)s,
                %(clean_text_hash)s
            )
            ON CONFLICT (research_id, parser_version) DO UPDATE SET
                document_hash = EXCLUDED.document_hash,
                parse_backend = EXCLUDED.parse_backend,
                parse_confidence_score = EXCLUDED.parse_confidence_score,
                parse_confidence_status = EXCLUDED.parse_confidence_status,
                raw_markdown_path = EXCLUDED.raw_markdown_path,
                clean_text_path = EXCLUDED.clean_text_path,
                figure_manifest = EXCLUDED.figure_manifest,
                artifact_manifest = EXCLUDED.artifact_manifest,
                clean_text_hash = EXCLUDED.clean_text_hash
            """,
            {
                **artifact,
                "figure_manifest": Json(artifact["figure_manifest"]),
                "artifact_manifest": Json(artifact["artifact_manifest"]),
            },
        )

        for span in records["spans"]:
            conn.execute(
                """
                INSERT INTO research_spans (
                    span_key,
                    research_id,
                    document_hash,
                    span_version,
                    span_type,
                    span_order,
                    page_start,
                    page_end,
                    section_path,
                    paragraph_start,
                    paragraph_end,
                    char_start,
                    char_end,
                    text,
                    text_hash,
                    coordinates,
                    metadata
                ) VALUES (
                    %(span_key)s,
                    %(research_id)s,
                    %(document_hash)s,
                    %(span_version)s,
                    %(span_type)s,
                    %(span_order)s,
                    %(page_start)s,
                    %(page_end)s,
                    %(section_path)s,
                    %(paragraph_start)s,
                    %(paragraph_end)s,
                    %(char_start)s,
                    %(char_end)s,
                    %(text)s,
                    %(text_hash)s,
                    %(coordinates)s,
                    %(metadata)s
                )
                ON CONFLICT (span_key) DO UPDATE SET
                    research_id = EXCLUDED.research_id,
                    document_hash = EXCLUDED.document_hash,
                    span_version = EXCLUDED.span_version,
                    span_type = EXCLUDED.span_type,
                    span_order = EXCLUDED.span_order,
                    page_start = EXCLUDED.page_start,
                    page_end = EXCLUDED.page_end,
                    section_path = EXCLUDED.section_path,
                    paragraph_start = EXCLUDED.paragraph_start,
                    paragraph_end = EXCLUDED.paragraph_end,
                    char_start = EXCLUDED.char_start,
                    char_end = EXCLUDED.char_end,
                    text = EXCLUDED.text,
                    text_hash = EXCLUDED.text_hash,
                    coordinates = EXCLUDED.coordinates,
                    metadata = EXCLUDED.metadata
                """,
                {
                    **span,
                    "coordinates": Json(span["coordinates"]) if span.get("coordinates") is not None else None,
                    "metadata": Json(span.get("metadata") or {}),
                },
            )

        for chunk in records["chunks"]:
            conn.execute(
                """
                INSERT INTO research_retrieval_chunks (
                    chunk_key,
                    research_id,
                    document_hash,
                    chunker_version,
                    chunk_order,
                    chunk_type,
                    title,
                    text,
                    text_hash,
                    span_keys,
                    page_start,
                    page_end,
                    token_count,
                    embedding_model,
                    embedding_version,
                    embedding_id,
                    lexical_terms,
                    metadata
                ) VALUES (
                    %(chunk_key)s,
                    %(research_id)s,
                    %(document_hash)s,
                    %(chunker_version)s,
                    %(chunk_order)s,
                    %(chunk_type)s,
                    %(title)s,
                    %(text)s,
                    %(text_hash)s,
                    %(span_keys)s,
                    %(page_start)s,
                    %(page_end)s,
                    %(token_count)s,
                    %(embedding_model)s,
                    %(embedding_version)s,
                    %(embedding_id)s,
                    %(lexical_terms)s,
                    %(metadata)s
                )
                ON CONFLICT (chunk_key) DO UPDATE SET
                    research_id = EXCLUDED.research_id,
                    document_hash = EXCLUDED.document_hash,
                    chunker_version = EXCLUDED.chunker_version,
                    chunk_order = EXCLUDED.chunk_order,
                    chunk_type = EXCLUDED.chunk_type,
                    title = EXCLUDED.title,
                    text = EXCLUDED.text,
                    text_hash = EXCLUDED.text_hash,
                    span_keys = EXCLUDED.span_keys,
                    page_start = EXCLUDED.page_start,
                    page_end = EXCLUDED.page_end,
                    token_count = EXCLUDED.token_count,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_version = EXCLUDED.embedding_version,
                    embedding_id = EXCLUDED.embedding_id,
                    lexical_terms = EXCLUDED.lexical_terms,
                    metadata = EXCLUDED.metadata
                """,
                {
                    **chunk,
                    "lexical_terms": Json(chunk.get("lexical_terms") or []),
                    "metadata": Json(chunk.get("metadata") or {}),
                },
            )

        logger.info(
            "Research memory substrate persisted",
            research_id=research_id,
            span_count=len(records["spans"]),
            chunk_count=len(records["chunks"]),
            backend=(artifact_context.parse_backend if artifact_context else None),
        )
