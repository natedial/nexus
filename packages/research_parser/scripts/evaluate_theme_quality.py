#!/usr/bin/env python3
"""Probe theme quality with a compact, decision-focused schema."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

from src.config import get_settings
from src.extraction import strip_boilerplate
from src.extraction.json_utils import clean_json_response
from src.llm import LLMClient, ModelConfig, load_model_config


QUALITY_RESPONSE_FORMAT = {
    "type": "json_object",
}


def _build_prompt() -> str:
    return (
        "You are extracting the most decision-useful macro/market themes from a sell-side research note.\n"
        "Return valid JSON only with this shape:\n"
        '{\n'
        '  "themes": [\n'
        "    {\n"
        '      "label": "short theme name",\n'
        '      "thesis": "1-2 sentence explanation of the actual claim",\n'
        '      "why_it_matters": "Why this matters for positioning, risk, or market interpretation",\n'
        '      "actionability": "Specific implication for investors/traders",\n'
        '      "evidence": ["short verbatim excerpt 1", "short verbatim excerpt 2"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Return at most 6 themes.\n"
        "- Prefer specific, non-generic themes.\n"
        "- Separate closely related but distinct tradable ideas.\n"
        "- Do not pad with weak themes.\n"
        "- Actionability must be concrete, not generic.\n"
    )

def _parse_model_spec(spec: str, max_tokens: int) -> ModelConfig:
    provider, model = spec.split(":", 1)
    return ModelConfig(provider=provider, model=model, max_tokens=max_tokens, temperature=0)


def _run_model_once(
    queue: mp.Queue,
    spec: str,
    max_tokens: int,
    clean: str,
    system: str,
    response_format: dict | None,
) -> None:
    try:
        settings = get_settings()
        client = LLMClient(
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
            groq_api_key=settings.groq_api_key,
            deepinfra_api_key=settings.deepinfra_api_key,
            openrouter_api_key=settings.openrouter_api_key,
            fireworks_api_key=settings.fireworks_api_key,
            together_api_key=settings.together_api_key,
            request_timeout_s=60.0,
        )
        model_cfg = _parse_model_spec(spec, max_tokens)
        raw_response = client.generate_once(
            config=model_cfg,
            system=system,
            user=clean,
            response_format=response_format,
        )
        parsed = json.loads(clean_json_response(raw_response))
        queue.put({"themes": parsed.get("themes", [])})
    except Exception as exc:
        queue.put({"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare compact theme quality across models.")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--document-name", required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--char-limit", type=int)
    parser.add_argument("--disable-response-format", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    config = load_model_config(config_path=settings.model_config_path)
    client = LLMClient(
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        groq_api_key=settings.groq_api_key,
        deepinfra_api_key=settings.deepinfra_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        fireworks_api_key=settings.fireworks_api_key,
        together_api_key=settings.together_api_key,
    )

    raw = args.artifact.read_text(encoding="utf-8")
    clean = strip_boilerplate(
        client,
        raw,
        config=config.boilerplate,
        deterministic_only=settings.boilerplate_deterministic_only,
        document_name=args.document_name,
        artifact_dir=settings.artifact_base_dir / f"theme_quality_{args.artifact.stem}",
    )
    if args.char_limit and args.char_limit > 0:
        clean = clean[:args.char_limit]

    payload = {
        "artifact": str(args.artifact),
        "document_name": args.document_name,
        "clean_chars": len(clean),
        "results": [],
    }
    system = _build_prompt()
    for spec in args.model:
        start = time.time()
        queue: mp.Queue = mp.get_context("spawn").Queue()
        proc = mp.get_context("spawn").Process(
            target=_run_model_once,
            args=(queue, spec, args.max_tokens, clean, system, None if args.disable_response_format else QUALITY_RESPONSE_FORMAT),
        )
        proc.start()
        proc.join(args.timeout)
        result = {
            "model": spec,
            "elapsed_s": round(time.time() - start, 2),
        }
        if proc.is_alive():
            proc.terminate()
            proc.join()
            result["error"] = f"TimeoutError: Timed out after {args.timeout}s"
        else:
            if queue.empty():
                result["error"] = "RuntimeError: Model process exited without returning a result"
            else:
                result.update(queue.get())
        payload["results"].append(result)

    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
