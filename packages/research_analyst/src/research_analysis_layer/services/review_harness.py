"""Local review/report helpers."""

from __future__ import annotations

from research_analysis_layer.db.analysis_store import AnalysisStore


class ReviewHarness:
    """Build persisted review payloads for one analyzed document."""

    def __init__(self, store: AnalysisStore):
        self.store = store

    def review_document(
        self,
        *,
        research_id: int,
        document_hash: str | None = None,
    ) -> dict[str, object] | None:
        payload = self.store.build_document_review(
            research_id=research_id,
            document_hash=document_hash,
        )
        if payload is None:
            return None
        review_key = f"{research_id}:{payload['document']['document_hash']}"
        review_id = self.store.save_review_snapshot(
            review_scope="document",
            review_key=review_key,
            payload=payload,
        )
        payload["review_id"] = review_id
        payload["review_key"] = review_key
        return payload
