"""Unit tests for flood.products.tables."""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
import pytest

from flood.engine.forcing import load_forcing_store, ParquetForcingView
from flood.engine.mapping import map_member
from flood.engine.routing import route
from flood.interfaces import MEMBERS
from flood.products.tables import (
    build_gauges,
    build_reaches,
    gauges_to_json,
    reaches_to_json,
)


class DummyRun:
    def __init__(self, cube, scenario, store):
        self.cube = cube
        self.scenario = scenario
        self.store = store
        self.record_start = pd.to_datetime(scenario.hydrology.record.start, utc=True).to_pydatetime()
        self.record_end = pd.to_datetime(scenario.hydrology.record.end, utc=True).to_pydatetime()
        self.max_horizon_minutes = 360


@pytest.fixture
def mini_run_ctx(mini_cube, mini_scenario, mini_data_dir):
    store = load_forcing_store(mini_scenario, mini_data_dir)
    return DummyRun(mini_cube, mini_scenario, store)


def test_build_reaches_and_json(mini_run_ctx):
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    t = datetime(2025, 1, 1, 6, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(
        mini_run_ctx.scenario,
        mini_run_ctx.store,
        p,
        network=mini_run_ctx.cube.network,
        gauges=mini_run_ctx.cube.gauges,
    )
    routed = route(
        mini_run_ctx.cube,
        view,
        mini_run_ctx.scenario,
        mini_run_ctx.scenario.forcing_defaults,
        members=MEMBERS,
    )
    q_mid = {fid: float(routed.at(t)[1, i]) for i, fid in enumerate(routed.feature_ids)}
    mid_mf = map_member(mini_run_ctx.cube, q_mid, with_velocity=True)

    reaches_df = build_reaches(mini_run_ctx, routed, t, mid_mf)
    assert len(reaches_df) == 6
    assert list(reaches_df["feature_id"]) == sorted(reaches_df["feature_id"])
    assert "stage_mid_m" in reaches_df.columns
    assert bool(reaches_df["is_forecast"].iloc[0]) is True

    # Test reach 101 source
    r101 = reaches_df[reaches_df["feature_id"] == 101].iloc[0]
    assert r101["source"] == "forecast_trend"

    # Test JSON conversion and validation
    records = reaches_to_json(reaches_df)
    assert len(records) == 6
    assert records[0]["reach_ref"] == "reach:101"


def test_build_gauges_and_json(mini_run_ctx):
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(
        mini_run_ctx.scenario,
        mini_run_ctx.store,
        p,
        network=mini_run_ctx.cube.network,
        gauges=mini_run_ctx.cube.gauges,
    )
    routed = route(
        mini_run_ctx.cube,
        view,
        mini_run_ctx.scenario,
        mini_run_ctx.scenario.forcing_defaults,
        members=MEMBERS,
    )

    gauges_df = build_gauges(mini_run_ctx, routed, p)
    assert not gauges_df.empty

    # Gauge 90000001 has latency 5 min, so for t > 03:55:00Z, observed_q_cms must be null / nan
    g1 = gauges_df[gauges_df["site"] == "90000001"]
    t_cutoff = pd.Timestamp("2025-01-01T03:55:00Z")
    after_cutoff = g1[g1["t"] > t_cutoff]
    assert after_cutoff["observed_q_cms"].isna().all()

    # Before cutoff, should have values
    before_cutoff = g1[g1["t"] <= t_cutoff]
    assert not before_cutoff["observed_q_cms"].isna().all()

    # JSON conversion and schema validation
    records = gauges_to_json(gauges_df)
    assert len(records) == len(gauges_df)
    for r in records:
        assert r["wse_datum"] == "NAVD88"
