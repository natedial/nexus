#!/usr/bin/env python3
"""Compare parser-exclusive and agent-inclusive dispatcher report JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.report_comparison import compare_reports


def _load_json(path: str) -> dict:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser-report-json", required=True)
    parser.add_argument("--analyst-report-json", required=True)
    parser.add_argument("--baseline-report-json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    comparison = compare_reports(
        _load_json(args.parser_report_json),
        _load_json(args.analyst_report_json),
        _load_json(args.baseline_report_json) if args.baseline_report_json else None,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
