"""Training capture for fine-tuning data."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CAPTURE_THRESHOLD = 0.75


@dataclass
class TrainingCapture:
    """A captured agent output for fine-tuning."""

    capture_id: str
    document_id: str
    capture_timestamp: str
    input: dict[str, Any]
    output: dict[str, Any]
    metadata: dict[str, Any]
    quality: dict[str, Any]


class TrainingCaptureManager:
    """Manages capturing high-quality agent outputs for fine-tuning."""

    def __init__(
        self,
        captures_dir: Path,
        db: "EvalDatabase | None" = None,
        min_confidence: float = CAPTURE_THRESHOLD,
    ):
        """Initialize capture manager.

        Args:
            captures_dir: Directory to store captures
            db: Optional database for persistence
            min_confidence: Minimum confidence threshold for capture
        """
        self.captures_dir = Path(captures_dir)
        self.db = db
        self.min_confidence = min_confidence

        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.captures_dir / "index.jsonl"

    def should_capture(
        self,
        confidence: float,
        schema_valid: bool,
    ) -> bool:
        """Check if output meets capture criteria."""
        return confidence >= self.min_confidence and schema_valid

    def capture(
        self,
        document_id: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        metadata: dict[str, Any],
        quality: dict[str, Any] | None = None,
    ) -> TrainingCapture | None:
        """Capture an output for training.

        Args:
            document_id: ID of the document
            input_data: Input payload to agent
            output_data: Agent output
            metadata: Execution metadata (model, prompt_version, latency, etc.)
            quality: Quality scores (golden_score, judge_score)

        Returns:
            TrainingCapture if criteria met, None otherwise
        """
        confidence = metadata.get("confidence", 0.0)
        schema_valid = metadata.get("schema_valid", True)

        if not self.should_capture(confidence, schema_valid):
            return None

        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
        capture_timestamp = datetime.now(timezone.utc).isoformat()

        capture = TrainingCapture(
            capture_id=capture_id,
            document_id=document_id,
            capture_timestamp=capture_timestamp,
            input=input_data,
            output=output_data,
            metadata={
                **metadata,
                "capture_id": capture_id,
                "capture_timestamp": capture_timestamp,
            },
            quality=quality or {},
        )

        self._save_capture(capture)

        if self.db:
            self.db.insert_training_capture(
                capture_id=capture_id,
                document_id=document_id,
                agent_type=metadata.get("agent_type", "unknown"),
                confidence=confidence,
                quality_score=quality.get("judge_score") if quality else None,
                output_path=str(self._capture_path(capture.capture_id)),
            )

        return capture

    def capture_request(self, request) -> "TrainingCapture | None":
        """Capture a structured CaptureRequest. Returns None if filtered or duplicate."""
        from research_analysis_layer.evals.trigger import CaptureRequest

        if not isinstance(request, CaptureRequest):
            raise TypeError("capture_request requires a CaptureRequest")

        if not self.should_capture(
            confidence=request.confidence,
            schema_valid=bool(request.metadata.get("schema_valid", False)),
        ):
            return None

        if self._is_duplicate(request.dedupe_key):
            return None

        merged_metadata = {
            **request.metadata,
            "agent_type": request.agent_type,
            "analysis_version": request.analysis_version,
            "confidence": request.confidence,
        }
        capture = self.capture(
            document_id=request.document_id,
            input_data=request.input_payload,
            output_data=request.output_payload,
            metadata=merged_metadata,
            quality=request.quality_signals,
        )
        if capture is not None:
            self._record_dedupe_key(request.dedupe_key)
        return capture

    def _dedupe_index_path(self) -> Path:
        return self.captures_dir / "dedupe.txt"

    def _is_duplicate(self, dedupe_key: str) -> bool:
        path = self._dedupe_index_path()
        if not path.exists():
            return False
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == dedupe_key:
                    return True
        return False

    def _record_dedupe_key(self, dedupe_key: str) -> None:
        path = self._dedupe_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(dedupe_key + "\n")

    def _capture_path(self, capture_id: str) -> Path:
        """Get path for capture file."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m")
        return self.captures_dir / date_str / f"{capture_id}.json"

    def _save_capture(self, capture: TrainingCapture) -> None:
        """Save capture to JSON file."""
        capture_path = self._capture_path(capture.capture_id)
        capture_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "capture_id": capture.capture_id,
            "document_id": capture.document_id,
            "capture_timestamp": capture.capture_timestamp,
            "input": capture.input,
            "output": capture.output,
            "metadata": capture.metadata,
            "quality": capture.quality,
        }

        capture_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        self._append_to_index(capture)

    def _append_to_index(self, capture: TrainingCapture) -> None:
        """Append capture to index."""
        index_entry = {
            "capture_id": capture.capture_id,
            "document_id": capture.document_id,
            "agent_type": capture.metadata.get("agent_type", "unknown"),
            "captured_at": capture.capture_timestamp,
            "confidence": capture.metadata.get("confidence", 0.0),
            "file": str(
                self._capture_path(capture.capture_id).relative_to(self.captures_dir)
            ),
        }

        with open(self._index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(index_entry, ensure_ascii=False) + "\n")

    def export(
        self,
        output_path: Path,
        min_confidence: float = 0.75,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Export captures to JSONL for fine-tuning.

        Args:
            output_path: Output file path
            min_confidence: Minimum confidence threshold
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)

        Returns:
            Number of captures exported
        """
        if not self._index_path.exists():
            return 0

        captures = []
        with open(self._index_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                if entry.get("confidence", 0) < min_confidence:
                    continue

                if start_date and entry.get("captured_at", "") < start_date:
                    continue

                if end_date and entry.get("captured_at", "") > end_date:
                    continue

                capture_path = self.captures_dir / entry["file"]
                if capture_path.exists():
                    capture_data = json.loads(capture_path.read_text(encoding="utf-8"))
                    captures.append(capture_data)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for cap in captures:
                f.write(json.dumps(cap, ensure_ascii=False) + "\n")

        return len(captures)

    def get_capture_count(self) -> int:
        """Get total number of captures."""
        if not self._index_path.exists():
            return 0

        count = 0
        with open(self._index_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
