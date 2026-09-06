"""CLI subcommands for managing runs: flood run create, state, list."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from flood.engine.run import Run, RunStore
from flood.scenario import load_scenario


def run_create(args: argparse.Namespace) -> int:
    """Create a new run from a scenario file and optional forcing overrides."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {args.scenario}", file=sys.stderr)
        return 2

    try:
        scenario = load_scenario(scenario_path)
    except Exception as e:
        print(f"Error loading scenario: {e}", file=sys.stderr)
        return 2

    overrides = None
    if args.override:
        ov_path = Path(args.override)
        if ov_path.exists():
            try:
                overrides = json.loads(ov_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Error reading override JSON file: {e}", file=sys.stderr)
                return 2
        else:
            try:
                overrides = json.loads(args.override)
            except Exception as e:
                print(f"Error parsing override JSON string: {e}", file=sys.stderr)
                return 2

    runs_dir = Path(args.runs_dir)
    data_dir = Path(args.data_dir)

    try:
        run = Run.create(
            scenario=scenario,
            mode=args.mode,
            overrides=overrides,
            runs_dir=runs_dir,
            data_dir=data_dir,
            engine_version=args.engine_version,
        )
        print(run.run_id)
        return 0
    except Exception as e:
        print(f"Error creating run: {e}", file=sys.stderr)
        return 1


def run_state(args: argparse.Namespace) -> int:
    """Query state for a run at (p, t), printing state response JSON."""
    runs_dir = Path(args.runs_dir)
    data_dir = Path(args.data_dir)

    store = RunStore(runs_dir, data_dir)
    if not store.exists(args.run_id):
        print(f"Error: Run not found: {args.run_id}", file=sys.stderr)
        return 2

    try:
        run = store.get(args.run_id)
        _, response = run.state(args.p, args.t, write=args.write)
        print(json.dumps(response, indent=2))
        return 0
    except Exception as e:
        print(f"Error executing run state: {e}", file=sys.stderr)
        return 1


def run_list(args: argparse.Namespace) -> int:
    """List all run manifests in runs-dir."""
    runs_dir = Path(args.runs_dir)
    data_dir = Path(args.data_dir)

    store = RunStore(runs_dir, data_dir)
    manifests = store.list()
    print(json.dumps(manifests, indent=2))
    return 0


def run_prewarm(args: argparse.Namespace) -> int:
    """Precompute and write products for a grid of (p, t) pairs so the demo serves from disk."""
    from datetime import timedelta
    from flood.engine.run import RunStore
    from flood.timegrid import parse_iso, snap_p, to_iso

    store = RunStore(runs_dir=args.runs_dir, data_dir=args.data_dir)
    run = store.get(args.run_id)
    horizons = [int(h) for h in str(args.horizons).split(",") if h.strip()]
    p = snap_p(parse_iso(args.p_from))
    p_to = parse_iso(args.p_to)
    n = 0
    while p <= p_to:
        for h in horizons:
            t = p + timedelta(minutes=h)
            if t > run.record_end:
                continue
            _, resp = run.state(p, t, write=True)
            n += 1
            print(f"{to_iso(p)} +{h:>3} min  cache={resp['cache']:<11} total={resp['compute_ms']['total']} ms", flush=True)
        if args.tte:
            run.tte(p, write=True)
            print(f"{to_iso(p)} time_to_exceedance written", flush=True)
        p += timedelta(minutes=int(args.p_step_min))
    if args.hindsight_from and args.hindsight_to:
        t = snap_p(parse_iso(args.hindsight_from))
        t_to = parse_iso(args.hindsight_to)
        while t <= t_to:
            _, resp = run.state("hindsight", t, write=True)
            n += 1
            print(f"hindsight {to_iso(t)}  cache={resp['cache']:<11} total={resp['compute_ms']['total']} ms", flush=True)
            t += timedelta(minutes=int(args.t_step_min))
    print(f"prewarmed {n} states for {run.run_id}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register 'run' subcommands."""
    run_parser = subparsers.add_parser("run", help="Manage and execute runs")
    run_sub = run_parser.add_subparsers(dest="run_action", required=True)

    # create
    create_parser = run_sub.add_parser("create", help="Create a new run")
    create_parser.add_argument("scenario", help="Path to scenario JSON file")
    create_parser.add_argument("--mode", choices=["replay", "live"], default="replay", help="Run mode (default: replay)")
    create_parser.add_argument("--override", help="Path to override JSON file or JSON string")
    create_parser.add_argument("--runs-dir", default="runs", help="Runs directory (default: runs)")
    create_parser.add_argument("--data-dir", default="data", help="Data directory (default: data)")
    create_parser.add_argument("--engine-version", default="0.1.0", help="Engine version (default: 0.1.0)")
    create_parser.set_defaults(func=run_create)

    # state
    state_parser = run_sub.add_parser("state", help="Query engine state for (p, t)")
    state_parser.add_argument("run_id", help="Run ID")
    state_parser.add_argument("--p", required=True, help="Cutoff timestamp ISO or 'hindsight'")
    state_parser.add_argument("--t", required=True, help="Target timestamp ISO")
    state_parser.add_argument("--write", action="store_true", default=False, help="Write products to disk")
    state_parser.add_argument("--runs-dir", default="runs", help="Runs directory (default: runs)")
    state_parser.add_argument("--data-dir", default="data", help="Data directory (default: data)")
    state_parser.set_defaults(func=run_state)

    # list
    list_parser = run_sub.add_parser("list", help="List runs")
    list_parser.add_argument("--runs-dir", default="runs", help="Runs directory (default: runs)")
    list_parser.add_argument("--data-dir", default="data", help="Data directory (default: data)")
    list_parser.set_defaults(func=run_list)

    pre = run_sub.add_parser("prewarm", help="Precompute products for a grid of (p, t) so the demo serves from disk")
    pre.add_argument("run_id")
    pre.add_argument("--p-from", required=True, help="first cutoff, contract ISO")
    pre.add_argument("--p-to", required=True, help="last cutoff, contract ISO")
    pre.add_argument("--p-step-min", default=5, type=int)
    pre.add_argument("--horizons", default="0,30,60,120", help="comma-separated minutes")
    pre.add_argument("--hindsight-from", default=None)
    pre.add_argument("--hindsight-to", default=None)
    pre.add_argument("--t-step-min", default=15, type=int)
    pre.add_argument("--tte", action="store_true", help="also write time_to_exceedance per cutoff (slow: one mapping per 5-minute step)")
    pre.add_argument("--runs-dir", default="runs")
    pre.add_argument("--data-dir", default="data")
    pre.set_defaults(func=run_prewarm)
