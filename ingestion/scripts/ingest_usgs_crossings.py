"""Load USGS road--stream crossing candidates into ``crossings``.

The USGS dataset models likely road--stream intersections from TIGER 2020 road
lines and NHD High Resolution flowlines.  It is a useful operational fallback
for the blocked Overpass endpoint, but it must not be presented as a verified
low-water-crossing inventory: ``crossing_type`` distinguishes bridge records
from unclassified road intersections and HMP verification remains manual.

Usage:
    python -m scripts.ingest_usgs_crossings
"""
import sys

import geopandas as gpd

from lib.db import get_engine
from lib.geo import boundary_polygon, load_kerr_county_boundary, reproject_to_4326
from lib.langchain_tools import ArcGISFeatureServerTool
from lib.upsert import upsert_geodataframe

# USGS Database of Stream Crossings in the United States, layer 0 (sites).
USGS_CROSSINGS_FEATURE_SERVER_URL = (
    "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
    "stream_crossings/FeatureServer/0/query"
)

SOURCE = "usgs_stream_crossings"
ID_FIELD = "stream_crossing_id"
ROAD_NAME_FIELD = "tiger2020_feature_names"


def fetch_crossings(boundary_geojson: dict) -> gpd.GeoDataFrame:
    """Fetch USGS crossing points intersecting ``boundary_geojson``."""
    data = ArcGISFeatureServerTool().invoke(
        {
            "url": USGS_CROSSINGS_FEATURE_SERVER_URL,
            "boundary_geojson": boundary_geojson,
        }
    )
    gdf = gpd.GeoDataFrame.from_features(data.get("features", []), crs="EPSG:4326")
    return reproject_to_4326(gdf)


def normalize_crossing_attributes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add the source-neutral road ``name`` consumed by the exposure view."""
    if ROAD_NAME_FIELD not in gdf.columns:
        raise ValueError(f"Expected road-name field '{ROAD_NAME_FIELD}' not present in USGS response")
    normalized = gdf.copy()
    normalized["name"] = normalized[ROAD_NAME_FIELD]
    return normalized


def clip_to_boundary(gdf: gpd.GeoDataFrame, boundary) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    return gdf[gdf.intersects(boundary)].copy()


def main() -> int:
    boundary_gdf = load_kerr_county_boundary()
    boundary_geojson = boundary_gdf.geometry.iloc[0].__geo_interface__
    boundary_geom = boundary_polygon()

    gdf = fetch_crossings(boundary_geojson)
    gdf = clip_to_boundary(gdf, boundary_geom)

    if ID_FIELD not in gdf.columns:
        print(f"Expected id field '{ID_FIELD}' not present in USGS response", file=sys.stderr)
        return 1

    if gdf[ID_FIELD].isna().any():
        print(f"USGS response contains a missing '{ID_FIELD}'", file=sys.stderr)
        return 1

    gdf = normalize_crossing_attributes(gdf)
    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="crossings",
        layer="crossing",
        source=SOURCE,
        id_field=ID_FIELD,
    )
    print(f"Upserted {count} USGS road--stream crossing rows into crossings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
