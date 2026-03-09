#!/usr/bin/env python3
"""Minimal DeepInfra smoke test for raw completions and throughline synthesis."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from typing import Any

from dotenv import load_dotenv

from src.llm import LLMClient, ModelConfig
from src.synthesizer import Synthesizer, _clean_json_response, _dump_json_payload


SAMPLE_PAYLOAD = {
    "themes": [
        {
            "source": "Goldman Sachs",
            "document": "GS Rates Weekly",
            "label": "Fed easing path",
            "context": "GS expects 75bp of Fed cuts starting in June as labor softens, but the easing pace could stay gradual if inflation proves sticky.",
            "strength": "Primary",
            "confidence": "High",
        },
        {
            "source": "JPMorgan",
            "document": "JPM US Rates",
            "label": "Front-end rallies if payrolls weaken",
            "context": "JPM sees the front end richening on softer payrolls, but warns Treasury supply could limit the long-end rally.",
            "strength": "Primary",
            "confidence": "High",
        },
        {
            "source": "Barclays",
            "document": "Barclays Macro Strategy",
            "label": "Treasury supply offsets duration longs",
            "context": "Barclays argues heavy refunding supply can blunt the long-end response even if the Fed turns more dovish.",
            "strength": "Secondary",
            "confidence": "Medium",
        },
    ],
    "trades": [
        {
            "source": "Goldman Sachs",
            "document": "GS Rates Weekly",
            "text": "Receive 5Y SOFR at 3.85%, target 3.50%, stop 4.05% because labor is cooling faster than inflation.",
            "conviction": "High",
            "timeframe": "weeks",
        },
        {
            "source": "JPMorgan",
            "document": "JPM US Rates",
            "text": "Favor 2s10s steepeners via swaps as front-end cuts reprice before the long end absorbs supply.",
            "conviction": "Medium",
            "timeframe": "weeks",
        },
    ],
    "document_count": 3,
    "sources": ["Goldman Sachs", "JPMorgan", "Barclays"],
    "date_range": "2026-03-01 to 2026-03-08",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="moonshotai/Kimi-K2.5",
        help="DeepInfra model id to test.",
    )
    parser.add_argument(
        "--mode",
        choices=("raw", "throughline"),
        default="throughline",
        help="Whether to run a minimal chat completion or the stage-one throughline prompt.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Retry count after the initial attempt.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1200,
        help="Completion token budget for the test.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full parsed result for throughline mode.",
    )
    parser.add_argument(
        "--wall-timeout",
        type=int,
        default=0,
        help="Hard wall-clock timeout in seconds for the whole smoke test. Disabled when 0.",
    )
    parser.add_argument(
        "--json-object",
        action="store_true",
        help="Request response_format={type: json_object}.",
    )
    parser.add_argument(
        "--drop-response-format-on-retry",
        action="store_true",
        help="If the provider rejects response_format, retry once without it inside the same request attempt.",
    )
    parser.add_argument(
        "--tool-choice",
        choices=("none", "auto", "required"),
        default=None,
        help="Optional tool_choice value for OpenAI-compatible providers.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high"),
        default=None,
        help="Optional reasoning_effort value for OpenAI-compatible providers.",
    )
    parser.add_argument(
        "--prompt-profile",
        choices=("full", "lean", "minimal"),
        default="full",
        help="System prompt profile for throughline mode.",
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
        help="If set, cap each key_insight to this many words.",
    )
    return parser.parse_args()


@contextmanager
def _wall_timeout(seconds: int):
    if seconds <= 0:
        yield
        return

    def _handle_timeout(signum, frame):
        raise TimeoutError(f"Smoke test exceeded {seconds} seconds.")

    previous = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _require_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("DEEPINFRA_API_KEY")
    if not api_key:
        raise SystemExit("DEEPINFRA_API_KEY is missing from the environment.")
    return api_key


def _build_stage1_prompt(base_prompt: str, args: argparse.Namespace) -> str:
    """Build a shorter prompt profile for DeepInfra model tuning."""
    count = args.throughline_count
    insight_words = args.max_key_insight_words

    if args.prompt_profile == "full":
        overrides = []
        if count > 0:
            overrides.append(f"- Override the default range and return exactly {count} through-lines.")
        if insight_words > 0:
            overrides.append(f"- Override the default key_insight budget and keep each key_insight to {insight_words} words or fewer.")
        if not overrides:
            return base_prompt
        return base_prompt + "\n\nTEST OVERRIDES\n" + "\n".join(overrides)

    count = count or (3 if args.prompt_profile == "lean" else 2)
    insight_words = insight_words or (80 if args.prompt_profile == "lean" else 60)

    if args.prompt_profile == "lean":
        return f"""You are a cross-document macro and rates synthesizer.

Return EXACTLY ONE JSON object:
{{
  "title": "short title",
  "through_lines": [
    {{
      "lead": "causal finding",
      "supporting_sources": ["Source A"],
      "consensus_level": "strong_consensus|moderate_consensus|mixed_views|contrarian",
      "consensus_anchor": "dominant market belief",
      "supporting_themes": ["theme 1", "theme 2"],
      "supporting_trades": ["trade expression"],
      "key_insight": "short synthesis"
    }}
  ]
}}

Rules:
- Return exactly {count} through-lines.
- Consensus first, then fractures.
- Include at most 1 contrarian through-line.
- Each key_insight must be {insight_words} words or fewer.
- Include mechanism and flip signpost.
- JSON only."""

    return f"""Return EXACTLY ONE JSON object with title and exactly {count} through_lines.
Each through-line must contain lead, supporting_sources, consensus_level, consensus_anchor, supporting_themes, supporting_trades, key_insight.
Consensus first. At most 1 contrarian through-line.
Each key_insight must be {insight_words} words or fewer.
JSON only."""


def _raw_completion(api_key: str, args: argparse.Namespace) -> dict:
    client = LLMClient(deepinfra_api_key=api_key)
    config = ModelConfig(
        provider="deepinfra",
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=0,
        request_timeout_seconds=args.timeout,
        max_retries=args.retries,
        response_format={"type": "json_object"} if args.json_object else None,
        drop_response_format_on_retry=args.drop_response_format_on_retry,
        tool_choice=args.tool_choice,
        reasoning_effort=args.reasoning_effort,
    )
    started = time.time()
    text = client.generate(
        config=config,
        system="You are a helpful assistant. Return only the requested text.",
        user="Reply with the single word ok.",
    )
    return {
        "mode": "raw",
        "model": args.model,
        "elapsed_seconds": round(time.time() - started, 2),
        "text": text,
    }


def _throughline_completion(api_key: str, args: argparse.Namespace) -> dict:
    synthesizer = Synthesizer(deepinfra_api_key=api_key, use_skill_pipeline=True)
    config = ModelConfig(
        provider="deepinfra",
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=0,
        request_timeout_seconds=args.timeout,
        max_retries=args.retries,
        response_format={"type": "json_object"} if args.json_object else None,
        drop_response_format_on_retry=args.drop_response_format_on_retry,
        tool_choice=args.tool_choice,
        reasoning_effort=args.reasoning_effort,
    )
    synthesizer._throughline_config = config
    prompt = _build_stage1_prompt(synthesizer.throughline_prompt, args)
    started = time.time()
    stage1_payload = synthesizer._prepare_stage1_payload(SAMPLE_PAYLOAD, config)
    raw_response = synthesizer.client.generate(
        config=config,
        system=prompt,
        user=_dump_json_payload(stage1_payload),
    )
    cleaned = _clean_json_response(raw_response)
    try:
        result = synthesizer._coerce_stage1_result(json.loads(cleaned))
    except json.JSONDecodeError:
        result = None
    summary = {
        "mode": "throughline",
        "model": args.model,
        "elapsed_seconds": round(time.time() - started, 2),
        "ok": result is not None,
        "title": (result or {}).get("title"),
        "throughline_count": len((result or {}).get("through_lines", [])),
        "first_lead": ((result or {}).get("through_lines") or [{}])[0].get("lead"),
        "payload_bytes": len(_dump_json_payload(stage1_payload).encode("utf-8")),
    }
    if args.full:
        summary["result"] = result
    if result is None:
        summary["raw_excerpt"] = raw_response[:600]
        summary["cleaned_excerpt"] = cleaned[:600]
    return summary


def main() -> int:
    args = _parse_args()
    api_key = _require_api_key()

    try:
        with _wall_timeout(args.wall_timeout):
            if args.mode == "raw":
                output = _raw_completion(api_key, args)
            else:
                output = _throughline_completion(api_key, args)
    except TimeoutError as exc:
        output = {
            "mode": args.mode,
            "model": args.model,
            "ok": False,
            "error": str(exc),
        }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
