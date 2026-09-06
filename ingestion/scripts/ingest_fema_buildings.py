"""Load FEMA USA Structures footprints matched to frozen model buildings.

The FEMA FeatureServer is the primary building source because it avoids the
public Overpass API and returns nationwide building polygons.  The frozen
vulnerability model is keyed to OSM building identifiers, however, so this
loader spatially matches its existing OSM centroid records to FEMA polygons at
ingest time.  The match supplies a stable model-compatible structure identity;
the original FEMA ``GlobalID`` and all FEMA attributes remain in provenance.

Usage:
    python -m scripts.ingest_fema_buildings
"""
import sys
import re
from pathlib import Path

import geopandas as gpd

from lib.db import get_engine
from lib.geo import boundary_polygon, load_kerr_county_boundary, reproject_to_4326
from lib.langchain_tools import ArcGISFeatureServerTool
from lib.upsert import upsert_geodataframe

# FEMA USA Structures, exposed as an anonymous-query ArcGIS FeatureServer by
# Esri. ``GlobalID`` is non-null and globally unique, so it is preserved with
# each matched row as FEMA provenance and makes overlapping-footprint ties
# deterministic. The upsert ID itself is the frozen model's matched OSM alias.
FEMA_BUILDINGS_FEATURE_SERVER_URL = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "USA_Structures_View/FeatureServer/0/query"
)

SOURCE = "fema_static_match"
ID_FIELD = "GlobalID"
OCCUPANCY_FIELD = "OCC_CLS"
STATIC_ID_FIELD = "static_feature_ref"
STATIC_MODEL_FEATURE_ID_FIELD = "static_model_feature_id"
DEFAULT_VULNERABILITY_PATH = (
    Path(__file__).resolve().parents[2] / "project" / "output" / "demographic_risk.geojson"
)
_LEADING_LAYER_PREFIX = re.compile(r"^[a-z_]+:")


def fetch_buildings(boundary_geojson: dict) -> gpd.GeoDataFrame:
    """Fetch FEMA structure polygons intersecting ``boundary_geojson``."""
    data = ArcGISFeatureServerTool().invoke(
        {
            "url": FEMA_BUILDINGS_FEATURE_SERVER_URL,
            "boundary_geojson": boundary_geojson,
        }
    )
    gdf = gpd.GeoDataFrame.from_features(data.get("features", []), crs="EPSG:4326")
    return reproject_to_4326(gdf)


def normalize_building_attributes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add the scenario's source-neutral ``building`` attribute.

    The existing Contract 0 structure view allow-lists ``building`` because
    that was originally the OSM tag.  FEMA instead provides ``OCC_CLS``.  Keep
    every original FEMA field for provenance and copy its occupancy class into
    the expected field rather than changing the downstream contract.
    """
    if OCCUPANCY_FIELD not in gdf.columns:
        raise ValueError(f"Expected occupancy field '{OCCUPANCY_FIELD}' not present in FEMA response")
    normalized = gdf.copy()
    normalized["building"] = normalized[OCCUPANCY_FIELD].fillna("Unknown").astype(str)
    return normalized


def static_model_feature_ref(feature_id: str) -> str:
    """Map ``building:osm:<ref>`` to the structure view's OSM-compatible ID."""
    if not feature_id:
        raise ValueError("Static vulnerability feature_id is required")
    source_id = _LEADING_LAYER_PREFIX.sub("", str(feature_id), count=1).replace(":", ".").replace("/", ".")
    if not source_id:
        raise ValueError(f"Static vulnerability feature_id {feature_id!r} has no usable source ID")
    return source_id


def load_vulnerability_points(path: Path = DEFAULT_VULNERABILITY_PATH) -> gpd.GeoDataFrame:
    """Load non-abstaining model centroid records used as identity anchors."""
    if not path.is_file():
        raise FileNotFoundError(f"Frozen vulnerability output not found: {path}")
    points = gpd.read_file(path)
    required = {"feature_id", "weight"}
    missing = required - set(points.columns)
    if missing:
        raise ValueError(f"Frozen vulnerability output is missing {sorted(missing)}")
    points = points[points["feature_id"].notna() & points["weight"].notna()].copy()
    if points.empty:
        raise ValueError("Frozen vulnerability output has no weighted footprints")
    if not points.geometry.geom_type.isin(["Point"]).all():
        raise ValueError("Frozen vulnerability output must contain Point centroids")
    return reproject_to_4326(points)


def match_buildings_to_vulnerability(
    buildings: gpd.GeoDataFrame, vulnerability_points: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Return one FEMA polygon per frozen model footprint that it contains.

    A point can occasionally fall in overlapping FEMA polygons.  Choosing the
    lexically smallest ``GlobalID`` makes that exceptional tie deterministic;
    one FEMA polygon may intentionally back several static OSM footprints.
    """
    if buildings.empty:
        return buildings.copy()
    if ID_FIELD not in buildings.columns:
        raise ValueError(f"Expected id field '{ID_FIELD}' not present in FEMA response")

    points = reproject_to_4326(vulnerability_points)[["feature_id", "geometry"]].copy()
    candidates = buildings[[ID_FIELD, "geometry"]].copy()
    matches = gpd.sjoin(points, candidates, how="inner", predicate="within")
    if matches.empty:
        return buildings.iloc[0:0].copy()

    pairs = (
        matches[["feature_id", ID_FIELD]]
        .sort_values(["feature_id", ID_FIELD])
        .drop_duplicates(subset="feature_id", keep="first")
    )
    matched = buildings.merge(pairs, on=ID_FIELD, how="inner")
    matched[STATIC_MODEL_FEATURE_ID_FIELD] = matched["feature_id"]
    matched[STATIC_ID_FIELD] = matched["feature_id"].map(static_model_feature_ref)
    matched = matched.drop(columns=["feature_id"])
    return gpd.GeoDataFrame(matched, geometry="geometry", crs=buildings.crs)


def clip_to_boundary(gdf: gpd.GeoDataFrame, boundary) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    return gdf[gdf.intersects(boundary)].copy()


def repair_invalid_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repair malformed source polygons before they reach PostGIS.

    FEMA's source includes occasional invalid footprints (for example, nested
    shells).  ``make_valid`` preserves the represented footprint while turning
    it into a valid Polygon/MultiPolygon, which keeps the ingestion verifier
    and the scenario's structure view usable on every run.
    """
    if gdf.empty:
        return gdf
    invalid = ~gdf.geometry.is_valid
    if not invalid.any():
        return gdf
    repaired = gdf.copy()
    repaired.loc[invalid, "geometry"] = repaired.loc[invalid, "geometry"].make_valid()
    return repaired


def main() -> int:
    boundary_gdf = load_kerr_county_boundary()
    boundary_geojson = boundary_gdf.geometry.iloc[0].__geo_interface__
    boundary_geom = boundary_polygon()

    gdf = fetch_buildings(boundary_geojson)
    gdf = clip_to_boundary(gdf, boundary_geom)
    gdf = repair_invalid_geometries(gdf)

    if ID_FIELD not in gdf.columns:
        print(f"Expected id field '{ID_FIELD}' not present in FEMA response", file=sys.stderr)
        return 1

    if gdf[ID_FIELD].isna().any() or (gdf[ID_FIELD].astype(str).str.strip() == "").any():
        print(f"FEMA response contains a missing '{ID_FIELD}'", file=sys.stderr)
        return 1

    try:
        gdf = match_buildings_to_vulnerability(gdf, load_vulnerability_points())
    except (FileNotFoundError, ValueError) as err:
        print(f"Cannot build FEMA/static identity matches: {err}", file=sys.stderr)
        return 1
    if gdf.empty:
        print("No FEMA building footprint contains a frozen vulnerability centroid", file=sys.stderr)
        return 1

    gdf = normalize_building_attributes(gdf)
    count = upsert_geodataframe(
        engine=get_engine(),
        gdf=gdf,
        table="buildings",
        layer="building",
        source=SOURCE,
        id_field=STATIC_ID_FIELD,
    )
    print(f"Upserted {count} FEMA/static identity-matched rows into buildings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
