"""Download and cache the Kerr County, TX boundary polygon (FIPS 48265) from
US Census TIGER/Line, so every other ingestion script clips to a real,
sourced boundary instead of a hand-typed bounding box.

Usage:
    python -m scripts.fetch_kerr_county_boundary
"""
import os
import sys

import requests

from lib.langchain_tools import CensusTigerCountyBoundaryTool

TEXAS_STATEFP = "48"
KERR_COUNTYFP = "265"

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "kerr_county_boundary.geojson"
)


def fetch_boundary(output_path: str = OUTPUT_PATH) -> str:
    county = CensusTigerCountyBoundaryTool().invoke(
        {"state_fp": TEXAS_STATEFP, "county_fp": KERR_COUNTYFP}
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
    county.to_file(output_path, driver="GeoJSON")
    return output_path


if __name__ == "__main__":
    try:
        path = fetch_boundary()
    except requests.RequestException as exc:
        print(f"Failed to download Kerr County boundary: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Kerr County boundary cached at {path}")
