"""Selection logic for hydrated parser outputs."""

from __future__ import annotations

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import HydratedParsedDocument, ParserStateRecord, SelectionDecision


class Selector:
    """Decide whether a hydrated document should be processed now."""

    def decide(
        self,
        state_record: ParserStateRecord,
        document: HydratedParsedDocument | None,
        store: AnalysisStore,
        analysis_version: str,
    ) -> SelectionDecision:
        if document is None:
            return SelectionDecision(
                file_id=state_record.file_id,
                file_name=state_record.file_name,
                selected=False,
                status="skipped_not_ready",
                reason="parsed_document_missing",
            )

        if not document.ready_for_analysis:
            return SelectionDecision(
                file_id=state_record.file_id,
                file_name=state_record.file_name,
                selected=False,
                status="skipped_not_ready",
                reason="document_not_ready",
                research_id=document.research_id,
                document_hash=document.document_hash,
            )

        already_processed, previous_hash = store.get_document_version_status(
            document.research_id,
            document.document_hash or "",
            analysis_version,
        )
        if already_processed:
            return SelectionDecision(
                file_id=state_record.file_id,
                file_name=state_record.file_name,
                selected=False,
                status="skipped_duplicate",
                reason="same_hash_same_version_already_processed",
                research_id=document.research_id,
                document_hash=document.document_hash,
            )

        reason = "new_document"
        if previous_hash and previous_hash != document.document_hash:
            reason = "document_hash_changed"
        elif previous_hash == document.document_hash:
            reason = "analysis_version_changed"

        return SelectionDecision(
            file_id=state_record.file_id,
            file_name=state_record.file_name,
            selected=True,
            status="queued",
            reason=reason,
            research_id=document.research_id,
            document_hash=document.document_hash,
        )
