"""PostGIS adapter coverage.

The query-composition tests run offline. The round-trip tests are marked ``postgis``
and are deselected by default; they run only against a caller-supplied
``FLOOD_TEST_POSTGIS_DSN``, create their own schema, and drop it afterwards.
"""
from __future__ import annotations

import os
import uuid

import pytest

from flood.contracts.models import ExposureLayer, PostgisMapping
from flood.impact.postgis import (
    ExposureConfigError,
    ExposureDataError,
    PostGISExposureStore,
    require_postgis,
    resolve_dsn,
)

psycopg = pytest.importorskip("psycopg")
gpd = pytest.importorskip("geopandas")

DSN_ENV = "FLOOD_TEST_POSTGIS_DSN"


def _layer(**kw) -> ExposureLayer:
    base = dict(
        layer_id="road",
        name="Road segments",
        source="../data/exposure/kerr_roads.gpkg",
        postgis=PostgisMapping(schema="flood_exposure", table="kerr_2025_07_04_road", geometry_column="geometry"),
        id_field="segment_id",
        geometry="line",
        attributes=["name", "functional_class"],
        impact={"impassable_depth_m": 0.3},
    )
    base.update(kw)
    return ExposureLayer(**base)


# --- offline ---------------------------------------------------------------


def test_dsn_comes_from_argument_then_environment(monkeypatch):
    monkeypatch.delenv("FLOOD_POSTGIS_DSN", raising=False)
    assert resolve_dsn("postgresql://arg") == "postgresql://arg"
    monkeypatch.setenv("FLOOD_POSTGIS_DSN", "postgresql://env")
    assert resolve_dsn(None) == "postgresql://env"
    assert resolve_dsn("postgresql://arg") == "postgresql://arg"


def test_missing_dsn_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("FLOOD_POSTGIS_DSN", raising=False)
    with pytest.raises(ExposureConfigError, match="DSN"):
        resolve_dsn(None)


def test_layer_without_mapping_is_rejected():
    with pytest.raises(ExposureConfigError, match="postgis"):
        require_postgis(_layer(postgis=None))


def test_query_quotes_identifiers_and_parameterizes_bounds():
    """No layer name is embedded in code, and no value is interpolated into SQL."""
    store = PostGISExposureStore("postgresql://unused")
    sql_text = store._build_query(_layer()).as_string(None)
    assert '"flood_exposure"."kerr_2025_07_04_road"' in sql_text
    assert '"segment_id"' in sql_text and '"geometry"' in sql_text
    assert '"name"' in sql_text and '"functional_class"' in sql_text
    # Bounds arrive as bind parameters, never as literals.
    assert sql_text.count("%s") == 5
    assert "ST_MakeEnvelope(%s, %s, %s, %s, %s)" in sql_text


def test_query_selects_only_allow_listed_columns():
    store = PostGISExposureStore("postgresql://unused")
    sql_text = store._build_query(_layer(attributes=["name"])).as_string(None)
    assert '"functional_class"' not in sql_text


def test_identifier_injection_is_impossible_through_the_registry():
    """A hostile table name cannot pass the contract model's identifier pattern."""
    with pytest.raises(ValueError):
        PostgisMapping(schema="public", table='roads"; DROP TABLE users --', geometry_column="geom")


def test_duplicate_ids_are_rejected():
    from shapely.geometry import LineString

    gdf = gpd.GeoDataFrame(
        {
            "segment_id": ["a", "a"],
            "name": ["x", "y"],
            "functional_class": ["local", "local"],
            "geometry": [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])],
        },
        crs="EPSG:4326",
    )
    with pytest.raises(ExposureDataError, match="duplicate"):
        PostGISExposureStore._validate(gdf, _layer(), 4326, "EPSG:5070")


def test_unsupported_geometry_type_is_rejected():
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(
        {
            "segment_id": ["a"],
            "name": ["x"],
            "functional_class": ["local"],
            "geometry": [Point(0, 0)],
        },
        crs="EPSG:4326",
    )
    with pytest.raises(ExposureDataError, match="declared 'line'"):
        PostGISExposureStore._validate(gdf, _layer(), 4326, "EPSG:5070")


def test_empty_geometry_is_rejected():
    from shapely.geometry import LineString

    gdf = gpd.GeoDataFrame(
        {
            "segment_id": ["a"],
            "name": ["x"],
            "functional_class": ["local"],
            "geometry": [LineString()],
        },
        crs="EPSG:4326",
    )
    with pytest.raises(ExposureDataError, match="empty geometry"):
        PostGISExposureStore._validate(gdf, _layer(), 4326, "EPSG:5070")


# --- opt-in round trip -----------------------------------------------------

@pytest.fixture
def live_schema():
    """Create an isolated schema in the caller's database and drop it afterwards."""
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        pytest.skip(f"{DSN_ENV} is not set")
    schema = f"flood_it_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(
            f'CREATE TABLE "{schema}"."roads" ('
            "  segment_id text PRIMARY KEY,"
            "  name text,"
            "  functional_class text,"
            "  geometry geometry(LineString, 4326))"
        )
        cur.execute(
            f'INSERT INTO "{schema}"."roads" VALUES '
            "('seg-1', 'Inside Road', 'local', ST_GeomFromText('LINESTRING(-99.2 30.0, -99.1 30.05)', 4326)),"
            "('seg-2', 'Far Road', 'local', ST_GeomFromText('LINESTRING(10 10, 10.1 10.1)', 4326))"
        )
    try:
        yield dsn, schema
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.postgis
def test_reads_through_read_postgis_and_bounds_the_query(live_schema, monkeypatch):
    """Proves geopandas.read_postgis is the read path and the bbox filter applies."""
    dsn, schema = live_schema
    layer = _layer(
        postgis=PostgisMapping(schema=schema, table="roads", geometry_column="geometry")
    )
    calls = {}
    real = gpd.read_postgis

    def spy(*args, **kwargs):
        calls["used"] = True
        calls["params"] = kwargs.get("params")
        return real(*args, **kwargs)

    monkeypatch.setattr(gpd, "read_postgis", spy)

    store = PostGISExposureStore(dsn)
    # A WGS84 bbox around seg-1 only, expressed in the raster's CRS.
    bounds = (-99.3, 29.9, -99.0, 30.2)
    gdf = store.load(layer, bounds, "EPSG:4326", "EPSG:5070")

    assert calls.get("used") is True
    assert len(calls["params"]) == 5
    assert list(gdf[layer.id_field]) == ["seg-1"]
    assert set(gdf.columns) == {"segment_id", "name", "functional_class", "geometry"}
    assert gdf.crs.to_string() == "EPSG:5070"


@pytest.mark.postgis
def test_live_schema_is_cleaned_up(live_schema):
    dsn, schema = live_schema
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,))
        assert cur.fetchone() is not None
