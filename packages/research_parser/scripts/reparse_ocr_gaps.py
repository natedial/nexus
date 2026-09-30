#!/usr/bin/env python3
"""Force-reparse OCR-gap docs (triggers + FALLBACK) with the RapidOCR path."""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from src.config import get_settings
from src.pipeline import Pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gap-list",
        type=Path,
        default=Path("data/ocr-gap-ids.tsv"),
        help="TSV of file_id\\tfile_name (default: data/ocr-gap-ids.tsv)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("data/ocr-gap-reparse-results.tsv"),
        help="Where to write per-file status TSV",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max files to process (0 = all)",
    )
    args = parser.parse_args()

    rows: list[tuple[str, str]] = []
    for line in args.gap_list.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        file_id, name = line.split("\t", 1)
        rows.append((file_id, name))
    if args.limit > 0:
        rows = rows[: args.limit]

    print(f"Host re-parse {len(rows)} OCR-gap docs", flush=True)
    pipeline = Pipeline(get_settings())
    ok_n = fail_n = 0
    results: list[str] = []

    for i, (file_id, name) in enumerate(rows, 1):
        print(f"\n[{i}/{len(rows)}] {name}", flush=True)
        try:
            success = pipeline.process_file(file_id, name, force=True)
            status = "ok" if success else "fail"
            ok_n += int(success)
            fail_n += int(not success)
            print(f"  {status}", flush=True)
        except Exception as exc:
            fail_n += 1
            status = f"error:{exc}"
            print(f"  ERROR {exc}", flush=True)
            traceback.print_exc()
        results.append(f"{file_id}\t{status}\t{name}")

    args.results.write_text("\n".join(results) + "\n")
    print(f"\nDONE ok={ok_n} fail={fail_n} results={args.results}", flush=True)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
