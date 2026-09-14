"""Offline parity validation harness.

Compares analyst batch export against legacy dispatcher source path
to validate that the new pipeline produces equivalent outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.services.dispatch_batch_exporter import (
    DispatchBatchExporter,
)
from research_analysis_layer.models.dispatch_scope import DispatchScope

logger = logging.getLogger(__name__)


@dataclass
class ParityIssue:
    """A single parity violation."""

    category: str
    document_key: str
    field: str
    expected: Any
    actual: Any
    severity: str = "error"


@dataclass
class ParityReport:
    """Result of parity validation."""

    analyst_count: int
    legacy_count: int
    matched_count: int
    issues: list[ParityIssue] = field(default_factory=list)
    metadata_fields_checked: int = 0
    evidence_fields_checked: int = 0

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0 and self.matched_count > 0

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "analyst_count": self.analyst_count,
            "legacy_count": self.legacy_count,
            "matched_count": self.matched_count,
            "issue_count": len(self.issues),
            "metadata_fields_checked": self.metadata_fields_checked,
            "evidence_fields_checked": self.evidence_fields_checked,
            "issues_by_severity": {
                "error": sum(1 for i in self.issues if i.severity == "error"),
                "warning": sum(1 for i in self.issues if i.severity == "warning"),
            },
        }


class ParityValidator:
    """Validates parity between analyst batch export and legacy source."""

    METADATA_FIELDS = [
        "source",
        "source_date",
        "publisher",
        "region",
        "asset_focus",
    ]

    EVIDENCE_FIELDS = [
        "themes",
        "trades",
        "assertions",
        "world_nodes",
        "world_edges",
        "forecast_candidates",
    ]

    def __init__(self, store: AnalysisStore):
        self.store = store
        self.exporter = DispatchBatchExporter(store)

    def validate(
        self,
        scope: DispatchScope,
        legacy_documents: list[dict[str, Any]],
    ) -> ParityReport:
        """Compare analyst batch export against legacy source.

        Args:
            scope: DispatchScope defining what to export from analyst
            legacy_documents: List of legacy parsed_research records

        Returns:
            ParityReport with comparison results
        """
        analyst_batch = self.exporter.load_batch(scope)
        analyst_docs = {d["document_key"]: d for d in analyst_batch["documents"]}
        legacy_docs = {self._document_key(d): d for d in legacy_documents}

        report = ParityReport(
            analyst_count=len(analyst_docs),
            legacy_count=len(legacy_docs),
            matched_count=0,
        )

        document_keys = set(analyst_docs.keys()) | set(legacy_docs.keys())

        for doc_key in document_keys:
            analyst_doc = analyst_docs.get(doc_key)
            legacy_doc = legacy_docs.get(doc_key)

            if analyst_doc is None:
                report.issues.append(
                    ParityIssue(
                        category="missing_in_analyst",
                        document_key=doc_key,
                        field="document",
                        expected="present",
                        actual="missing",
                    )
                )
                continue

            if legacy_doc is None:
                report.issues.append(
                    ParityIssue(
                        category="missing_in_legacy",
                        document_key=doc_key,
                        field="document",
                        expected="present",
                        actual="missing",
                    )
                )
                continue

            report.matched_count += 1

            self._compare_metadata(doc_key, analyst_doc, legacy_doc, report)
            self._compare_evidence(doc_key, analyst_doc, legacy_doc, report)

        return report

    def _document_key(self, legacy_doc: dict[str, Any]) -> str:
        """Extract document_key from legacy document."""
        return legacy_doc.get("document_name", "")

    def _compare_metadata(
        self,
        doc_key: str,
        analyst_doc: dict[str, Any],
        legacy_doc: dict[str, Any],
        report: ParityReport,
    ) -> None:
        """Compare key metadata fields."""
        for field in self.METADATA_FIELDS:
            report.metadata_fields_checked += 1
            analyst_value = analyst_doc.get(field, "")
            legacy_value = legacy_doc.get(field, "") or legacy_doc.get(
                "parsed_data", {}
            ).get("metadata", {}).get(field, "")

            if analyst_value != legacy_value:
                report.issues.append(
                    ParityIssue(
                        category="metadata_mismatch",
                        document_key=doc_key,
                        field=field,
                        expected=str(legacy_value),
                        actual=str(analyst_value),
                    )
                )

    def _compare_evidence(
        self,
        doc_key: str,
        analyst_doc: dict[str, Any],
        legacy_doc: dict[str, Any],
        report: ParityReport,
    ) -> None:
        """Compare evidence pack fields."""
        legacy_parsed = legacy_doc.get("parsed_data", {})

        for field in self.EVIDENCE_FIELDS:
            report.evidence_fields_checked += 1
            analyst_value = analyst_doc.get(field, [])
            legacy_value = legacy_parsed.get(field, [])

            if not isinstance(analyst_value, list):
                analyst_value = []
            if not isinstance(legacy_value, list):
                legacy_value = []

            if len(analyst_value) != len(legacy_value):
                report.issues.append(
                    ParityIssue(
                        category="evidence_count_mismatch",
                        document_key=doc_key,
                        field=field,
                        expected=f"count={len(legacy_value)}",
                        actual=f"count={len(analyst_value)}",
                        severity="warning",
                    )
                )

            if len(analyst_value) == 0 and len(legacy_value) > 0:
                report.issues.append(
                    ParityIssue(
                        category="evidence_missing",
                        document_key=doc_key,
                        field=field,
                        expected="non-empty",
                        actual="empty",
                        severity="warning",
                    )
                )


def run_parity_validation(
    store_path: Path,
    legacy_json_path: Path | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    document_keys: list[str] | None = None,
    batch_key: str = "parity-check",
) -> ParityReport:
    """Run full parity validation.

    Args:
        store_path: Path to analysis SQLite store
        legacy_json_path: Optional path to legacy documents JSON (for testing)
        date_from: Start date for scope
        date_to: End date for scope
        document_keys: Specific document keys to compare
        batch_key: Batch key for scope

    Returns:
        ParityReport with comparison results
    """
    store = AnalysisStore(store_path)

    from datetime import datetime as dt

    scope = DispatchScope(
        date_from=dt.fromisoformat(date_from) if date_from else None,
        date_to=dt.fromisoformat(date_to) if date_to else None,
        document_keys=document_keys,
        batch_key=batch_key,
        include_orphans=True,
    )

    validator = ParityValidator(store)

    legacy_docs = []
    if legacy_json_path and legacy_json_path.exists():
        with open(legacy_json_path) as f:
            legacy_docs = json.load(f).get("documents", [])

    return validator.validate(scope, legacy_docs)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run parity validation")
    parser.add_argument("--store", required=True, help="Path to analysis store")
    parser.add_argument("--legacy", help="Path to legacy documents JSON")
    parser.add_argument("--date-from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--document-keys", help="Comma-separated document keys")
    parser.add_argument("--batch-key", default="parity-check", help="Batch key")

    args = parser.parse_args()

    doc_keys = None
    if args.document_keys:
        doc_keys = [k.strip() for k in args.document_keys.split(",")]

    report = run_parity_validation(
        store_path=Path(args.store),
        legacy_json_path=Path(args.legacy) if args.legacy else None,
        date_from=args.date_from,
        date_to=args.date_to,
        document_keys=doc_keys,
        batch_key=args.batch_key,
    )

    print(json.dumps(report.summary(), indent=2))

    if report.issues:
        print("\nIssues found:")
        for issue in report.issues:
            print(
                f"  [{issue.severity}] {issue.category}: {issue.document_key}.{issue.field}"
            )
            print(f"    expected: {issue.expected}")
            print(f"    actual: {issue.actual}")
