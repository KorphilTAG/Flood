"""Manual, opt-in smoke test that calls every real external data source used
by the ingestion scripts and reports whether each returns a non-empty,
well-formed result. Fetch-only -- does not write to PostGIS, so it can run
without a reachable database.

This is a standalone script, not a pytest test module, so it is never
collected or run by a default `pytest` invocation. Requires network access.

Usage:
    python -m scripts.live_smoke_test
"""
import sys

from lib.geo import boundary_polygon, overpass_bbox
from lib.langchain_tools import (
    ArcGISFeatureServerTool,
    CensusTigerCountyBoundaryTool,
    OverpassApiTool,
)
from scripts.ingest_nhd_flowlines import HUC8, NHD_FLOWLINE_FEATURE_SERVER_URL
from scripts.ingest_osm_buildings import build_query as build_buildings_query
from scripts.ingest_osm_crossings import build_query as build_crossings_query
from scripts.ingest_txdot_roads import TXDOT_ROADS_FEATURE_SERVER_URL

TEXAS_STATEFP = "48"
KERR_COUNTYFP = "265"


def check_tiger_boundary() -> tuple:
    gdf = CensusTigerCountyBoundaryTool().invoke(
        {"state_fp": TEXAS_STATEFP, "county_fp": KERR_COUNTYFP}
    )
    ok = len(gdf) > 0 and gdf.geometry.iloc[0] is not None
    return ok, f"{len(gdf)} county polygon(s)", gdf


def check_txdot_roads(boundary_geojson: dict) -> tuple:
    data = ArcGISFeatureServerTool().invoke(
        {"url": TXDOT_ROADS_FEATURE_SERVER_URL, "boundary_geojson": boundary_geojson}
    )
    features = data.get("features", [])
    return len(features) > 0, f"{len(features)} feature(s)", None


def check_nhd_flowlines(boundary_geojson: dict) -> tuple:
    data = ArcGISFeatureServerTool().invoke(
        {
            "url": NHD_FLOWLINE_FEATURE_SERVER_URL,
            "boundary_geojson": boundary_geojson,
            "where": f"REACHCODE LIKE '{HUC8}%'",
        }
    )
    features = data.get("features", [])
    return len(features) > 0, f"{len(features)} feature(s)", None


def check_osm_buildings(bbox: tuple) -> tuple:
    data = OverpassApiTool().invoke({"query": build_buildings_query(bbox)})
    elements = data.get("elements", [])
    return len(elements) > 0, f"{len(elements)} element(s)", None


def check_osm_crossings(bbox: tuple) -> tuple:
    data = OverpassApiTool().invoke({"query": build_crossings_query(bbox)})
    if "elements" not in data:
        return False, "response missing 'elements' key", None
    # Kerr County may legitimately have zero tagged low-water crossings, so
    # this check is "well-formed", not "non-empty".
    return True, f"{len(data['elements'])} element(s) (zero is a valid result)", None


def main() -> int:
    results = []
    boundary_geojson = None
    bbox = None

    print("Live smoke test -- calling real external endpoints (network required)\n")

    try:
        ok, detail, boundary_gdf = check_tiger_boundary()
        results.append(("Census TIGER boundary", ok, detail))
        if ok:
            boundary_geojson = boundary_gdf.geometry.iloc[0].__geo_interface__
            bbox = overpass_bbox(boundary_gdf.geometry.union_all())
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the run
        results.append(("Census TIGER boundary", False, f"error: {exc}"))

    if boundary_geojson is not None:
        for label, check in (
            ("TxDOT ArcGIS FeatureServer (roads)", lambda: check_txdot_roads(boundary_geojson)),
            ("USGS NHDPlus HR MapServer (flowlines)", lambda: check_nhd_flowlines(boundary_geojson)),
        ):
            try:
                ok, detail, _ = check()
                results.append((label, ok, detail))
            except Exception as exc:  # noqa: BLE001
                results.append((label, False, f"error: {exc}"))
    else:
        results.append(("TxDOT ArcGIS FeatureServer (roads)", False, "skipped: no boundary"))
        results.append(("USGS NHDPlus HR MapServer (flowlines)", False, "skipped: no boundary"))

    if bbox is not None:
        for label, check in (
            ("Overpass API (buildings)", lambda: check_osm_buildings(bbox)),
            ("Overpass API (crossings)", lambda: check_osm_crossings(bbox)),
        ):
            try:
                ok, detail, _ = check()
                results.append((label, ok, detail))
            except Exception as exc:  # noqa: BLE001
                results.append((label, False, f"error: {exc}"))
    else:
        results.append(("Overpass API (buildings)", False, "skipped: no boundary"))
        results.append(("Overpass API (crossings)", False, "skipped: no boundary"))

    any_failed = False
    for label, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            any_failed = True
        print(f"[{status}] {label}: {detail}")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
