#!/usr/bin/env python3
"""Smoke-test configured LLM providers with a tiny JSON task."""

import argparse
import json

from src.config import get_settings
from src.extraction.json_utils import clean_json_response
from src.llm import LLMClient, ModelConfig


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a lightweight provider smoke test."
    )
    parser.add_argument(
        "--provider",
        default="groq",
        choices=["openai", "anthropic", "groq", "deepinfra", "openrouter", "fireworks", "together"],
        help="Provider to smoke-test.",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-oss-20b",
        help="Model id to call on the selected provider.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=256,
        help="Max output tokens for the smoke request.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=None,
        help="Optional reasoning effort for providers/models that support it.",
    )
    parser.add_argument(
        "--fallback-provider",
        default=None,
        choices=["openai", "anthropic", "groq", "deepinfra", "openrouter", "fireworks", "together"],
        help="Optional fallback provider.",
    )
    parser.add_argument(
        "--fallback-model",
        default=None,
        help="Optional fallback model id (requires --fallback-provider).",
    )
    parser.add_argument(
        "--fallback-max-tokens",
        type=int,
        default=256,
        help="Max output tokens for fallback request.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    client = LLMClient(
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        groq_api_key=settings.groq_api_key,
        deepinfra_api_key=settings.deepinfra_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        fireworks_api_key=settings.fireworks_api_key,
        together_api_key=settings.together_api_key,
    )
    config = ModelConfig(
        provider=args.provider,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=0,
        reasoning_effort=args.reasoning_effort,
    )
    if args.fallback_provider or args.fallback_model:
        if not (args.fallback_provider and args.fallback_model):
            print("SMOKE FAILED: --fallback-provider and --fallback-model must be set together")
            return 1
        config.fallback = [
            ModelConfig(
                provider=args.fallback_provider,
                model=args.fallback_model,
                max_tokens=args.fallback_max_tokens,
                temperature=0,
            )
        ]
    system = (
        "Return valid JSON only with keys: status, provider, model. "
        "Use status='ok'."
    )
    response = client.generate(
        config=config,
        system=system,
        user=f"Run provider smoke test for {args.provider}/{args.model}.",
    )

    try:
        parsed = json.loads(clean_json_response(response))
    except Exception as exc:
        print("SMOKE FAILED: response was not valid JSON")
        print(f"error={exc}")
        print(f"raw={response[:500]}")
        return 1

    print("SMOKE OK")
    print(json.dumps(parsed, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
