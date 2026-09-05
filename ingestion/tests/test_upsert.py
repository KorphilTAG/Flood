import json

import geopandas as gpd
from shapely.geometry import Point

from lib.upsert import apply_upsert_in_memory, build_upsert_sql, rows_from_geodataframe


def make_fixture_gdf(names=("Alpha St", "Beta Rd")):
    return gpd.GeoDataFrame(
        {
            "OBJECTID": [101, 102][: len(names)],
            "STREET_NAME": list(names),
        },
        geometry=[Point(-99.3, 30.05), Point(-99.2, 30.06)][: len(names)],
        crs="EPSG:4326",
    )


def test_build_upsert_sql_has_on_conflict_clause():
    sql = build_upsert_sql("roads")
    assert "INSERT INTO roads" in sql
    assert "ON CONFLICT (feature_id) DO UPDATE SET" in sql
    assert "feature_id = EXCLUDED.feature_id" not in sql


def test_build_upsert_sql_includes_extra_columns():
    sql = build_upsert_sql("crossings", extra_columns=["osm_tag"])
    assert "osm_tag" in sql
    assert ":osm_tag" in sql


def test_rows_from_geodataframe_builds_deterministic_feature_ids():
    gdf = make_fixture_gdf()
    rows = rows_from_geodataframe(gdf, layer="road", source="txdot", id_field="OBJECTID")

    assert [r["feature_id"] for r in rows] == ["road:txdot:101", "road:txdot:102"]
    assert rows[0]["source"] == "txdot"
    assert rows[0]["source_id"] == "101"
    attrs = json.loads(rows[0]["attributes"])
    assert attrs["STREET_NAME"] == "Alpha St"


def test_upsert_rerun_is_idempotent_no_duplicates_no_id_reassignment():
    gdf = make_fixture_gdf()
    rows = rows_from_geodataframe(gdf, layer="road", source="txdot", id_field="OBJECTID")

    store = {}
    apply_upsert_in_memory(store, rows)
    first_run_ids = set(store.keys())
    assert first_run_ids == {"road:txdot:101", "road:txdot:102"}
    assert len(store) == 2

    # Re-run against the exact same source rows -- must not duplicate or
    # reassign any feature_id.
    apply_upsert_in_memory(store, rows)
    assert set(store.keys()) == first_run_ids
    assert len(store) == 2


def test_upsert_rerun_updates_attributes_without_changing_feature_id():
    gdf = make_fixture_gdf()
    rows = rows_from_geodataframe(gdf, layer="road", source="txdot", id_field="OBJECTID")

    store = {}
    apply_upsert_in_memory(store, rows)

    # Simulate the upstream source updating a non-key attribute for the same
    # source id on a later run.
    updated_gdf = make_fixture_gdf(names=("Alpha Street (renamed)", "Beta Rd"))
    updated_rows = rows_from_geodataframe(updated_gdf, layer="road", source="txdot", id_field="OBJECTID")
    apply_upsert_in_memory(store, updated_rows)

    assert len(store) == 2
    assert set(store.keys()) == {"road:txdot:101", "road:txdot:102"}
    updated_attrs = json.loads(store["road:txdot:101"]["attributes"])
    assert updated_attrs["STREET_NAME"] == "Alpha Street (renamed)"


def test_upsert_extra_fields_carried_through():
    gdf = gpd.GeoDataFrame(
        {"osm_ref": ["node/1"], "tags": [{"ford": "yes"}]},
        geometry=[Point(-99.3, 30.05)],
        crs="EPSG:4326",
    )
    rows = rows_from_geodataframe(
        gdf,
        layer="crossing",
        source="osm",
        id_field="osm_ref",
        extra_fields={"osm_tag": lambda row: "ford=yes"},
    )
    assert rows[0]["feature_id"] == "crossing:osm:node/1"
    assert rows[0]["osm_tag"] == "ford=yes"
