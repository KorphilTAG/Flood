"""Load TxDOT road centerlines (TxDOT open data / ArcGIS Open Data portal),
clipped to the Kerr County boundary, into the `roads` table.

Usage:
    python -m scripts.ingest_txdot_roads
"""
import sys

import geopandas as gpd

from lib.db import get_engine
from lib.geo import boundary_polygon, load_kerr_county_boundary, reproject_to_4326
from lib.langchain_tools import ArcGISFeatureServerTool
from lib.upsert import upsert_geodataframe

# TxDOT Roadway Inventory (Texas Referenced Marker System) FeatureServer, published
# on the TxDOT ArcGIS Open Data portal (gis-txdot.opendata.arcgis.com).
TXDOT_ROADS_FEATURE_SERVER_URL = (
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/"
    "TxDOT_Roadway_Linear_Referencing_System/FeatureServer/0/query"
)

SOURCE = "txdot"
ID_FIELD = "OBJECTID"


def fetch_roads(boundary_geojson: dict) -> gpd.GeoDataFrame:
    data = ArcGISFeatureServerTool().invoke(
        {"url": TXDOT_ROADS_FEATURE_SERVER_URL, "boundary_geojson": boundary_geojson}
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

    gdf = fetch_roads(boundary_geojson)
    gdf = clip_to_boundary(gdf, boundary_geom)

    if ID_FIELD not in gdf.columns:
        print(f"Expected id field '{ID_FIELD}' not present in TxDOT response", file=sys.stderr)
        return 1

    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="roads",
        layer="road",
        source=SOURCE,
        id_field=ID_FIELD,
    )
    print(f"Upserted {count} rows into roads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
