"""CLI for eval infrastructure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research_analysis_layer.config import Settings
from research_analysis_layer.evals.runner import AgentEvalRunner
from research_analysis_layer.evals.comparison import DEFAULT_FIELD_WEIGHTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Eval infrastructure for analysis agents"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run eval on golden set")
    run_parser.add_argument(
        "--golden",
        type=Path,
        required=True,
        help="Path to golden dataset directory",
    )
    run_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for results",
    )
    run_parser.add_argument(
        "--agents",
        type=str,
        default="synthesizer",
        help="Comma-separated list of agent types (default: synthesizer)",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of docs to evaluate",
    )
    run_parser.add_argument(
        "--judge",
        action="store_true",
        help="Run LLM judge for semantic evaluation",
    )
    run_parser.add_argument(
        "--judge-model",
        type=str,
        default="gpt-5-mini",
        help="Model to use for LLM judge",
    )

    compare_parser = subparsers.add_parser(
        "compare", help="Compare current results to baseline"
    )
    compare_parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Path to baseline results JSON",
    )
    compare_parser.add_argument(
        "--current",
        type=Path,
        help="Path to current results (default: auto-detect latest)",
    )

    export_parser = subparsers.add_parser(
        "export", help="Export training captures for fine-tuning"
    )
    export_parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    export_parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD, default: today)",
    )
    export_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.75,
        help="Minimum confidence threshold (default: 0.75)",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSONL file path",
    )

    return parser


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    """Run eval on golden set."""
    golden_path = args.golden
    output_dir = args.output

    if not golden_path.exists():
        print(f"Error: Golden path not found: {golden_path}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    agent_types = [a.strip() for a in args.agents.split(",")]

    print(f"Running eval on {golden_path}")
    print(f"Agents: {', '.join(agent_types)}")
    print(f"Output: {output_dir}")

    from research_analysis_layer.services.agent_llm_client import (
        build_agent_llm_client,
    )

    llm_client = build_agent_llm_client(settings)
    if llm_client is None:
        print(
            "Error: set AGENT_LLM_PROVIDER=openai (with AGENT_LLM_API_KEY) "
            "or AGENT_LLM_PROVIDER=codex",
            file=sys.stderr,
        )
        return 1

    runner = AgentEvalRunner(
        llm_client=llm_client,
        golden_path=golden_path,
        output_dir=output_dir,
        judge_model=args.judge_model,
    )

    summary = runner.run_golden(
        limit=args.limit,
        agent_types=agent_types,
        use_judge=args.judge,
    )

    output_path = runner.save_results(summary)

    print(f"\n=== Eval Results ===")
    print(f"Documents: {summary.total_docs}")
    print(f"Schema validity: {summary.schema_validity_rate:.1%}")
    print(f"Confidence (avg): {summary.confidence_avg:.3f}")
    print(f"Latency (avg): {summary.latency_avg_ms}ms")
    print(f"Latency (p95): {summary.latency_p95_ms}ms")

    if summary.field_scores:
        print(f"\nField scores:")
        for field, score in summary.field_scores.items():
            weight = DEFAULT_FIELD_WEIGHTS.get(field, 0)
            print(f"  {field}: {score:.3f} (weight: {weight})")

    if summary.judge_scores:
        print(f"\nJudge scores:")
        for dimension, score in summary.judge_scores.items():
            print(f"  {dimension}: {score:.3f}")

    print(f"\nResults saved to: {output_path}")

    if summary.schema_validity_rate < 0.95:
        print(f"\nWARNING: Schema validity below threshold (95%)", file=sys.stderr)

    return 0


def cmd_compare(args: argparse.Namespace, settings: Settings) -> int:
    """Compare results to baseline."""
    baseline_path = args.baseline

    if not baseline_path.exists():
        print(f"Error: Baseline not found: {baseline_path}", file=sys.stderr)
        return 1

    golden_path = Path("evals/golden")
    if not golden_path.exists():
        golden_path = Path("research_analyst/evals/golden")

    output_dir = Path("evals/results")
    if not output_dir.exists():
        output_dir = Path("research_analyst/evals/results")

    from research_analysis_layer.services.agent_llm_client import (
        build_agent_llm_client,
    )

    llm_client = build_agent_llm_client(settings)

    runner = AgentEvalRunner(
        llm_client=llm_client,
        golden_path=golden_path,
        output_dir=output_dir,
    )

    try:
        report = runner.compare_to_baseline(baseline_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"=== Regression Report ===")
    print(f"Baseline: {report.baseline_name}")

    if report.changes:
        print(f"\nMetric changes:")
        for metric, delta in report.changes.items():
            sign = "+" if delta > 0 else ""
            print(f"  {metric}: {sign}{delta:.1%}")

    if report.regressions:
        print(f"\n*** REGRESSIONS DETECTED ***")
        for reg in report.regressions:
            print(f"  - {reg}")
        return 1
    else:
        print(f"\nNo regressions detected.")

    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    """Export training captures."""
    from research_analysis_layer.evals.training_capture import TrainingCaptureManager

    captures_dir = Path("evals/captures")
    if not captures_dir.exists():
        captures_dir = Path("research_analyst/evals/captures")

    if not captures_dir.exists():
        print(f"Error: Captures directory not found: {captures_dir}", file=sys.stderr)
        return 1

    manager = TrainingCaptureManager(captures_dir=captures_dir)

    count = manager.export(
        output_path=args.output,
        min_confidence=args.min_confidence,
        start_date=args.start,
        end_date=args.end,
    )

    print(f"Exported {count} captures to {args.output}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    settings = Settings()

    if args.command == "run":
        return cmd_run(args, settings)
    elif args.command == "compare":
        return cmd_compare(args, settings)
    elif args.command == "export":
        return cmd_export(args, settings)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
