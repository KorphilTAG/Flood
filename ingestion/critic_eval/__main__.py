"""`python -m critic_eval run` -- the real, end-to-end, human-operated
pre-demo check (spec.md In scope, item 1; Approach, "Report, not gate, by
default").

Requires a real built AAR corpus and a real `OPENAI_API_KEY` to produce
meaningful scores: both the critic generation step (`critic.service.
run_critique`) and the RAGAS judge step call OpenAI for real. This is a
genuine departure from every other run path in `ingestion/` -- see
`ingestion/README.md`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .dataset import load_sample_plans
from .mapping import to_ragas_records
from .ragas_eval import evaluate_records
from .report import format_report, write_report_json
from .runner import run_critic_on_samples
from .settings import Settings


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m critic_eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run the fixed sample set through the real critic and RAGAS judge."
    )
    run_parser.add_argument(
        "--sample-path",
        default=None,
        help="Path to the sample-plan fixture (default: settings.sample_path).",
    )
    run_parser.add_argument(
        "--fail-under-faithfulness",
        type=float,
        default=None,
        help="Exit non-zero if any sample's faithfulness score falls below this value. "
        "Opt-in only -- omitted, the CLI always exits 0 (report-only).",
    )
    run_parser.add_argument(
        "--fail-under-context-precision",
        type=float,
        default=None,
        help="Exit non-zero if any sample's context-precision score falls below this "
        "value. Opt-in only -- omitted, the CLI always exits 0 (report-only).",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    sample_path = args.sample_path or settings.sample_path
    samples = load_sample_plans(sample_path)

    sample_runs = run_critic_on_samples(samples, settings)
    records = to_ragas_records(sample_runs)
    scores = evaluate_records(records, settings)

    report_text = format_report(sample_runs, records, scores, settings)
    print(report_text)

    settings.report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = settings.report_dir / f"citation-quality-eval-{timestamp}.json"
    write_report_json(sample_runs, records, scores, report_path)
    print(f"Wrote JSON report to {report_path}")

    if args.fail_under_faithfulness is None and args.fail_under_context_precision is None:
        return 0

    failed = False
    for score in scores:
        faithfulness = score.get("faithfulness")
        context_precision = score.get("context_precision")
        if args.fail_under_faithfulness is not None and (
            faithfulness is None or faithfulness < args.fail_under_faithfulness
        ):
            failed = True
        if args.fail_under_context_precision is not None and (
            context_precision is None or context_precision < args.fail_under_context_precision
        ):
            failed = True
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
