"""Offline Contract 2 extraction against synthetic Contract 1 rasters and vectors.

No database and no network: the exposure store is a fake returning in-memory
GeoDataFrames, and the COGs are written by the real Contract 1 writer so band
descriptions, nodata, and dtype match production products.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from shapely.geometry import LineString, Point, Polygon

from flood.contracts.validate import validate_json
from flood.impact.extractor import (
    ImpactExtractionError,
    ImpactExtractor,
    impact_path,
    write_impact_json,
)
from flood.impact.postgis import ExposureConfigError
from flood.interfaces import NODATA, Grid, StateArrays
from flood.products.raster import write_depth_cog

# A small grid inside the Kerr AOI so the fixture shares the scenario's CRS.
X0, YTOP = -340000.0, 790000.0
RES, N = 10.0, 20
GRID = Grid.from_bounds((X0, YTOP - N * RES, X0 + N * RES, YTOP), resolution_m=RES, crs="EPSG:5070")

T0 = datetime(2025, 7, 4, 6, 15, 0, tzinfo=timezone.utc)
P0 = datetime(2025, 7, 4, 6, 10, 0, tzinfo=timezone.utc)


def _xy(row: int, col: int) -> tuple[float, float]:
    """Centre of a grid cell, so a point sample is unambiguous."""
    return X0 + col * RES + RES / 2, YTOP - row * RES - RES / 2


# Where each fixture feature sits on the grid.
CROSSING_CELL = (5, 5)
DRY_CROSSING_CELL = (18, 1)
ROAD_ROW, ROAD_COLS = 10, (2, 8)
STRUCTURE_ROWS, STRUCTURE_COLS = (14, 16), (14, 16)
SITE_ROWS, SITE_COLS = (2, 4), (14, 16)


def _cells(rows: tuple[int, int], cols: tuple[int, int]) -> tuple[slice, slice]:
    return slice(rows[0], rows[1] + 1), slice(cols[0], cols[1] + 1)


def _polygon(rows: tuple[int, int], cols: tuple[int, int]) -> Polygon:
    xmin = X0 + cols[0] * RES
    xmax = X0 + (cols[1] + 1) * RES
    ymax = YTOP - rows[0] * RES
    ymin = YTOP - (rows[1] + 1) * RES
    return Polygon([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])


@pytest.fixture
def exposure() -> dict[str, gpd.GeoDataFrame]:
    """One feature of each geometry kind, plus a crossing that never floods."""
    crs = GRID.crs
    crossings = gpd.GeoDataFrame(
        {
            "crossing_id": ["cr-17", "cr-99"],
            "road_name": ["Example Road", "Dry Ridge"],
            "geometry": [Point(*_xy(*CROSSING_CELL)), Point(*_xy(*DRY_CROSSING_CELL))],
        },
        crs=crs,
    )
    y = YTOP - ROAD_ROW * RES - RES / 2
    roads = gpd.GeoDataFrame(
        {
            "segment_id": ["seg-17"],
            "name": ["Example Road"],
            "functional_class": ["local"],
            "egress_for_site": ["camp-4"],
            "geometry": [
                LineString([(X0 + ROAD_COLS[0] * RES + RES / 2, y), (X0 + ROAD_COLS[1] * RES + RES / 2, y)])
            ],
        },
        crs=crs,
    )
    structures = gpd.GeoDataFrame(
        {
            "osm_id": ["b-1"],
            "building": ["yes"],
            "geometry": [_polygon(STRUCTURE_ROWS, STRUCTURE_COLS)],
        },
        crs=crs,
    )
    sites = gpd.GeoDataFrame(
        {
            "site_id": ["camp-4"],
            "name": ["Example Camp"],
            "site_type": ["camp"],
            "occupancy_est": [120],
            "geometry": [_polygon(SITE_ROWS, SITE_COLS)],
        },
        crs=crs,
    )
    return {"crossing": crossings, "road": roads, "structure": structures, "site": sites}


class FakeExposureStore:
    """Returns fixture features, projected exactly as PostGISExposureStore projects them.

    The column subsetting matters: the real store SELECTs only the id, the registry
    attribute allow-list, and any explicitly requested join column. A fake that handed
    back every fixture column would let an extractor bug that never requests an egress
    `join_field` pass here and then fail against a real database.
    """

    def __init__(self, features: dict[str, gpd.GeoDataFrame]) -> None:
        self.features = features
        self.calls: list[tuple[str, tuple, str, tuple]] = []

    def load(self, layer, bounds, bounds_crs, target_crs, extra_columns=()):
        self.calls.append((layer.layer_id, tuple(bounds), target_crs, tuple(extra_columns)))
        gdf = self.features[layer.layer_id].to_crs(target_crs)
        keep = list(dict.fromkeys([layer.id_field, *layer.attributes, *extra_columns]))
        missing = [c for c in keep if c not in gdf.columns]
        assert not missing, f"{layer.layer_id}: fixture lacks requested column(s) {missing}"
        return gdf[[*keep, "geometry"]]


def _write_cog(path: Path, depth: np.ndarray, hazard: np.ndarray | None = None) -> Path:
    """Write a real six-band Contract 1 COG from a depth field."""
    hazard = np.zeros_like(depth) if hazard is None else hazard
    arrays = StateArrays(
        p=P0,
        t=T0,
        depth_mid=depth,
        depth_low=depth * 0.8,
        depth_high=depth * 1.2,
        velocity_ms=np.full_like(depth, 0.5),
        hazard_dv=hazard,
        prob_inundated=(depth >= 0.03).astype("float32"),
        compute_ms={},
    )
    return write_depth_cog(path, GRID, arrays)


def _dry() -> np.ndarray:
    return np.zeros((N, N), dtype="float32")


@pytest.fixture
def cogs(tmp_path: Path) -> dict[datetime, Path]:
    """Current plus +30/+60/+120 rasters, each flooding one more fixture feature."""
    t30, t60, t120 = (T0 + timedelta(minutes=m) for m in (30, 60, 120))

    now = _dry()
    # Nodata must not read as dry: park a nodata block on empty ground.
    now[0, 0] = NODATA

    d30 = _dry()
    d30[CROSSING_CELL] = 0.20  # >= crossing impassable_depth_m 0.15

    d60 = d30.copy()
    d60[ROAD_ROW, ROAD_COLS[0] : ROAD_COLS[1] + 1] = 0.35  # >= road 0.30

    d120 = d60.copy()
    d120[_cells(STRUCTURE_ROWS, STRUCTURE_COLS)] = 0.12  # >= structure 0.10

    return {
        T0: _write_cog(tmp_path / "t0.tif", now),
        t30: _write_cog(tmp_path / "t30.tif", d30),
        t60: _write_cog(tmp_path / "t60.tif", d60),
        t120: _write_cog(tmp_path / "t120.tif", d120),
    }


def _extract(kerr_scenario, exposure, cogs, **kw):
    store = FakeExposureStore(exposure)
    extractor = ImpactExtractor(kerr_scenario, store)
    current = cogs[T0]
    projections = {t: p for t, p in cogs.items() if t != T0}
    return extractor.extract(
        run_id="kerr-2025-07-04-test",
        p=kw.pop("p", P0),
        t=T0,
        current_cog=current,
        projection_cogs=kw.pop("projection_cogs", projections),
        **kw,
    )


def test_bands_resolved_by_description_not_index(tmp_path, kerr_scenario, exposure):
    """A COG whose bands are in a different order still extracts correctly."""
    depth = _dry()
    depth[CROSSING_CELL] = 0.20
    path = tmp_path / "shuffled.tif"
    # Same data, deliberately reversed band order: only descriptions can disambiguate.
    with rasterio.open(
        path, "w", driver="GTiff", height=N, width=N, count=6, dtype="float32",
        crs=GRID.crs, transform=rasterio.Affine(*GRID.transform), nodata=NODATA,
    ) as dst:
        dst.write(np.zeros((N, N), "float32"), 1)   # prob_inundated
        dst.write(np.zeros((N, N), "float32"), 2)   # hazard_dv
        dst.write(np.full((N, N), 0.5, "float32"), 3)  # velocity_ms
        dst.write(depth * 1.2, 4)
        dst.write(depth * 0.8, 5)
        dst.write(depth, 6)                          # depth_mid last
        dst.descriptions = (
            "prob_inundated", "hazard_dv", "velocity_ms", "depth_high", "depth_low", "depth_mid",
        )
    payload = _extract(kerr_scenario, exposure, {T0: path}, projection_cogs={})
    refs = [f["feature_ref"] for f in payload["facts"]]
    assert "crossing:cr-17" in refs


def test_missing_required_band_is_an_error(tmp_path, kerr_scenario, exposure):
    path = tmp_path / "nobands.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=N, width=N, count=1, dtype="float32",
        crs=GRID.crs, transform=rasterio.Affine(*GRID.transform), nodata=NODATA,
    ) as dst:
        dst.write(_dry(), 1)
        dst.descriptions = ("something_else",)
    with pytest.raises(ImpactExtractionError, match="band description"):
        _extract(kerr_scenario, exposure, {T0: path}, projection_cogs={})


def test_missing_future_cog_is_an_error_not_implicit_dry(tmp_path, kerr_scenario, exposure, cogs):
    """A declared projection target whose product is absent must fail loudly."""
    missing = tmp_path / "does-not-exist.tif"
    with pytest.raises(ImpactExtractionError, match="missing"):
        _extract(
            kerr_scenario, exposure, cogs,
            projection_cogs={T0 + timedelta(minutes=30): missing},
        )


def test_grid_mismatch_is_an_error(tmp_path, kerr_scenario, exposure, cogs):
    other = Grid.from_bounds((X0, YTOP - 400, X0 + 400, YTOP), resolution_m=RES, crs="EPSG:5070")
    arrays = StateArrays(
        p=P0, t=T0,
        depth_mid=np.zeros((40, 40), "float32"), depth_low=np.zeros((40, 40), "float32"),
        depth_high=np.zeros((40, 40), "float32"), velocity_ms=np.zeros((40, 40), "float32"),
        hazard_dv=np.zeros((40, 40), "float32"), prob_inundated=np.zeros((40, 40), "float32"),
        compute_ms={},
    )
    path = write_depth_cog(tmp_path / "bigger.tif", other, arrays)
    with pytest.raises(ImpactExtractionError, match="shape|transform|CRS"):
        _extract(
            kerr_scenario, exposure, cogs,
            projection_cogs={T0 + timedelta(minutes=30): path},
        )


def test_classification_uses_only_registry_thresholds(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    kinds = {f["feature_ref"]: f["kind"] for f in payload["facts"]}
    assert kinds["crossing:cr-17"] == "impassable"
    assert kinds["road:seg-17"] == "impassable"
    assert kinds["structure:b-1"] == "threatened"


def test_feature_dry_at_every_target_is_absent(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    refs = [f["feature_ref"] for f in payload["facts"]]
    assert "crossing:cr-99" not in refs


def test_attributes_are_exactly_the_registry_allow_list(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    by_ref = {f["feature_ref"]: f for f in payload["facts"]}
    assert set(by_ref["crossing:cr-17"]["attributes"]) == {"road_name"}
    assert set(by_ref["road:seg-17"]["attributes"]) == {"name", "functional_class"}
    # `egress_for_site` is a join column, not an allow-listed attribute.
    assert "egress_for_site" not in by_ref["road:seg-17"]["attributes"]


def test_projections_hold_one_fixed_p_and_earliest_impact(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    assert payload["p"] == "2025-07-04T06:10:00Z"
    by_ref = {f["feature_ref"]: f for f in payload["facts"]}

    crossing = by_ref["crossing:cr-17"]
    assert crossing["impacted_now"] is False
    assert crossing["first_impacted_t"] == "2025-07-04T06:45:00Z"
    assert [p["t"] for p in crossing["projections"]] == [
        "2025-07-04T06:45:00Z", "2025-07-04T07:15:00Z", "2025-07-04T08:15:00Z",
    ]
    assert [p["impacted"] for p in crossing["projections"]] == [True, True, True]

    assert by_ref["road:seg-17"]["first_impacted_t"] == "2025-07-04T07:15:00Z"
    assert by_ref["structure:b-1"]["first_impacted_t"] == "2025-07-04T08:15:00Z"


def test_target_outside_horizon_is_omitted_not_substituted(kerr_scenario, exposure, cogs):
    """Only the offered projection targets appear; nothing is invented for the rest."""
    only_30 = {T0 + timedelta(minutes=30): cogs[T0 + timedelta(minutes=30)]}
    payload = _extract(kerr_scenario, exposure, cogs, projection_cogs=only_30)
    crossing = next(f for f in payload["facts"] if f["feature_ref"] == "crossing:cr-17")
    assert [p["t"] for p in crossing["projections"]] == ["2025-07-04T06:45:00Z"]


def test_egress_blocked_reports_first_blocked_time(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    egress = {e["site_ref"]: e for e in payload["egress"]}
    camp = egress["site:camp-4"]
    assert camp["route_refs"] == ["road:seg-17"]
    assert camp["status"] == "blocked"
    assert camp["first_blocked_t"] == "2025-07-04T07:15:00Z"


def test_egress_join_column_is_requested_from_the_store(kerr_scenario, exposure, cogs):
    """The routes layer must be fetched with its join column, or egress can never resolve.

    `egress_for_site` is not in the road layer's attribute allow-list, so the store only
    returns it when the extractor asks for it explicitly.
    """
    store = FakeExposureStore(exposure)
    ImpactExtractor(kerr_scenario, store).extract(
        run_id="kerr-2025-07-04-test", p=P0, t=T0, current_cog=cogs[T0], projection_cogs={},
    )
    requested = {layer_id: extra for layer_id, _, _, extra in store.calls}
    assert requested["road"] == ("egress_for_site",)
    assert requested["crossing"] == ()


def test_egress_via_unknown_routes_layer_is_a_config_error(kerr_scenario, exposure, cogs):
    scenario = kerr_scenario.model_copy(deep=True)
    for layer in scenario.exposure_layers:
        if layer.egress is not None:
            layer.egress.routes_layer = "nonexistent"
    with pytest.raises(ExposureConfigError, match="routes_layer"):
        ImpactExtractor(scenario, FakeExposureStore(exposure)).extract(
            run_id="kerr-2025-07-04-test", p=P0, t=T0, current_cog=cogs[T0], projection_cogs={},
        )


def test_egress_unknown_when_no_route_is_configured(kerr_scenario, exposure, cogs):
    exposure["road"] = exposure["road"].assign(egress_for_site=["someone-else"])
    payload = _extract(kerr_scenario, exposure, cogs)
    camp = next(e for e in payload["egress"] if e["site_ref"] == "site:camp-4")
    assert camp["status"] == "unknown"
    assert camp["route_refs"] == []
    assert camp["first_blocked_t"] is None


def test_nodata_is_not_treated_as_dry(kerr_scenario, exposure, cogs):
    """The nodata cell in the current raster yields no impact and no crash."""
    payload = _extract(kerr_scenario, exposure, cogs)
    assert all(f["depth_max_m"] >= 0 for f in payload["facts"])
    assert all(f["hazard_dv_max_m2_per_s"] >= 0 for f in payload["facts"])


def test_hazard_limit_alone_can_impact_a_feature(tmp_path, kerr_scenario, exposure):
    """The crossing's hazard_dv_limit classifies it even with sub-threshold depth."""
    depth = _dry()
    depth[CROSSING_CELL] = 0.05  # below impassable_depth_m 0.15
    hazard = _dry()
    hazard[CROSSING_CELL] = 0.9  # above hazard_dv_limit 0.5
    path = _write_cog(tmp_path / "hazard.tif", depth, hazard)
    payload = _extract(kerr_scenario, exposure, {T0: path}, projection_cogs={})
    refs = [f["feature_ref"] for f in payload["facts"]]
    assert "crossing:cr-17" in refs


def test_layer_without_applicable_threshold_is_a_config_error(kerr_scenario, exposure, cogs):
    scenario = kerr_scenario.model_copy(deep=True)
    for layer in scenario.exposure_layers:
        if layer.layer_id == "road":
            layer.impact = None
    extractor = ImpactExtractor(scenario, FakeExposureStore(exposure))
    with pytest.raises(ExposureConfigError, match="impassable_depth_m"):
        extractor.extract(
            run_id="kerr-2025-07-04-test", p=P0, t=T0,
            current_cog=cogs[T0], projection_cogs={},
        )


def test_layer_without_postgis_mapping_is_a_config_error(kerr_scenario, exposure, cogs):
    scenario = kerr_scenario.model_copy(deep=True)
    for layer in scenario.exposure_layers:
        if layer.layer_id == "structure":
            layer.postgis = None
    extractor = ImpactExtractor(scenario, FakeExposureStore(exposure))
    with pytest.raises(ExposureConfigError, match="postgis"):
        extractor.extract(
            run_id="kerr-2025-07-04-test", p=P0, t=T0,
            current_cog=cogs[T0], projection_cogs={},
        )


def test_reaches_are_reduced_to_contract_2_columns(tmp_path, kerr_scenario, exposure, cogs):
    """The sidecar carries far more than Contract 2 keeps."""
    sidecar = tmp_path / "reaches.parquet"
    pd.DataFrame(
        {
            "reach_ref": ["reach:3586192"],
            "feature_id": [3586192],
            "q_mid_cms": [412.0],
            "stage_mid_m": [2.31],
            "rate_of_rise_m_per_h": [0.42],
            "velocity_ms": [1.17],
            "source": ["routed"],
            "gauge_ref": ["gauge:08166200"],
        }
    ).to_parquet(sidecar)
    payload = _extract(kerr_scenario, exposure, cogs, reaches_parquet=sidecar)
    assert payload["reaches"] == [
        {
            "reach_ref": "reach:3586192",
            "stage_mid_m": 2.31,
            "rate_of_rise_m_per_h": 0.42,
            "velocity_ms": 1.17,
            "source": "routed",
        }
    ]
    assert payload["velocity_is_proxy"] is True


def test_output_validates_and_carries_no_coordinates(kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    validate_json("impact-json", payload)
    text = json.dumps(payload)
    for banned in ("geometry", "coordinates", '"lon"', '"lat"'):
        assert banned not in text
    assert all(":" in f["feature_ref"] for f in payload["facts"])


def test_write_is_atomic_and_at_the_canonical_path(tmp_path, kerr_scenario, exposure, cogs):
    payload = _extract(kerr_scenario, exposure, cogs)
    out = impact_path(tmp_path, P0, T0)
    written = write_impact_json(out, payload)
    assert written == tmp_path / "impacts" / "p=20250704T0610Z" / "t=20250704T0615Z" / "impact.json"
    assert json.loads(written.read_text()) == payload
    assert not list(written.parent.glob("*.tmp"))


def test_hindsight_path_and_null_p(kerr_scenario, exposure, cogs, tmp_path):
    payload = _extract(kerr_scenario, exposure, cogs, p=None)
    assert payload["p"] is None
    validate_json("impact-json", payload)
    out = write_impact_json(impact_path(tmp_path, None, T0), payload)
    assert out == tmp_path / "impacts" / "hindsight" / "t=20250704T0615Z" / "impact.json"
