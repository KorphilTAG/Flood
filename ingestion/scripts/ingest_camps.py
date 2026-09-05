"""Generic, source-agnostic loader for the `camps` table.

Accepts any local vector file GeoPandas can read (GeoJSON, Shapefile, ...)
and loads it into `camps`, assigning feature_id as
"camp:<source>:<source_id-or-row-index>".

This script ships and is tested only against the synthetic fixture at
tests/fixtures/sample_camps.geojson (see tests/test_ingest_camps.py). Real
camp footprint acquisition (KCAD parcel search, TNRIS StratMap request,
ReportAll/Regrid purchase, or aerial-imagery tracing) is manual and out of
scope for this feature -- see ingestion/README.md's follow-up checklist.

Usage:
    python -m scripts.ingest_camps --input <path to GeoJSON/Shapefile> [--source <name>] [--id-field <column>]
"""
import argparse
import sys

import geopandas as gpd

from lib.db import get_engine
from lib.geo import reproject_to_4326
from lib.upsert import upsert_geodataframe

LAYER = "camp"


def load_camps_file(input_path: str, source: str, id_field: str | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(input_path)
    gdf = reproject_to_4326(gdf)

    if id_field and id_field in gdf.columns:
        gdf["_camp_source_id"] = gdf[id_field].astype(str)
    else:
        gdf["_camp_source_id"] = gdf.index.astype(str)

    return gdf


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load a local vector file into camps")
    parser.add_argument("--input", required=True, help="Path to a GeoJSON/Shapefile of camp footprints")
    parser.add_argument("--source", default="manual", help="Source label recorded on each row (default: manual)")
    parser.add_argument(
        "--id-field",
        default=None,
        help="Column to use as source_id; falls back to the row index if unset or absent",
    )
    args = parser.parse_args(argv)

    gdf = load_camps_file(args.input, args.source, args.id_field)

    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="camps",
        layer=LAYER,
        source=args.source,
        id_field="_camp_source_id",
    )
    print(f"Upserted {count} rows into camps from {args.input}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
