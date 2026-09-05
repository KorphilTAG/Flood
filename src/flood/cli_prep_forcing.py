"""CLI subcommand for preparing forcing data: flood prep forcing."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from flood.ingest.nwm import ingest_nwm
from flood.ingest.usgs import ingest_usgs
from flood.scenario import load_scenario


def run_prep_forcing(args: argparse.Namespace) -> int:
    """Execute forcing preparation for a scenario."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {args.scenario}", file=sys.stderr)
        return 2

    try:
        scenario = load_scenario(scenario_path)
    except Exception as e:
        print(f"Error loading scenario: {e}", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir)

    if not args.skip_nwm:
        try:
            ingest_nwm(scenario, data_dir, keep_raw=args.keep_raw)
        except Exception as e:
            print(f"Error ingesting NWM forcing: {e}", file=sys.stderr)
            return 1

    if not args.skip_usgs:
        try:
            ingest_usgs(scenario, data_dir)
        except Exception as e:
            print(f"Error ingesting USGS forcing: {e}", file=sys.stderr)
            return 1

    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register 'prep forcing' subcommand into the main CLI."""
    # Retrieve existing 'prep' subparser or create it if not yet registered
    prep_parser = None
    if subparsers.choices and "prep" in subparsers.choices:
        prep_parser = subparsers.choices["prep"]
    else:
        prep_parser = subparsers.add_parser("prep", help="Data preparation subcommands")

    # Find or create prep subparsers
    prep_sub = None
    if prep_parser._actions:
        for action in prep_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                prep_sub = action
                break

    if prep_sub is None:
        prep_sub = prep_parser.add_subparsers(dest="prep_action", required=True)

    forcing_parser = prep_sub.add_parser("forcing", help="Prepare NWM and USGS forcing data")
    forcing_parser.add_argument("scenario", help="Path to scenario JSON file")
    forcing_parser.add_argument("--data-dir", default="data", help="Root directory for data (default: data)")
    forcing_parser.add_argument("--keep-raw", action="store_true", default=False, help="Keep raw NWM NetCDF files")
    forcing_parser.add_argument("--skip-nwm", action="store_true", default=False, help="Skip NWM ingest")
    forcing_parser.add_argument("--skip-usgs", action="store_true", default=False, help="Skip USGS ingest")
    forcing_parser.set_defaults(func=run_prep_forcing)
