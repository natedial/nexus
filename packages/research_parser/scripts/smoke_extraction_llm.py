#!/usr/bin/env python3
"""Lightweight live smoke test for extraction steps using configured models."""

import argparse
import json

from src.config import get_settings
from src.extraction import (
    extract_metadata,
    extract_themes,
    extract_trades,
    strip_boilerplate,
)
from src.llm import LLMClient, load_model_config


SAMPLE_TEXT = """
Goldman Sachs Macro Strategy
Date: 2026-02-25
Region: US
Asset Focus: Rates

We remain constructive on front-end US rates as growth moderates and inflation prints soften.
Our base case is for the 2y yield to decline over the next 3-6 months.
Positioning remains crowded in long USD and light duration.

Trade idea:
Receive 2y USD swaps versus paying 10y USD swaps, targeting curve steepening over 3 months.
Conviction: high.

Analyst Certification:
The views expressed accurately reflect the analyst's personal views.
Important Disclosures:
This material is for informational purposes only and is not investment advice.
Distribution and other regulatory disclosures apply.
Copyright 2026 Goldman Sachs.
""".strip()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run live extraction smoke tests with current config/models.yaml."
    )
    parser.add_argument(
        "--skip-themes",
        action="store_true",
        help="Skip themes extraction to reduce cost.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    model_config = load_model_config(config_path=settings.model_config_path)
    client = LLMClient(
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        groq_api_key=settings.groq_api_key,
        deepinfra_api_key=settings.deepinfra_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        fireworks_api_key=settings.fireworks_api_key,
        together_api_key=settings.together_api_key,
    )

    print("SMOKE: boilerplate")
    clean_text = strip_boilerplate(
        client,
        SAMPLE_TEXT,
        config=model_config.boilerplate,
        deterministic_only=settings.boilerplate_deterministic_only,
        document_name="2026-02-25_GS_Macro_Smoke.pdf",
    )
    print(
        json.dumps(
            {
                "provider": model_config.boilerplate.provider,
                "model": model_config.boilerplate.model,
                "input_chars": len(SAMPLE_TEXT),
                "output_chars": len(clean_text),
            },
            indent=2,
        )
    )

    print("SMOKE: metadata")
    metadata = extract_metadata(client, clean_text, config=model_config.metadata)
    print(
        json.dumps(
            {
                "provider": model_config.metadata.provider,
                "model": model_config.metadata.model,
                "source": metadata.source,
                "source_date": metadata.source_date,
                "area": metadata.area,
                "region": metadata.region,
                "asset_focus": metadata.asset_focus,
            },
            default=str,
            indent=2,
        )
    )

    if not args.skip_themes:
        print("SMOKE: themes")
        themes = extract_themes(client, clean_text, config=model_config.themes)
        print(
            json.dumps(
                {
                    "provider": model_config.themes.provider,
                    "model": model_config.themes.model,
                    "count": len(themes),
                    "labels": [t.label for t in themes[:3]],
                },
                indent=2,
            )
        )

    print("SMOKE: trades")
    trades = extract_trades(client, clean_text, config=model_config.trades)
    print(
        json.dumps(
            {
                "provider": model_config.trades.provider,
                "model": model_config.trades.model,
                "count": len(trades),
                "sample": [t.text for t in trades[:2]],
            },
            indent=2,
        )
    )

    print("SMOKE OK: extraction path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
