"""CLI subcommands for flood mapping."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd

from flood.engine.cube import HandCube
from flood.engine.ensemble import reduce_members
from flood.engine.mapping import map_member
from flood.products.raster import write_depth_cog


def run_map(args: argparse.Namespace) -> int:
    """Run HAND mapping from discharge CSV to COG raster."""
    cube_dir = Path(args.cube)
    if not (cube_dir / "meta.json").exists():
        candidates = list(cube_dir.glob("**/meta.json"))
        if candidates:
            cube_dir = candidates[0].parent
        else:
            print(f"Error: No valid cube found at {args.cube}", file=sys.stderr)
            return 2

    q_path = Path(args.q)
    if not q_path.exists():
        print(f"Error: Discharge CSV not found: {args.q}", file=sys.stderr)
        return 2

    out_path = Path(args.out)

    cube = HandCube.load(cube_dir)
    df = pd.read_csv(q_path)

    if "feature_id" not in df.columns or "q_mid_cms" not in df.columns:
        print("Error: CSV must contain 'feature_id' and 'q_mid_cms' columns", file=sys.stderr)
        return 2

    if "q_low_cms" not in df.columns:
        df["q_low_cms"] = df["q_mid_cms"]
    if "q_high_cms" not in df.columns:
        df["q_high_cms"] = df["q_mid_cms"]

    q_mid = dict(zip(df["feature_id"].astype(int), df["q_mid_cms"].astype(float)))
    q_low = dict(zip(df["feature_id"].astype(int), df["q_low_cms"].astype(float)))
    q_high = dict(zip(df["feature_id"].astype(int), df["q_high_cms"].astype(float)))

    mid_mf = map_member(cube, q_mid, with_velocity=True)
    low_mf = map_member(cube, q_low, with_velocity=False)
    high_mf = map_member(cube, q_high, with_velocity=False)

    state = reduce_members(low_mf, mid_mf, high_mf)
    write_depth_cog(out_path, cube.grid, state)
    print(f"Wrote {out_path}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register 'map' subcommand."""
    map_parser = subparsers.add_parser("map", help="Map reach discharges to flood raster COG")
    map_parser.add_argument("--cube", required=True, help="Path to cube directory")
    map_parser.add_argument("--q", required=True, help="Path to discharge CSV")
    map_parser.add_argument("--out", required=True, help="Path to output GeoTIFF")
    map_parser.set_defaults(func=run_map)
