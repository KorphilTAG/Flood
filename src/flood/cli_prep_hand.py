"""CLI subcommands for HAND preparation."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from flood.contracts.validate import ContractError
from flood.ingest.hand import prep_hand
from flood.scenario import load_scenario


def run_prep_hand(args: argparse.Namespace) -> int:
    """Run HAND FIM data ingest and cube preparation."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"File not found: {args.scenario}", file=sys.stderr)
        return 2
    try:
        scenario = load_scenario(scenario_path)
        prep_hand(scenario, data_dir=args.data_dir, force=args.force)
        print(f"OK {scenario.scenario_id}")
        return 0
    except ContractError as e:
        path_str = "/".join(str(p) for p in e.path) if e.path else "<root>"
        print(f"Error at {path_str} ({e.path}): {e.message}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register 'prep hand' subcommand."""
    prep_parser = None
    if subparsers.choices and "prep" in subparsers.choices:
        prep_parser = subparsers.choices["prep"]
    else:
        prep_parser = subparsers.add_parser("prep", help="Data preparation subcommands")

    prep_sub = None
    if prep_parser._actions:
        for action in prep_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                prep_sub = action
                break

    if prep_sub is None:
        prep_sub = prep_parser.add_subparsers(dest="prep_action", required=True)

    hand_parser = prep_sub.add_parser("hand", help="Download HAND FIM artifacts and build HandCube")
    hand_parser.add_argument("scenario", help="Path to scenario JSON file")
    hand_parser.add_argument("--data-dir", default="data", help="Root data directory (default: data)")
    hand_parser.add_argument("--force", action="store_true", help="Force re-download and re-processing")
    hand_parser.set_defaults(func=run_prep_hand)
