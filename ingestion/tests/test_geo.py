import json
import os

import geopandas as gpd
import pytest
from shapely.geometry import Point

from lib.geo import (
    load_kerr_county_boundary,
    make_feature_id,
    overpass_element_to_geometry,
    overpass_elements_to_geodataframe,
    reproject_to_4326,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_make_feature_id_basic():
    assert make_feature_id("road", "txdot", "1023481") == "road:txdot:1023481"
    assert make_feature_id("crossing", "osm", "way/38291029") == "crossing:osm:way/38291029"
    assert make_feature_id("river", "nhd", 12345600001234) == "river:nhd:12345600001234"


@pytest.mark.parametrize("layer,source,source_id", [
    (None, "osm", "1"),
    ("road", None, "1"),
    ("road", "osm", None),
    ("road", "osm", ""),
])
def test_make_feature_id_requires_all_parts(layer, source, source_id):
    with pytest.raises(ValueError):
        make_feature_id(layer, source, source_id)


def test_reproject_to_4326_from_web_mercator():
    # A point in EPSG:3857 (Web Mercator) near Kerrville, TX.
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(-11055000, 3512000)], crs="EPSG:3857")
    reprojected = reproject_to_4326(gdf)

    assert reprojected.crs.to_epsg() == 4326
    lon, lat = reprojected.geometry.iloc[0].x, reprojected.geometry.iloc[0].y
    # Roughly Kerr County, TX (~-99.3, 30.05); just sanity-check the reprojection
    # landed in a plausible lon/lat range rather than staying in meters.
    assert -100 < lon < -98
    assert 29 < lat < 31


def test_reproject_to_4326_noop_when_already_4326():
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(-99.3, 30.05)], crs="EPSG:4326")
    reprojected = reproject_to_4326(gdf)
    assert reprojected.crs.to_epsg() == 4326
    assert reprojected.geometry.iloc[0].x == pytest.approx(-99.3)


def test_reproject_to_4326_assumes_4326_when_crs_missing():
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(-99.3, 30.05)])
    reprojected = reproject_to_4326(gdf)
    assert reprojected.crs.to_epsg() == 4326


def test_load_kerr_county_boundary_missing_file(tmp_path):
    missing_path = tmp_path / "does_not_exist.geojson"
    with pytest.raises(FileNotFoundError):
        load_kerr_county_boundary(str(missing_path))


def test_load_kerr_county_boundary_reads_cached_file(tmp_path):
    boundary_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"GEOID": "48265", "NAME": "Kerr"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-99.5, 29.9], [-99.0, 29.9], [-99.0, 30.2], [-99.5, 30.2], [-99.5, 29.9]]],
                },
            }
        ],
    }
    path = tmp_path / "kerr_county_boundary.geojson"
    path.write_text(json.dumps(boundary_geojson))

    gdf = load_kerr_county_boundary(str(path))

    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 4326
    assert gdf.iloc[0]["GEOID"] == "48265"


def _load_relation_fixture_elements():
    path = os.path.join(FIXTURES_DIR, "overpass_relation_building.json")
    with open(path) as f:
        return json.load(f)["elements"]


def test_overpass_relation_with_split_outer_ring_produces_valid_polygon():
    elements = _load_relation_fixture_elements()
    relation = next(el for el in elements if el["id"] == 900000001)

    geom = overpass_element_to_geometry(relation)

    assert geom is not None
    assert geom.geom_type == "Polygon"
    assert geom.is_valid
    assert not geom.is_empty


def test_overpass_relation_with_empty_members_returns_none():
    elements = _load_relation_fixture_elements()
    relation = next(el for el in elements if el["id"] == 900000002)

    assert overpass_element_to_geometry(relation) is None


def test_overpass_elements_to_geodataframe_keeps_relation_building():
    elements = _load_relation_fixture_elements()
    relation = next(el for el in elements if el["id"] == 900000001)

    gdf = overpass_elements_to_geodataframe([relation])

    assert len(gdf) == 1
    assert gdf.iloc[0]["id"] == 900000001
    assert gdf.iloc[0]["geometry"].geom_type == "Polygon"
