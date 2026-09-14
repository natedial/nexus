"""Models for dispatch batch export scope."""

from datetime import datetime
from pydantic import BaseModel, Field


class DispatchScopeError(ValueError):
    """Raised when a DispatchScope is invalid."""

    pass


class DispatchScope(BaseModel):
    """Scope definition for exporting a dispatch batch.

    Rules:
    - Exactly one of (date_from, date_to) OR document_keys must be provided
    - batch_key is always required for idempotency
    """

    date_from: datetime | None = Field(
        None, description="inclusive lower bound on DocumentAnalysis.created_at"
    )
    date_to: datetime | None = Field(
        None, description="exclusive upper bound on DocumentAnalysis.created_at"
    )
    document_keys: list[str] | None = Field(
        None, description="explicit replay list; when set, date bounds are ignored"
    )
    analysis_version: str | None = Field(
        None,
        description="pin a specific analyst version; default = latest per document",
    )
    include_orphans: bool = Field(
        True, description="include rows with research_id IS NULL"
    )
    batch_key: str = Field(
        ...,
        description="caller-supplied identifier; stamped into DispatchBatch.batch_key",
    )

    def validate_scope(self) -> None:
        """Validate the scope meets the contract rules.

        Raises:
            DispatchScopeError: If scope is invalid
        """
        has_date_bounds = self.date_from is not None or self.date_to is not None
        has_document_keys = (
            self.document_keys is not None and len(self.document_keys) > 0
        )

        if has_date_bounds and has_document_keys:
            raise DispatchScopeError(
                "Cannot specify both date bounds and document_keys; choose exactly one"
            )

        if not has_date_bounds and not has_document_keys:
            raise DispatchScopeError(
                "Must specify either (date_from, date_to) or document_keys"
            )

        if not self.batch_key:
            raise DispatchScopeError("batch_key is required for idempotency")
