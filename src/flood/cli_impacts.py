"""CLI subcommands for Contract 2 impact extraction."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys

from flood.engine.run import Run
from flood.impact.extractor import (
    PROJECTION_OFFSETS_MIN,
    ImpactExtractionError,
    ImpactExtractor,
    impact_path,
    write_impact_json,
)
from flood.impact.postgis import ExposureConfigError, ExposureDataError, PostGISExposureStore, resolve_dsn
from flood.contracts.validate import ContractError
from flood.interfaces import TimeGridError
from flood.scenario import load_scenario


def _materialize(run: Run, p, t) -> Path:
    """Write the (p, t) depth COG if it is not already on disk, and return its path."""
    run.state(p if p is not None else "hindsight", t, write=True)
    return run.product_path("raster", p if p is not None else "hindsight", t)


def run_impacts_extract(args: argparse.Namespace) -> int:
    """Resolve the engine query, materialize its products, and write Contract 2."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario not found: {scenario_path}", file=sys.stderr)
        return 2
    run_dir = Path(args.run_dir)
    if not (run_dir / "run.json").is_file():
        print(f"Error: Run manifest not found: {run_dir / 'run.json'}", file=sys.stderr)
        return 2

    try:
        scenario = load_scenario(scenario_path)
        run = Run.open(run_dir, args.data_dir or run_dir.parent.parent / "data")
        resolved = run.resolve(args.p, args.t)

        current = _materialize(run, resolved.p, resolved.t)
        reaches = run.product_path(
            "reaches", resolved.p if resolved.mode != "hindsight" else "hindsight", resolved.t
        )

        # Same-`p` projections, but only for targets Contract 1 still permits.
        projections: dict = {}
        for offset in PROJECTION_OFFSETS_MIN:
            t_future = resolved.t + timedelta(minutes=offset)
            try:
                run.resolve(args.p, t_future)
            except TimeGridError:
                continue  # Outside the record or horizon: omit, never substitute.
            projections[t_future] = _materialize(run, resolved.p, t_future)

        store = PostGISExposureStore(resolve_dsn(args.postgis_dsn))
        extractor = ImpactExtractor(scenario, store)
        payload = extractor.extract(
            run_id=run.run_id,
            p=resolved.p,
            t=resolved.t,
            current_cog=current,
            projection_cogs=projections,
            reaches_parquet=reaches if reaches.exists() else None,
        )
        out_path = write_impact_json(impact_path(run_dir, resolved.p, resolved.t), payload)
    except (ExposureConfigError, ExposureDataError) as err:
        print(f"Error: exposure configuration: {err}", file=sys.stderr)
        return 2
    except ImpactExtractionError as err:
        print(f"Error: missing or inconsistent engine product: {err}", file=sys.stderr)
        return 2
    except TimeGridError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    except ContractError as err:
        print(f"Error: written document violates Contract 2: {err}", file=sys.stderr)
        return 2

    print(out_path)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'impacts' subcommand group."""
    impacts = subparsers.add_parser("impacts", help="Contract 2 impact products")
    impacts_sub = impacts.add_subparsers(dest="impacts_command", required=True)
    extract = impacts_sub.add_parser("extract", help="Extract Contract 2 facts for a (p, t) query")
    extract.add_argument("--scenario", required=True, help="Path to the scenario JSON")
    extract.add_argument("--run-dir", required=True, help="Path to the run directory")
    extract.add_argument("--p", required=True, help="Knowledge cutoff (ISO UTC) or 'hindsight'")
    extract.add_argument("--t", required=True, help="Target time (ISO UTC)")
    extract.add_argument("--postgis-dsn", default=None, help="PostGIS DSN; else FLOOD_POSTGIS_DSN")
    extract.add_argument("--data-dir", default=None, help="Data directory for the run")
    extract.set_defaults(func=run_impacts_extract)
