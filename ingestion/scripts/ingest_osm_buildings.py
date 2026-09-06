"""Load OSM building footprints (building=*) inside the Kerr County boundary,
via the Overpass API, into the `buildings` table.

Usage:
    python -m scripts.ingest_osm_buildings
"""
import sys

from lib.db import get_engine
from lib.geo import boundary_polygon, overpass_bbox, overpass_elements_to_geodataframe
from lib.langchain_tools import OverpassApiTool
from lib.upsert import upsert_geodataframe

SOURCE = "osm"


def build_query(bbox: tuple) -> str:
    south, west, north, east = bbox
    return f"""
    [out:json][timeout:180];
    (
      way["building"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    );
    out geom;
    """


def main() -> int:
    boundary_geom = boundary_polygon()
    bbox = overpass_bbox(boundary_geom)

    data = OverpassApiTool().invoke({"query": build_query(bbox)})
    gdf = overpass_elements_to_geodataframe(data.get("elements", []))
    if gdf.empty:
        print("No building elements returned by Overpass")
        return 0

    gdf = gdf[gdf.intersects(boundary_geom)].copy()
    gdf["osm_ref"] = gdf["type"] + "/" + gdf["id"].astype(str)
    gdf["tags"] = gdf["tags"].apply(dict)

    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="buildings",
        layer="building",
        source=SOURCE,
        id_field="osm_ref",
    )
    print(f"Upserted {count} rows into buildings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
