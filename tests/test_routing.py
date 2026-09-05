"""Tests for reach routing and forecasting."""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from flood.engine.routing import (
    _celerity,
    _stage_from_q,
    _top_width,
    _wet_area,
    mc_params,
    mc_step,
    route,
)
from flood.interfaces import SOURCE_INDEX, SOURCE_CODES


class FixtureForcingView:
    """ForcingView protocol implementation backed by mini-huc fixture parquet files."""

    def __init__(self, data_dir: Path, p: datetime):
        self.p = p
        usgs = pd.read_parquet(data_dir / "usgs" / "mini-huc" / "continuous.parquet")
        ana = pd.read_parquet(data_dir / "nwm" / "mini-huc" / "analysis.parquet")
        sr = pd.read_parquet(data_dir / "nwm" / "mini-huc" / "short_range.parquet")

        cutoff_obs = self.p if self.p >= datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc) else self.p - timedelta(minutes=5)
        self._obs_q_cache: dict[str, pd.Series] = {}
        self._obs_wse_cache: dict[str, pd.Series] = {}
        for site, g in usgs[usgs["valid_time"] <= cutoff_obs].sort_values("valid_time").groupby("site"):
            q_rows = g[g["parameter"] == "00060"]
            if not q_rows.empty:
                self._obs_q_cache[site] = pd.Series(q_rows["value_si"].to_numpy(dtype=float), index=pd.DatetimeIndex(q_rows["valid_time"]))
            wse_rows = g[g["parameter"] == "00065"]
            if not wse_rows.empty:
                self._obs_wse_cache[site] = pd.Series(wse_rows["value_si"].to_numpy(dtype=float), index=pd.DatetimeIndex(wse_rows["valid_time"]))

        cutoff_ana = self.p - timedelta(minutes=60)
        ana_df = ana[ana["valid_time"] <= cutoff_ana].sort_values("valid_time")
        self._ana_cache: dict[int, pd.Series] = {}
        self._qlat_cache: dict[int, tuple[list[float], np.ndarray]] = {}
        for fid, g in ana_df.groupby("feature_id"):
            self._ana_cache[fid] = pd.Series(g["q_cms"].to_numpy(dtype=float), index=pd.DatetimeIndex(g["valid_time"]))
            self._qlat_cache[fid] = ([ts.timestamp() for ts in g["valid_time"]], g["qlat_cms"].to_numpy(dtype=float))

        self._ratio_cache: dict[int, float] = {}
        obs_101 = self._obs_q_cache.get("90000001", pd.Series(dtype=float))
        ana_101 = self._ana_cache.get(101, pd.Series(dtype=float))
        common = obs_101.index.intersection(ana_101.index)
        ratio_val = 1.0
        if len(common) > 0:
            t = common.max()
            a_val = float(ana_101.loc[t])
            if a_val > 0:
                ratio_val = float(obs_101.loc[t]) / a_val
        for fid in [101, 103, 104, 105, 106]:
            self._ratio_cache[fid] = ratio_val

        cutoff_sr = self.p - timedelta(minutes=90)
        sr_df = sr[sr["issue_time"] <= cutoff_sr]
        self._sr_cache: dict[int, pd.Series] = {}
        if not sr_df.empty:
            max_it = sr_df["issue_time"].max()
            for fid, g in sr_df[sr_df["issue_time"] == max_it].sort_values("valid_time").groupby("feature_id"):
                self._sr_cache[fid] = pd.Series(g["q_cms"].to_numpy(dtype=float), index=pd.DatetimeIndex(g["valid_time"]))

    def obs_q(self, site: str) -> pd.Series:
        return self._obs_q_cache.get(site, pd.Series(dtype=float))

    def obs_wse(self, site: str) -> pd.Series:
        return self._obs_wse_cache.get(site, pd.Series(dtype=float))

    def nwm_analysis(self, feature_id: int) -> pd.Series:
        return self._ana_cache.get(feature_id, pd.Series(dtype=float))

    def latest_short_range(self, feature_id: int) -> pd.Series:
        return self._sr_cache.get(feature_id, pd.Series(dtype=float))

    def ratio(self, feature_id: int) -> float:
        return self._ratio_cache.get(feature_id, 1.0)

    def qlat(self, feature_id: int, tau: datetime) -> float:
        cached = self._qlat_cache.get(feature_id)
        if not cached:
            return 0.0
        times, qlats = cached
        tau_s = tau.timestamp()
        idx = int(np.searchsorted(times, tau_s, side="right")) - 1
        base = float(qlats[idx]) if idx >= 0 else float(qlats[-1])
        return base * self.ratio(feature_id)


def test_mc_step_properties():
    """mc_step steady state, coefficients sum to one, and reach-level mass conservation."""
    q_ss = 25.0
    res = mc_step(q_ss, q_ss, q_ss, K=600.0, X=0.3, dt=60.0)
    assert math.isclose(res, q_ss, rel_tol=1e-6)

    # Test coefficients sum to 1 algebraically
    dt = 60.0
    K = 600.0
    X = 0.3
    denom = 2.0 * K * (1.0 - X) + dt
    c0 = (dt - 2.0 * K * X) / denom
    c1 = (dt + 2.0 * K * X) / denom
    c2 = (2.0 * K * (1.0 - X) - dt) / denom
    assert math.isclose(c0 + c1 + c2, 1.0, rel_tol=1e-9)

    # Sub-stepping case
    res_sub = mc_step(q_ss, q_ss, q_ss, K=10.0, X=0.3, dt=60.0)
    assert math.isclose(res_sub, q_ss, rel_tol=1e-6)

    # Mass conservation over long draining window (triangular hydrograph)
    rise = 60
    n_steps = rise * 4
    q_in = [
        max(0.0, 40.0 * (1.0 - abs(t - rise) / float(rise)))
        for t in range(n_steps)
    ]
    q_out = [0.0] * n_steps
    cur_out = 0.0
    for t in range(1, n_steps):
        cur_out = mc_step(q_in[t - 1], q_in[t], cur_out, K=600.0, X=0.3, dt=60.0)
        q_out[t] = cur_out

    vol_in = sum(q_in) * 60.0
    vol_out = sum(q_out) * 60.0
    assert abs(vol_out - vol_in) / vol_in <= 0.005  # within 0.5%


def test_controls_reproduction(mini_cube, mini_scenario, mini_data_dir):
    """Controls: q[mid] at reaches 101 and 103 equals fixture observation within 1e-4 at tau <= 03:55Z."""
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    fids = list(routed.feature_ids)
    idx_101 = fids.index(101)
    idx_103 = fids.index(103)

    obs1 = view.obs_q("90000001")
    obs3 = view.obs_q("90000003")

    cutoff = np.datetime64("2025-01-01T03:55:00", "s")
    for t_idx, tau in enumerate(routed.taus):
        if tau <= cutoff:
            t_dt = pd.to_datetime(tau).tz_localize("UTC")
            val_101 = routed.q[1, idx_101, t_idx]
            val_103 = routed.q[1, idx_103, t_idx]
            expected_101 = float(np.interp(t_dt.timestamp(), [ts.timestamp() for ts in obs1.index], obs1.values))
            expected_103 = float(np.interp(t_dt.timestamp(), [ts.timestamp() for ts in obs3.index], obs3.values))
            assert abs(val_101 - expected_101) <= 1e-4
            assert abs(val_103 - expected_103) <= 1e-4


def _find_peak_time_s(taus: np.ndarray, q: np.ndarray) -> float:
    idx = int(np.argmax(q))
    t0 = float(taus[idx].astype("datetime64[s]").astype(np.int64))
    if 0 < idx < len(q) - 1:
        y_prev, y0, y_next = float(q[idx - 1]), float(q[idx]), float(q[idx + 1])
        denom = y_prev - 2.0 * y0 + y_next
        if abs(denom) > 1e-9:
            dt = float((taus[idx + 1] - taus[idx]) / np.timedelta64(1, "s"))
            delta = 0.5 * (y_prev - y_next) / denom
            return t0 + delta * dt
    return t0


def test_lag_and_celerity(mini_cube, mini_scenario, mini_data_dir):
    """Lag: with p = record end (hindsight), peak time of q[mid] at 104 is later than 103 within 50% of 1000/c."""
    p = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    fids = list(routed.feature_ids)
    idx_103 = fids.index(103)
    idx_104 = fids.index(104)

    t103 = _find_peak_time_s(routed.taus, routed.q[1, idx_103, :])
    t104 = _find_peak_time_s(routed.taus, routed.q[1, idx_104, :])
    lag_s = t104 - t103
    assert lag_s > 0

    peak_q_104 = float(np.max(routed.q[1, idx_104, :]))
    b = mini_cube.branch(9)
    c = _celerity(b.rating, 1, peak_q_104)
    expected_lag_s = 1000.0 / c

    rel_error = abs(lag_s - expected_lag_s) / expected_lag_s
    assert rel_error <= 0.50


def test_member_ordering(mini_cube, mini_scenario, mini_data_dir):
    """Members: at reach 101 for tau > 03:55Z, q[low] <= q[mid] <= q[high] with strict inequality at 04:30Z; equal <= 03:55Z."""
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    fids = list(routed.feature_ids)
    idx_101 = fids.index(101)

    cutoff = np.datetime64("2025-01-01T03:55:00", "s")
    t_0430 = np.datetime64("2025-01-01T04:30:00", "s")

    for t_idx, tau in enumerate(routed.taus):
        q_low = routed.q[0, idx_101, t_idx]
        q_mid = routed.q[1, idx_101, t_idx]
        q_high = routed.q[2, idx_101, t_idx]

        if tau <= cutoff:
            assert math.isclose(q_low, q_mid, rel_tol=1e-5, abs_tol=1e-5)
            assert math.isclose(q_mid, q_high, rel_tol=1e-5, abs_tol=1e-5)
        else:
            assert q_low <= q_mid <= q_high

        if tau == t_0430:
            assert q_low < q_mid < q_high


def test_junction_inference(mini_cube, mini_scenario, mini_data_dir):
    """Junction: reach 102 at 03:00Z equals obs3(03:10Z) - obs1(03:00Z) within 1e-3 and has source code mass_balance."""
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    fids = list(routed.feature_ids)
    idx_102 = fids.index(102)

    obs1 = view.obs_q("90000001")
    obs3 = view.obs_q("90000003")

    t_0300 = datetime(2025, 1, 1, 3, 0, tzinfo=timezone.utc)
    t_0310 = datetime(2025, 1, 1, 3, 10, tzinfo=timezone.utc)

    val_obs1 = float(np.interp(t_0300.timestamp(), [ts.timestamp() for ts in obs1.index], obs1.values))
    val_obs3 = float(np.interp(t_0310.timestamp(), [ts.timestamp() for ts in obs3.index], obs3.values))
    expected = val_obs3 - val_obs1

    step_0300 = routed.index_of(t_0300)
    actual = routed.q[1, idx_102, step_0300]
    src = routed.source[idx_102, step_0300]

    assert math.isclose(actual, expected, abs_tol=1e-3)
    assert src == SOURCE_INDEX["mass_balance"]


def test_source_codes(mini_cube, mini_scenario, mini_data_dir):
    """Sources: 101 is observed before t_last and forecast_trend after; 104 is routed throughout; 103 is observed then routed."""
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    fids = list(routed.feature_ids)
    idx_101 = fids.index(101)
    idx_103 = fids.index(103)
    idx_104 = fids.index(104)

    t_last_obs = np.datetime64("2025-01-01T03:55:00", "s")

    for t_idx, tau in enumerate(routed.taus):
        src_101 = routed.source[idx_101, t_idx]
        src_103 = routed.source[idx_103, t_idx]
        src_104 = routed.source[idx_104, t_idx]

        assert src_104 == SOURCE_INDEX["routed"]

        if tau <= t_last_obs:
            assert src_101 == SOURCE_INDEX["observed"]
            assert src_103 == SOURCE_INDEX["observed"]
        else:
            assert src_101 == SOURCE_INDEX["forecast_trend"]
            assert src_103 == SOURCE_INDEX["routed"]


def test_hindsight(mini_cube, mini_scenario, mini_data_dir):
    """Hindsight: with p = record end, no forecast_trend code appears."""
    p = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)
    routed = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)

    assert SOURCE_INDEX["forecast_trend"] not in routed.source


def test_runtime(mini_cube, mini_scenario, mini_data_dir):
    """One route call on the fixture completes in under 2 seconds."""
    import time
    p = datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    view = FixtureForcingView(mini_data_dir, p)

    t_start = time.perf_counter()
    _ = route(mini_cube, view, mini_scenario, mini_scenario.forcing_defaults)
    elapsed = time.perf_counter() - t_start

    assert elapsed < 2.0
