#!/usr/bin/env python3
"""
Backfill script for theme normalization.

Usage:
    # Dry run (show what would be done)
    python scripts/backfill_theme_normalization.py --dry-run

    # Actual run with progress
    python scripts/backfill_theme_normalization.py --batch-size 100

    # Resume from specific ID
    python scripts/backfill_theme_normalization.py --resume-from 12345

    # Limit total records
    python scripts/backfill_theme_normalization.py --limit 500

This script:
- Reads existing parsed_research records
- Extracts themes from parsed_data JSON
- Replaces normalized rows in research_themes, research_theme_excerpts
- Uses batching (100-500 records per batch)
- Commits per batch for observability
- Is rerunnable and idempotent per research_id
- Can resume from last processed ID
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

from supabase import create_client

# Add src to path for config
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings


def _compute_document_hash(text: str) -> str:
    """Compute SHA256 hash of cleaned text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_relevance(value: object) -> list[str]:
    """Normalize legacy relevance payloads into a text[]-compatible list."""
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            cleaned = str(item).strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []


def _fetch_batch(
    client: create_client,
    batch_size: int,
    last_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Fetch a batch of parsed_research records."""
    query = client.table("parsed_research").select(
        "id, source_date, source, document_name, document_id, parsed_data"
    )

    if last_id is not None:
        query = query.gt("id", last_id)

    query = query.order("id").limit(batch_size)

    if limit:
        query = query.limit(limit)

    response = query.execute()
    return response.data or []


def _extract_themes_from_parsed_data(parsed_data: dict) -> list[dict]:
    """Extract themes from parsed_data JSON."""
    if not parsed_data:
        return []

    themes_data = parsed_data.get("themes", [])
    if not themes_data:
        return []

    extracted = []
    for theme in themes_data:
        if not isinstance(theme, dict):
            continue

        excerpts = theme.get("excerpts", [])
        if isinstance(excerpts, list):
            excerpt_list = [
                {"text": e.get("text", "") if isinstance(e, dict) else str(e)} for e in excerpts
            ]
        else:
            excerpt_list = []

        arg_struct = theme.get("argument_structure")
        if arg_struct and isinstance(arg_struct, dict):
            argument_structure = arg_struct
        else:
            argument_structure = None

        extracted.append(
            {
                "label": theme.get("label", "Unknown"),
                "excerpts": excerpt_list,
                "relevance": _normalize_relevance(theme.get("relevance", [])),
                "classification": theme.get("classification", "Description"),
                "strength": theme.get("strength", "Secondary"),
                "confidence": theme.get("confidence", "Medium"),
                "evidence_count": theme.get("evidence_count", len(excerpt_list)),
                "mention_count": theme.get("mention_count", 0),
                "context": theme.get("context", ""),
                "directionality": theme.get("directionality"),
                "argument_structure": argument_structure,
            }
        )

    return extracted


def _extract_metadata_from_parsed_data(parsed_data: dict) -> dict:
    """Extract document-level metadata from parsed_data JSON."""
    if not parsed_data:
        return {}

    metadata = parsed_data.get("metadata", {})
    if not isinstance(metadata, dict):
        return {}

    return {
        "source": metadata.get("source"),
        "document_id": metadata.get("document_id"),
        "publisher": metadata.get("publisher"),
        "area": metadata.get("area", "Other"),
        "region": metadata.get("region", "Global"),
        "asset_focus": metadata.get("asset_focus", "multi-asset"),
        "document_link": metadata.get("document_link"),
    }


def _update_document_columns(
    client: create_client,
    research_id: int,
    theme_count: int,
    trade_count: int,
    metadata: dict,
    full_text: str,
) -> None:
    """Update document-level columns on parsed_research."""
    document_title = f"Analysis of {metadata.get('source', 'Unknown')}"
    document_hash = _compute_document_hash(full_text or "")

    update = {
        "document_title": document_title,
        "document_id": metadata.get("document_id"),
        "publisher": metadata.get("publisher"),
        "area": metadata.get("area"),
        "region": metadata.get("region"),
        "asset_focus": metadata.get("asset_focus"),
        "document_link": metadata.get("document_link"),
        "theme_count": theme_count,
        "trade_count": trade_count,
        "document_hash": document_hash,
    }

    client.table("parsed_research").update(update).eq("id", research_id).execute()


def _insert_normalized_themes(
    client: create_client,
    research_id: int,
    themes: list[dict],
) -> int:
    """Replace normalized theme rows for a document."""
    client.table("research_themes").delete().eq("research_id", research_id).execute()

    for idx, theme in enumerate(themes, start=1):
        theme_record = {
            "research_id": research_id,
            "theme_order": idx,
            "label": theme.get("label", "Unknown"),
            "scope": None,
            "primary_category": theme.get("relevance", [None])[0]
            if theme.get("relevance")
            else None,
            "relevance": theme.get("relevance", []),
            "classification": theme.get("classification", "Description"),
            "strength": theme.get("strength", "Secondary"),
            "confidence": theme.get("confidence", "Medium"),
            "evidence_count": theme.get("evidence_count", 0),
            "mention_count": theme.get("mention_count", 0),
            "context": theme.get("context", ""),
            "directionality": theme.get("directionality"),
            "argument_structure": theme.get("argument_structure"),
        }

        response = (
            client.table("research_themes")
            .insert(theme_record)
            .execute()
        )

        if response.data:
            theme_id = response.data[0].get("id")

            excerpts = theme.get("excerpts", [])
            for excerpt_idx, excerpt in enumerate(excerpts, start=1):
                client.table("research_theme_excerpts").insert(
                    {
                        "theme_id": theme_id,
                        "excerpt_order": excerpt_idx,
                        "excerpt_text": excerpt.get("text", ""),
                    }
                ).execute()

    return len(themes)


def _process_batch(
    client: create_client,
    records: list[dict],
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Process a batch of records. Returns (processed, skipped, errors)."""
    processed = 0
    skipped = 0
    errors = 0

    for record in records:
        research_id = record["id"]

        try:
            parsed_data = record.get("parsed_data", {})
            if not parsed_data:
                skipped += 1
                continue

            themes = _extract_themes_from_parsed_data(parsed_data)
            metadata = _extract_metadata_from_parsed_data(parsed_data)
            if not metadata.get("document_id") and record.get("document_id"):
                metadata["document_id"] = record.get("document_id")

            trades_data = parsed_data.get("trades", [])
            trade_count = len(trades_data) if isinstance(trades_data, list) else 0

            full_text = parsed_data.get("full_text", "")

            if dry_run:
                print(
                    f"  [DRY RUN] Would insert {len(themes)} themes for "
                    f"research_id={research_id} ({record.get('source', 'Unknown')})"
                )
                processed += 1
                continue

            _insert_normalized_themes(client, research_id, themes)

            # Update document columns after normalized writes succeed so reruns
            # can safely repair partial theme/excerpt inserts.
            _update_document_columns(
                client,
                research_id,
                len(themes),
                trade_count,
                metadata,
                full_text,
            )

            processed += 1

        except Exception as e:
            print(f"  ERROR processing research_id={research_id}: {e}")
            errors += 1

    return processed, skipped, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill theme normalization tables")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to process per batch (default: 100)",
    )
    parser.add_argument(
        "--resume-from",
        type=int,
        default=None,
        help="Resume from specific research_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit total records to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Delay between batches in seconds (default: 0.1)",
    )

    args = parser.parse_args()

    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_key)

    print("Starting backfill...")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Resume from: {args.resume_from or 'beginning'}")
    print(f"  Limit: {args.limit or 'none'}")
    print(f"  Dry run: {args.dry_run}")
    print()

    total_processed = 0
    total_skipped = 0
    total_errors = 0
    last_id = args.resume_from
    remaining_limit = args.limit

    while True:
        batch_limit = min(args.batch_size, remaining_limit) if remaining_limit else args.batch_size

        records = _fetch_batch(
            client,
            batch_limit,
            last_id,
            batch_limit,
        )

        if not records:
            break

        research_ids = [r["id"] for r in records]
        print(f"Processing batch: IDs {min(research_ids)}-{max(research_ids)}")

        processed, skipped, errors = _process_batch(
            client,
            records,
            dry_run=args.dry_run,
        )

        total_processed += processed
        total_skipped += skipped
        total_errors += errors

        print(f"  Processed: {processed}, Skipped: {skipped}, Errors: {errors}")

        last_id = max(research_ids)

        if remaining_limit:
            remaining_limit -= processed
            if remaining_limit <= 0:
                break

        if len(records) < args.batch_size:
            break

        time.sleep(args.delay)

    print()
    print("=" * 50)
    print("Backfill complete!")
    print(f"  Total processed: {total_processed}")
    print(f"  Total skipped: {total_skipped}")
    print(f"  Total errors: {total_errors}")
    print(f"  Last processed ID: {last_id}")
    print("=" * 50)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
