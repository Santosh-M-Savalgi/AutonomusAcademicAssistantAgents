"""Command-line entry point for the Phase 4.6 evaluation runner."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from apps.api.config import Settings
from packages.evalkit.suite import benchmark_definitions, run_phase46


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AAA v3 Phase 4.6 evaluation runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run the real-model evaluation")
    run.add_argument("--suite", choices=("phase4.6",), default="phase4.6")
    run.add_argument(
        "--benchmark",
        choices=tuple(definition.key for definition in benchmark_definitions()),
        help="run one benchmark for debugging instead of the complete suite",
    )
    run.add_argument("--output-dir", type=Path, default=Path("docs"))
    run.add_argument("--provider", choices=("llama_cpp",))
    run.add_argument("--base-url")
    run.add_argument("--model-id")
    run.add_argument("--artifact-path")
    run.add_argument("--lock-path")
    run.add_argument(
        "--diagnostic-topics",
        action="store_true",
        help="emit per-example syllabus topics to stdout for diagnostic runs",
    )
    run.add_argument(
        "--diagnostic-tags",
        action="store_true",
        help="emit per-example question tags to stdout for diagnostic runs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.diagnostic_tags and args.benchmark not in {"question-tagging", "question-tagging-v3"}:
        parser.error(
            "--diagnostic-tags requires --benchmark question-tagging or "
            "question-tagging-v3"
        )
    settings = Settings()
    updates = {
        key: value
        for key, value in {
            "model_provider": args.provider,
            "model_base_url": args.base_url,
            "model_id": args.model_id,
            "model_artifact_path": args.artifact_path,
            "model_lock_path": args.lock_path,
        }.items()
        if value is not None
    }
    settings = settings.model_copy(update=updates)
    report, paths = asyncio.run(
        run_phase46(
            settings,
            benchmark_key=args.benchmark,
            output_dir=args.output_dir,
            diagnostic_topics=args.diagnostic_topics,
            diagnostic_tags=args.diagnostic_tags,
        )
    )
    print(f"decision={report.decision}")
    print(f"json={paths[0]}")
    print(f"markdown={paths[1]}")
    return 0 if report.decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
