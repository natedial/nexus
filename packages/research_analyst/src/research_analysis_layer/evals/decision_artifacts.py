"""Sidecar artifact IO for shadow decision classification."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from research_analysis_layer.models.decision_models import ShadowClassificationArtifact


def write_shadow_artifact(
    artifact: ShadowClassificationArtifact,
    output_dir: Path,
    *,
    prefix: str = "decision_shadow",
) -> Path:
    """Write a versioned JSON sidecar under eval output conventions."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    doc_part = artifact.document_key or artifact.document_hash or "fixture"
    safe_doc = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in doc_part)[:80]
    path = output_dir / f"{prefix}_{safe_doc}_{stamp}.json"
    path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def write_shadow_artifact_jsonl(
    artifact: ShadowClassificationArtifact,
    output_path: Path,
) -> Path:
    """Write one JSON object per unit for streaming inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for unit in artifact.units:
            handle.write(json.dumps(unit.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return output_path


def load_shadow_artifact(path: Path) -> ShadowClassificationArtifact:
    """Load a previously written shadow artifact."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ShadowClassificationArtifact.model_validate(payload)
