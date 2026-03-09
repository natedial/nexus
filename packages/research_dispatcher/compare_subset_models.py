#!/usr/bin/env python3
"""Compare stage-one throughline outputs across two models on a small live Supabase subset."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from dotenv import load_dotenv

from config import Config
from src.database import DatabaseClient
from src.llm import ModelConfig
from src.synthesizer import Synthesizer, _clean_json_response, _dump_json_payload


SUBSET_SIZE = 3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deepinfra-model",
        default="moonshotai/Kimi-K2-Instruct-0905",
        help="DeepInfra model id to compare against OpenAI.",
    )
    parser.add_argument(
        "--deepinfra-max-tokens",
        type=int,
        default=1600,
        help="Max tokens for the DeepInfra comparison run.",
    )
    parser.add_argument(
        "--deepinfra-timeout",
        type=float,
        default=60,
        help="Per-request timeout in seconds for the DeepInfra comparison run.",
    )
    parser.add_argument(
        "--deepinfra-json-object",
        action="store_true",
        help="Use response_format={type: json_object} for the DeepInfra request.",
    )
    parser.add_argument(
        "--deepinfra-drop-response-format-on-retry",
        action="store_true",
        help="Retry without response_format if the provider rejects it.",
    )
    parser.add_argument(
        "--deepinfra-tool-choice",
        choices=("none", "auto", "required"),
        default=None,
        help="Optional tool_choice for the DeepInfra request.",
    )
    parser.add_argument(
        "--deepinfra-reasoning-effort",
        choices=("none", "low", "medium", "high"),
        default=None,
        help="Optional reasoning_effort for the DeepInfra request.",
    )
    parser.add_argument(
        "--prompt-profile",
        choices=("full", "lean", "minimal"),
        default="full",
        help="System prompt profile for stage-one testing.",
    )
    parser.add_argument(
        "--throughline-count",
        type=int,
        default=0,
        help="If set, override the prompt to request exactly this many through-lines.",
    )
    parser.add_argument(
        "--max-key-insight-words",
        type=int,
        default=0,
        help="If set, cap each key_insight to this many words in the test prompt.",
    )
    parser.add_argument(
        "--max-supporting-themes",
        type=int,
        default=0,
        help="If set, cap supporting_themes per through-line in the test prompt.",
    )
    parser.add_argument(
        "--max-supporting-trades",
        type=int,
        default=0,
        help="If set, cap supporting_trades per through-line in the test prompt.",
    )
    parser.add_argument(
        "--payload-theme-limit",
        type=int,
        default=0,
        help="If set, keep only the top-N themes in the stage-one payload.",
    )
    parser.add_argument(
        "--payload-trade-limit",
        type=int,
        default=0,
        help="If set, keep only the top-N trades in the stage-one payload.",
    )
    return parser.parse_args()


def _strength_score(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    return {
        "primary": 3,
        "secondary": 2,
        "tertiary": 1,
    }.get(normalized, 0)


def _confidence_score(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(normalized, 0)


def _sort_payload_items(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Rank stage-one payload items so caps keep the densest evidence first."""
    if kind == "themes":
        return sorted(
            items,
            key=lambda item: (
                _strength_score(item.get("strength")),
                _confidence_score(item.get("confidence")),
                int(item.get("mention_count") or 0),
                len(str(item.get("context") or "")),
            ),
            reverse=True,
        )

    return sorted(
        items,
        key=lambda item: (
            _confidence_score(item.get("conviction")),
            len(str(item.get("text") or "")),
            len(str(item.get("rationale") or "")),
        ),
        reverse=True,
    )


def _apply_payload_limits(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Optionally cap theme/trade counts for model-tolerance experiments."""
    limited = dict(payload)

    themes = list(payload.get("themes", []))
    trades = list(payload.get("trades", []))

    if args.payload_theme_limit > 0 and len(themes) > args.payload_theme_limit:
        limited["themes"] = _sort_payload_items(themes, "themes")[: args.payload_theme_limit]
    else:
        limited["themes"] = themes

    if args.payload_trade_limit > 0 and len(trades) > args.payload_trade_limit:
        limited["trades"] = _sort_payload_items(trades, "trades")[: args.payload_trade_limit]
    else:
        limited["trades"] = trades

    return limited


def _build_stage1_prompt(base_prompt: str, args: argparse.Namespace) -> str:
    """Build an experimental prompt profile for stage-one tuning."""
    count = args.throughline_count
    insight_words = args.max_key_insight_words
    theme_cap = args.max_supporting_themes
    trade_cap = args.max_supporting_trades

    if args.prompt_profile == "full":
        overrides = []
        if count > 0:
            overrides.append(f"- Override the default range and return exactly {count} through-lines.")
        if insight_words > 0:
            overrides.append(f"- Override the default key_insight budget and keep each key_insight to {insight_words} words or fewer.")
        if theme_cap > 0:
            overrides.append(f"- Keep supporting_themes to at most {theme_cap} items per through-line.")
        if trade_cap > 0:
            overrides.append(f"- Keep supporting_trades to at most {trade_cap} items per through-line.")
        if not overrides:
            return base_prompt
        return base_prompt + "\n\nTEST OVERRIDES\n" + "\n".join(overrides)

    count = count or (3 if args.prompt_profile == "lean" else 2)
    insight_words = insight_words or (85 if args.prompt_profile == "lean" else 60)
    theme_cap = theme_cap or (4 if args.prompt_profile == "lean" else 3)
    trade_cap = trade_cap or 1

    if args.prompt_profile == "lean":
        return f"""You are a cross-document macro and rates synthesizer.

Task:
- Find the dominant market beliefs across the supplied themes and trades.
- Prioritize consensus first, then the fracture lines inside that consensus.
- Include at most 1 contrarian through-line, and only if it attacks a shared market assumption.
- Ignore weak or orphaned ideas.

Return EXACTLY ONE JSON object with this schema:
{{
  "title": "short synthesis title",
  "through_lines": [
    {{
      "lead": "causal one-line finding",
      "supporting_sources": ["Source A", "Source B"],
      "consensus_level": "strong_consensus|moderate_consensus|mixed_views|contrarian",
      "consensus_anchor": "dominant market belief this line supports, fractures, or challenges",
      "supporting_themes": ["theme 1", "theme 2"],
      "supporting_trades": ["trade expression"],
      "key_insight": "short narrative synthesis"
    }}
  ]
}}

Rules:
- Return exactly {count} through-lines.
- At least half of the through-lines must be consensus-anchored.
- supporting_themes: at most {theme_cap}.
- supporting_trades: at most {trade_cap}.
- key_insight: at most {insight_words} words.
- Every through-line must explain the mechanism and the flip signpost.
- Use only the provided evidence. If support is weak, omit the idea.
- No markdown. No prose outside JSON."""

    return f"""Return EXACTLY ONE JSON object with:
- "title"
- "through_lines": exactly {count} items

Each through-line must contain:
- lead
- supporting_sources
- consensus_level
- consensus_anchor
- supporting_themes (max {theme_cap})
- supporting_trades (max {trade_cap})
- key_insight (max {insight_words} words)

Ranking:
1. consensus the market is pricing
2. fractures inside that consensus
3. one contrarian risk only if it breaks a shared assumption

Rules:
- consensus first
- concise wording
- use only supplied evidence
- include mechanism and flip signpost
- JSON only"""


def _run_stage1(
    synthesizer: Synthesizer,
    config: ModelConfig,
    payload: dict,
    prompt: str,
) -> dict:
    started = time.time()
    raw_response = ""
    cleaned = ""
    parsed = None
    error = None

    try:
        stage1_payload = synthesizer._prepare_stage1_payload(payload, config)
        raw_response = synthesizer.client.generate(
            config=config,
            system=prompt,
            user=_dump_json_payload(stage1_payload),
        )
        cleaned = _clean_json_response(raw_response)
        parsed = synthesizer._coerce_stage1_result(json.loads(cleaned))
    except Exception as exc:
        error = str(exc)

    return {
        "config": {
            "provider": config.provider,
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "request_timeout_seconds": config.request_timeout_seconds,
            "max_retries": config.max_retries,
            "response_format": config.response_format,
            "tool_choice": config.tool_choice,
            "reasoning_effort": config.reasoning_effort,
        },
        "elapsed_seconds": round(time.time() - started, 2),
        "ok": parsed is not None,
        "error": error,
        "title": (parsed or {}).get("title"),
        "throughline_count": len((parsed or {}).get("through_lines", [])),
        "through_lines": (parsed or {}).get("through_lines", []),
        "raw_excerpt": raw_response[:1200],
        "cleaned_excerpt": cleaned[:1200],
        "payload_bytes": len(_dump_json_payload(stage1_payload).encode("utf-8")),
    }


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
    subset = records[:SUBSET_SIZE]
    if not subset:
        raise SystemExit("No records returned by query_analysis().")

    synthesizer = Synthesizer(
        openai_api_key=Config.OPENAI_API_KEY,
        deepinfra_api_key=Config.DEEPINFRA_API_KEY,
        use_skill_pipeline=True,
    )
    payload = _apply_payload_limits(synthesizer._prepare_input(subset), args)
    prompt = _build_stage1_prompt(synthesizer.throughline_prompt, args)

    deepinfra_config = ModelConfig(
        provider="deepinfra",
        model=args.deepinfra_model,
        max_tokens=args.deepinfra_max_tokens,
        temperature=0,
        request_timeout_seconds=args.deepinfra_timeout,
        max_retries=0,
        response_format={"type": "json_object"} if args.deepinfra_json_object else None,
        drop_response_format_on_retry=args.deepinfra_drop_response_format_on_retry,
        tool_choice=args.deepinfra_tool_choice,
        reasoning_effort=args.deepinfra_reasoning_effort,
    )
    openai_config = ModelConfig(
        provider="openai",
        model="gpt-5-mini",
        max_tokens=16000,
        temperature=0,
        request_timeout_seconds=90,
        max_retries=0,
    )

    deepinfra_result = _run_stage1(synthesizer, deepinfra_config, payload, prompt)
    openai_result = _run_stage1(synthesizer, openai_config, payload, prompt)

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
            "payload_theme_count": len(payload.get("themes", [])),
            "payload_trade_count": len(payload.get("trades", [])),
            "payload_date_range": payload.get("date_range"),
            "prompt_profile": args.prompt_profile,
            "throughline_count": args.throughline_count,
            "max_key_insight_words": args.max_key_insight_words,
        },
        "deepinfra_candidate": deepinfra_result,
        "openai_gpt_5_mini": openai_result,
    }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
