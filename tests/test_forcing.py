"""Tests for ForcingStore, load_forcing_store, and ParquetForcingView."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from flood.contracts.models import GaugeOutageOverride, Scenario
from flood.engine.cube import HandCube
from flood.engine.forcing import ForcingStore, ParquetForcingView, load_forcing_store


def test_protocol_conformance(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    store = load_forcing_store(mini_scenario, mini_data_dir)
    p = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(mini_scenario, store, p, mini_cube.network, mini_cube.gauges)
    assert hasattr(view, "p")
    assert isinstance(view.p, datetime)
    for method_name in ("obs_q", "obs_wse", "nwm_analysis", "latest_short_range", "qlat", "ratio"):
        method = getattr(view, method_name, None)
        assert method is not None
        assert callable(method)


def test_availability(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    store = load_forcing_store(mini_scenario, mini_data_dir)

    # 1. p = 03:00Z and latency 5: obs_q("90000001").index.max() == 02:55Z
    p_0300 = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    view_0300 = ParquetForcingView(mini_scenario, store, p_0300, mini_cube.network, mini_cube.gauges)
    obs1 = view_0300.obs_q("90000001")
    assert obs1.index.max() == datetime(2025, 1, 1, 2, 55, 0, tzinfo=timezone.utc)

    # 2. with analysis latency 60: nwm_analysis(103).index.max() == 02:00Z
    analysis_103 = view_0300.nwm_analysis(103)
    assert analysis_103.index.max() == datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc)

    # 3. with short-range latency 90:
    # latest_short_range(103) at p = 07:29Z comes from 00:00Z cycle
    p_0729 = datetime(2025, 1, 1, 7, 29, 0, tzinfo=timezone.utc)
    view_0729 = ParquetForcingView(mini_scenario, store, p_0729, mini_cube.network, mini_cube.gauges)
    sr_0729 = view_0729.latest_short_range(103)
    # 00:00Z cycle has valid times 01:00 to 06:00
    assert sr_0729.index.min() == datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert sr_0729.index.max() == datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc)

    # at p = 07:30Z comes from 06:00Z cycle
    p_0730 = datetime(2025, 1, 1, 7, 30, 0, tzinfo=timezone.utc)
    view_0730 = ParquetForcingView(mini_scenario, store, p_0730, mini_cube.network, mini_cube.gauges)
    sr_0730 = view_0730.latest_short_range(103)
    # 06:00Z cycle has valid times 07:00 to 12:00
    assert sr_0730.index.min() == datetime(2025, 1, 1, 7, 0, 0, tzinfo=timezone.utc)
    assert sr_0730.index.max() == datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_gauge_outage(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    # A gauge_outage from 02:30Z removes rows at and after 02:30Z for that site only
    outage = GaugeOutageOverride(
        type="gauge_outage",
        gauge_ref="gauge:90000001",
        from_="2025-01-01T02:30:00Z",
    )
    scenario_outage = mini_scenario.model_copy(deep=True)
    scenario_outage.forcing_defaults.scenario_overrides.append(outage)

    store = load_forcing_store(scenario_outage, mini_data_dir)
    p = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(scenario_outage, store, p, mini_cube.network, mini_cube.gauges)

    # Site 90000001 has outage at >= 02:30Z, so max index is 02:25Z
    obs1 = view.obs_q("90000001")
    assert obs1.index.max() == datetime(2025, 1, 1, 2, 25, 0, tzinfo=timezone.utc)

    # Site 90000003 is unaffected, max index is still 02:55Z
    obs3 = view.obs_q("90000003")
    assert obs3.index.max() == datetime(2025, 1, 1, 2, 55, 0, tzinfo=timezone.utc)


def test_ratio(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    # In mini_huc fixture:
    # analysis is 0.5 * truth, so ratio(103) equals 2.0 within 1e-6
    # and ratio(102) (levelpath 8, no gauge) equals 1.0
    store = load_forcing_store(mini_scenario, mini_data_dir)
    p = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(mini_scenario, store, p, mini_cube.network, mini_cube.gauges)

    assert np.isclose(view.ratio(103), 2.0, rtol=1e-6)
    assert np.isclose(view.ratio(102), 1.0, rtol=1e-6)

    # Walk downstream from 101 (levelpath 9) to reach 103 (has gauge 90000003)
    assert np.isclose(view.ratio(101), 2.0, rtol=1e-6)

    # Walk downstream from 104 (levelpath 9) to reach 105 (has gauge 90000005)
    assert view.ratio(104) > 0.0

    # When network is None, ratio returns 1.0
    view_no_net = ParquetForcingView(mini_scenario, store, p, network=None, gauges=mini_cube.gauges)
    assert view_no_net.ratio(103) == 1.0


def test_obs_wse(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    store = load_forcing_store(mini_scenario, mini_data_dir)
    p = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)

    # With gauges table providing gauge_altitude_m = 500.0 for 90000001
    view_with_gauges = ParquetForcingView(mini_scenario, store, p, mini_cube.network, mini_cube.gauges)
    wse_with = view_with_gauges.obs_wse("90000001")
    assert not wse_with.empty

    # Without gauges table (None): returns gauge height without datum
    view_without_gauges = ParquetForcingView(mini_scenario, store, p, mini_cube.network, gauges=None)
    wse_without = view_without_gauges.obs_wse("90000001")
    assert not wse_without.empty

    # Difference should equal gauge_altitude_m (500.0)
    diff = wse_with.iloc[0] - wse_without.iloc[0]
    assert np.isclose(diff, 500.0, rtol=1e-5)


def test_qlat(mini_scenario: Scenario, mini_data_dir: Path, mini_cube: HandCube) -> None:
    store = load_forcing_store(mini_scenario, mini_data_dir)
    p = datetime(2025, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
    view = ParquetForcingView(mini_scenario, store, p, mini_cube.network, mini_cube.gauges)

    # At tau = 02:00Z, analysis known at p has qlat_cms = 0.5.
    # ratio(103) = 2.0.
    # Expected qlat = 0.5 * 2.0 = 1.0.
    tau_0200 = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc)
    assert np.isclose(view.qlat(103, tau_0200), 1.0, rtol=1e-5)

    # At tau = 04:00Z (ahead of last known analysis 02:00Z):
    # Short range cycle 00:00Z is known at p (valid up to 06:00Z).
    # In build.py, short range qlat_cms is 0.45.
    # qlat = 0.45 * ratio(103) = 0.45 * 2.0 = 0.9.
    tau_0400 = datetime(2025, 1, 1, 4, 0, 0, tzinfo=timezone.utc)
    assert np.isclose(view.qlat(103, tau_0400), 0.9, rtol=1e-5)


def test_cli_prep_forcing(mini_huc_dir: Path) -> None:
    from flood.cli import main
    scenario_file = mini_huc_dir / "scenario.json"
    code = main(["prep", "forcing", str(scenario_file), "--skip-nwm", "--skip-usgs"])
    assert code == 0

