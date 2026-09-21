"""Discover relay intake handoff bundles written by research-relay."""

from __future__ import annotations

from pathlib import Path

from src.intake.relay_contract import RelayIntakeArtifact, load_manifest


class RelayIntakeAdapter:
    """List completed relay handoff bundles from a shared intake directory."""

    def __init__(self, handoff_dir: Path):
        self.handoff_dir = handoff_dir

    def list_pending(self) -> list[RelayIntakeArtifact]:
        if not self.handoff_dir.is_dir():
            return []
        artifacts: list[RelayIntakeArtifact] = []
        for manifest_path in sorted(self.handoff_dir.glob("*/manifest.json")):
            try:
                artifact = load_manifest(manifest_path)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if not artifact.is_processable():
                continue
            artifacts.append(artifact)
        return artifacts
