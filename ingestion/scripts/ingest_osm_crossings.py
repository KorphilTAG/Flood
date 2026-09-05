"""Load OSM-tagged low-water crossings (ford=yes, bridge=low_water_crossing)
inside the Kerr County boundary, via the Overpass API, into the `crossings`
table. hmp_verified_name / hmp_cross_checked are left null/false -- the HMP
cross-check is a manual follow-up (PRD 6.1), not performed by this script.

Usage:
    python -m scripts.ingest_osm_crossings
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
      node["ford"="yes"]({south},{west},{north},{east});
      way["ford"="yes"]({south},{west},{north},{east});
      node["bridge"="low_water_crossing"]({south},{west},{north},{east});
      way["bridge"="low_water_crossing"]({south},{west},{north},{east});
    );
    out geom;
    """


def matched_osm_tag(row) -> str:
    tags = row["tags"]
    if tags.get("ford") == "yes":
        return "ford=yes"
    if tags.get("bridge") == "low_water_crossing":
        return "bridge=low_water_crossing"
    return ""


def main() -> int:
    boundary_geom = boundary_polygon()
    bbox = overpass_bbox(boundary_geom)

    data = OverpassApiTool().invoke({"query": build_query(bbox)})
    gdf = overpass_elements_to_geodataframe(data.get("elements", []))
    if gdf.empty:
        print("No crossing elements returned by Overpass")
        return 0

    gdf = gdf[gdf.intersects(boundary_geom)].copy()
    gdf["osm_ref"] = gdf["type"] + "/" + gdf["id"].astype(str)
    gdf["tags"] = gdf["tags"].apply(dict)

    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="crossings",
        layer="crossing",
        source=SOURCE,
        id_field="osm_ref",
        extra_fields={"osm_tag": matched_osm_tag},
    )
    print(f"Upserted {count} rows into crossings (hmp_verified_name left null)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
