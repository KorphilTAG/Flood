"""Gauge conveyance calibration: fit recovery, quality gates, and propagation along the network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from flood.engine.calibration import (
    MIN_Q_MAX_CMS,
    SCALE_GRID,
    fit_gauge_scale,
    propagate_scales,
)
from flood.engine.rating import stage_from_q


def _synthetic_pairs(rt, cidx: int, true_scale: float, n: int = 60, q_top_fraction: float = 0.6):
    """Discharge and gauge height generated from the table itself at a known scale."""
    q_max = float(rt.q_cms[cidx, -1]) * q_top_fraction
    q = np.linspace(0.5, q_max, n)
    stage, _ = stage_from_q(rt, np.full(n, cidx), (q * true_scale).astype(np.float32))
    gh = 3.0 + stage.astype(np.float64)  # arbitrary datum
    return q, gh


def test_fit_recovers_known_scale(mini_cube):
    rt = mini_cube.branch(9).rating
    for true_scale in (0.5, 0.8, 1.3):
        s, rmse, n, q_max, rise_max, fitted, reason = fit_gauge_scale(rt, 1, *_synthetic_pairs(rt, 1, true_scale))
        assert fitted, reason
        assert abs(s - true_scale) <= 0.02
        assert rmse < 0.05
        assert n >= 12


def test_fit_rejects_records_without_a_flood(mini_cube):
    rt = mini_cube.branch(9).rating
    q = np.linspace(0.1, MIN_Q_MAX_CMS / 4, 40)
    gh = 2.0 + 0.01 * q
    s, _, _, _, _, fitted, reason = fit_gauge_scale(rt, 1, q, gh)
    assert not fitted
    assert s == 1.0
    assert "no flood" in reason


def test_fit_flags_grid_edge(mini_cube):
    rt = mini_cube.branch(9).rating
    q, gh = _synthetic_pairs(rt, 1, float(SCALE_GRID[0]) / 2.0)
    s, _, _, _, _, fitted, reason = fit_gauge_scale(rt, 1, q, gh)
    assert fitted
    assert s == pytest.approx(float(SCALE_GRID[0]))
    assert reason == "fit at grid edge"


def _chain_network():
    # 1 -> 2 -> 3 -> 4 -> 5 -> outlet on one levelpath; tributary 10 -> 3 on another; 20 isolated.
    rows = [
        (1, 2, 100, 1000.0), (2, 3, 100, 1000.0), (3, 4, 100, 1000.0), (4, 5, 100, 1000.0), (5, 0, 100, 1000.0),
        (10, 3, 200, 500.0),
        (20, 0, 300, 800.0),
    ]
    return pd.DataFrame(rows, columns=["feature_id", "to_feature_id", "levelpath_id", "length_m"])


def test_propagation_interpolates_and_inherits():
    net = _chain_network()
    scales = propagate_scales(net, {1: 0.4, 5: 0.8}, default=0.6)
    # Interpolated by distance along the levelpath between the two gauges.
    assert scales[1] == pytest.approx(0.4)
    assert scales[5] == pytest.approx(0.8)
    assert scales[3] == pytest.approx(0.6, abs=0.01)
    assert 0.4 < scales[2] < scales[3] < scales[4] < 0.8
    # Ungauged tributary inherits the first calibrated reach downstream.
    assert scales[10] == pytest.approx(scales[3])
    # Isolated levelpath keeps the default.
    assert scales[20] == pytest.approx(0.6)


def test_propagation_beyond_gauges_is_nearest():
    net = _chain_network()
    scales = propagate_scales(net, {3: 0.5}, default=1.0)
    assert all(scales[f] == pytest.approx(0.5) for f in (1, 2, 3, 4, 5, 10))
    assert scales[20] == pytest.approx(1.0)
