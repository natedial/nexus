"""Dry-run CLI for graphic selection fixtures.

Usage (from packages/research_dispatcher):

  python -m src.graphic_selection.cli \\
    --fixtures fixtures/graphic_selection/concept_blocks.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.graphic_selection.chooser import GraphicChooser
from src.graphic_selection.factory import (
    DecisionModelConfigError,
    build_decision_model,
)
from src.graphic_selection.models import ConceptBlock


def load_concept_blocks(path: Path) -> list[ConceptBlock]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix == ".jsonl":
        blocks: list[ConceptBlock] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                blocks.append(ConceptBlock.model_validate(json.loads(line)))
            except Exception as exc:  # noqa: BLE001 — surface fixture line errors
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
        return blocks
    data = json.loads(text)
    if isinstance(data, list):
        return [ConceptBlock.model_validate(item) for item in data]
    if isinstance(data, dict) and "blocks" in data:
        return [ConceptBlock.model_validate(item) for item in data["blocks"]]
    raise ValueError(f"unsupported fixture shape in {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run graphic selection (DecisionModel → pattern id)"
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        required=True,
        help="JSONL or JSON file of ConceptBlock records",
    )
    parser.add_argument(
        "--provider",
        default="fake",
        help="DecisionModel provider: fake (default) or jev",
    )
    parser.add_argument(
        "--document-key",
        default=None,
        help="Optional document key for the artifact",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write GraphicSelectionArtifact JSON to this path",
    )
    parser.add_argument(
        "--check-expected",
        action="store_true",
        help="Exit non-zero if emit.pattern_id != expected_pattern_id",
    )
    args = parser.parse_args(argv)

    try:
        model = build_decision_model(provider=args.provider)
    except DecisionModelConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    blocks = load_concept_blocks(args.fixtures)
    artifact = GraphicChooser(model).choose(
        blocks, document_key=args.document_key or args.fixtures.stem
    )

    mismatches: list[str] = []
    for unit, block in zip(artifact.units, blocks, strict=True):
        pattern = unit.decision.emit.get("pattern_id")
        print(
            f"{unit.unit_id}\tshape={unit.data_shape}\t"
            f"choice={unit.decision.choice.get('representation')}\t"
            f"emit={pattern}\t"
            f"gated={unit.decision.choice.get('field_gated')}"
        )
        if args.check_expected and block.expected_pattern_id is not None:
            if pattern != block.expected_pattern_id:
                mismatches.append(
                    f"{unit.unit_id}: emit={pattern} "
                    f"expected={block.expected_pattern_id}"
                )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            artifact.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.out}", file=sys.stderr)

    if mismatches:
        print("expected mismatches:", file=sys.stderr)
        for item in mismatches:
            print(f"  {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
