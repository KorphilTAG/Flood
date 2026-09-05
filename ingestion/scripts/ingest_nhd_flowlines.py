"""Load USGS NHD flowlines for HUC8 12100201 (matching docs/README.md's HAND
HUC8) into the `river_network` table.

Usage:
    python -m scripts.ingest_nhd_flowlines
"""
import sys

import geopandas as gpd

from lib.db import get_engine
from lib.geo import boundary_polygon, load_kerr_county_boundary, reproject_to_4326
from lib.langchain_tools import ArcGISFeatureServerTool
from lib.upsert import upsert_geodataframe

# USGS National Map / NHDPlus HR MapServer, NHDFlowline layer (id 3).
NHD_FLOWLINE_FEATURE_SERVER_URL = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query"
)

HUC8 = "12100201"
SOURCE = "nhd"
ID_FIELD = "NHDPlusID"


def fetch_flowlines(boundary_geojson: dict) -> gpd.GeoDataFrame:
    where = f"REACHCODE LIKE '{HUC8}%'"
    data = ArcGISFeatureServerTool().invoke(
        {"url": NHD_FLOWLINE_FEATURE_SERVER_URL, "boundary_geojson": boundary_geojson, "where": where}
    )
    gdf = gpd.GeoDataFrame.from_features(data.get("features", []), crs="EPSG:4326")
    return reproject_to_4326(gdf)


def clip_to_boundary(gdf: gpd.GeoDataFrame, boundary) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    return gdf[gdf.intersects(boundary)].copy()


def main() -> int:
    boundary_gdf = load_kerr_county_boundary()
    boundary_geojson = boundary_gdf.geometry.iloc[0].__geo_interface__
    boundary_geom = boundary_polygon()

    gdf = fetch_flowlines(boundary_geojson)
    gdf = clip_to_boundary(gdf, boundary_geom)

    if ID_FIELD not in gdf.columns:
        print(f"Expected id field '{ID_FIELD}' not present in NHD response", file=sys.stderr)
        return 1

    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="river_network",
        layer="river",
        source=SOURCE,
        id_field=ID_FIELD,
    )
    print(f"Upserted {count} rows into river_network")
    return 0


if __name__ == "__main__":
    sys.exit(main())
