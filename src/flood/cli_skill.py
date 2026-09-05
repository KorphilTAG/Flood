"""CLI subcommand for hindcast skill computation."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys
import pandas as pd

from flood.skill.hindcast import (
    compute_skill,
    summarise,
    target_check,
    update_limitations,
    write_skill,
)


def run_skill(args: argparse.Namespace) -> int:
    """Compute and display hindcast skill for a run."""
    try:
        from flood.engine.run import RunStore  # type: ignore
    except ImportError:
        print("error: engine run store not available")
        return 2

    store = RunStore(runs_dir=args.runs_dir, data_dir=args.data_dir)
    run = store.open(args.run_id)

    # Cutoffs grid: every args.cutoff_step_min minutes across the record
    step_min = int(args.cutoff_step_min)
    cur = run.record_start
    cutoffs = []
    while cur <= run.record_end:
        cutoffs.append(cur)
        cur += timedelta(minutes=step_min)

    # Horizons: parse comma-separated list
    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]

    detail_df = compute_skill(run, cutoffs, horizons)
    summary_df = summarise(detail_df)

    run_dir = getattr(run, "run_dir", Path(args.runs_dir) / args.run_id)
    write_skill(run_dir, detail_df, summary_df)

    limitations = target_check(summary_df, run.scenario)
    run_json_path = Path(run_dir) / "run.json"
    if limitations and run_json_path.exists():
        update_limitations(run_json_path, limitations)

    print(summary_df.to_string(index=False))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register 'skill' subcommand."""
    skill_parser = subparsers.add_parser("skill", help="Compute hindcast skill for a run")
    skill_parser.add_argument("run_id", help="Run ID")
    skill_parser.add_argument("--runs-dir", default="runs", help="Runs directory (default: runs)")
    skill_parser.add_argument("--data-dir", default="data", help="Data directory (default: data)")
    skill_parser.add_argument(
        "--cutoff-step-min",
        type=int,
        default=30,
        help="Cutoff step in minutes (default: 30)",
    )
    skill_parser.add_argument(
        "--horizons",
        default="0,30,60,120,240",
        help="Comma-separated horizons in minutes (default: 0,30,60,120,240)",
    )
    skill_parser.set_defaults(func=run_skill)
