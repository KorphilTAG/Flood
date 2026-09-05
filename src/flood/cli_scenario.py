"""Scenario CLI subcommands."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from flood.contracts.validate import ContractError
from flood.scenario import load_scenario


def run_validate(args: argparse.Namespace) -> int:
    """Validate a scenario file."""
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {args.path}", file=sys.stderr)
        return 2
    try:
        scenario = load_scenario(path)
        print(f"OK {scenario.scenario_id}")
        return 0
    except ContractError as e:
        path_str = "/".join(str(p) for p in e.path) if e.path else "<root>"
        print(f"Error at {path_str} ({e.path}): {e.message}")
        return 2
    except Exception as e:
        print(f"Error: {e}")
        return 2


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register scenario subcommand and its subparsers."""
    scenario_parser = subparsers.add_parser("scenario", help="Scenario subcommands")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_action", required=True)

    validate_parser = scenario_sub.add_parser("validate", help="Validate scenario JSON")
    validate_parser.add_argument("path", help="Path to scenario JSON file")
    validate_parser.set_defaults(func=run_validate)
