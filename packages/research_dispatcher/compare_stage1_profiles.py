#!/usr/bin/env python3
"""Compare tuned stage-one profiles across multiple models on a live Supabase subset."""

from __future__ import annotations

import argparse
import json
import sys
import time

from dotenv import load_dotenv

from config import Config
from src.database import DatabaseClient
from src.stage1_profiles import (
    apply_payload_limits,
    build_stage1_prompt,
    get_stage1_profile,
    list_stage1_profiles,
)
from src.synthesizer import Synthesizer, _clean_json_response, _dump_json_payload


DEFAULT_PROFILE_NAMES = [
    "gpt_5_mini_balanced",
    "kimi_k2_instruct_balanced",
    "kimi_k2_5_compact",
    "minimax_m2_5_compact",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=DEFAULT_PROFILE_NAMES,
        help=f"Stage-one profile names to compare. Available: {', '.join(list_stage1_profiles())}",
    )
    parser.add_argument(
        "--subset-size",
        type=int,
        default=3,
        help="Number of documents to pull from query_analysis().",
    )
    parser.add_argument(
        "--show-full",
        action="store_true",
        help="Include the full parsed through-lines for each profile.",
    )
    return parser.parse_args()


def _run_profile(
    synthesizer: Synthesizer,
    profile_name: str,
    payload: dict,
    show_full: bool,
) -> dict:
    profile = get_stage1_profile(profile_name)
    config = profile.to_model_config()
    stage1_payload = synthesizer._prepare_stage1_payload(
        apply_payload_limits(payload, profile),
        config,
    )
    prompt = build_stage1_prompt(synthesizer.throughline_prompt, profile)

    started = time.time()
    raw_response = ""
    cleaned = ""
    parsed = None
    error = None

    try:
        raw_response = synthesizer.client.generate(
            config=config,
            system=prompt,
            user=_dump_json_payload(stage1_payload),
        )
        cleaned = _clean_json_response(raw_response)
        parsed = synthesizer._coerce_stage1_result(json.loads(cleaned))
    except Exception as exc:
        error = str(exc)

    result = {
        "profile": profile.name,
        "config": {
            "provider": config.provider,
            "model": config.model,
            "max_tokens": config.max_tokens,
            "request_timeout_seconds": config.request_timeout_seconds,
            "max_retries": config.max_retries,
            "response_format": config.response_format,
            "tool_choice": config.tool_choice,
            "reasoning_effort": config.reasoning_effort,
            "prompt_profile": profile.prompt_profile,
            "throughline_count": profile.throughline_count,
            "max_key_insight_words": profile.max_key_insight_words,
            "max_supporting_themes": profile.max_supporting_themes,
            "max_supporting_trades": profile.max_supporting_trades,
            "payload_theme_limit": profile.payload_theme_limit,
            "payload_trade_limit": profile.payload_trade_limit,
        },
        "elapsed_seconds": round(time.time() - started, 2),
        "ok": parsed is not None,
        "error": error,
        "title": (parsed or {}).get("title"),
        "throughline_count": len((parsed or {}).get("through_lines", [])),
        "first_lead": ((parsed or {}).get("through_lines") or [{}])[0].get("lead"),
        "payload_theme_count": len(stage1_payload.get("themes", [])),
        "payload_trade_count": len(stage1_payload.get("trades", [])),
        "payload_bytes": len(_dump_json_payload(stage1_payload).encode("utf-8")),
        "raw_excerpt": raw_response[:1200],
        "cleaned_excerpt": cleaned[:1200],
    }

    if show_full:
        result["through_lines"] = (parsed or {}).get("through_lines", [])

    return result


def main() -> int:
    args = _parse_args()
    load_dotenv()

    if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
        raise SystemExit("Supabase credentials are missing.")
    if not Config.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is missing.")
    if not Config.DEEPINFRA_API_KEY:
        raise SystemExit("DEEPINFRA_API_KEY is missing.")

    db = DatabaseClient()
    records = db.query_analysis()
    subset = records[: args.subset_size]
    if not subset:
        raise SystemExit("No records returned by query_analysis().")

    synthesizer = Synthesizer(
        openai_api_key=Config.OPENAI_API_KEY,
        deepinfra_api_key=Config.DEEPINFRA_API_KEY,
        use_skill_pipeline=True,
    )
    base_payload = synthesizer._prepare_input(subset)

    results = []
    for profile_name in args.profiles:
        results.append(
            _run_profile(
                synthesizer=synthesizer,
                profile_name=profile_name,
                payload=base_payload,
                show_full=args.show_full,
            )
        )

    output = {
        "subset": {
            "document_count": len(subset),
            "documents": [
                {
                    "id": record.get("id"),
                    "source": record.get("source"),
                    "document_name": record.get("document_name"),
                    "source_date": str(record.get("source_date")),
                }
                for record in subset
            ],
            "payload_theme_count": len(base_payload.get("themes", [])),
            "payload_trade_count": len(base_payload.get("trades", [])),
            "payload_date_range": base_payload.get("date_range"),
        },
        "profiles": results,
    }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
