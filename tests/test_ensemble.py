"""Tests for ensemble reduction and time-to-exceedance."""
from datetime import datetime, timezone
import numpy as np
import pytest
from flood.engine.ensemble import reduce_members, time_to_exceedance
from flood.interfaces import MemberFields, MIN_DEPTH_M, TTE_THRESHOLDS_M


def test_reduce_members_basic():
    # 2x2 grid
    d_low = np.array([[0.0, 0.02], [0.10, np.nan]], dtype=np.float32)
    d_mid = np.array([[0.0, 0.05], [0.20, np.nan]], dtype=np.float32)
    d_high = np.array([[0.0, 0.10], [0.30, np.nan]], dtype=np.float32)
    v_mid = np.array([[0.0, 1.0], [2.0, np.nan]], dtype=np.float32)

    low = MemberFields(depth=d_low, velocity=None)
    mid = MemberFields(depth=d_mid, velocity=v_mid)
    high = MemberFields(depth=d_high, velocity=None)

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    state = reduce_members(low, mid, high, p=now, t=now, compute_ms={"test": 1})

    assert state.p == now
    assert state.t == now
    assert state.compute_ms == {"test": 1}

    # Depth copies
    np.testing.assert_allclose(state.depth_low, d_low)
    np.testing.assert_allclose(state.depth_mid, d_mid)
    np.testing.assert_allclose(state.depth_high, d_high)

    # Velocity from mid
    np.testing.assert_allclose(state.velocity_ms, v_mid)

    # hazard_dv = depth_mid * velocity_ms
    expected_hazard = np.array([[0.0, 0.05], [0.40, np.nan]], dtype=np.float32)
    np.testing.assert_allclose(state.hazard_dv, expected_hazard)

    # prob_inundated
    # (0, 0): all 0.0 < 0.03 -> prob 0.0
    # (0, 1): low=0.02 (< 0.03), mid=0.05 (>= 0.03), high=0.10 (>= 0.03) -> 2 / 3
    # (1, 0): all >= 0.03 -> 3 / 3 = 1.0
    # (1, 1): all NaN -> NaN
    expected_prob = np.array([[0.0, 2.0 / 3.0], [1.0, np.nan]], dtype=np.float32)
    np.testing.assert_allclose(state.prob_inundated, expected_prob)


def test_time_to_exceedance_three_frames():
    # Grid of shape (1, 5) with cells:
    # col 0: already deep at min 0 (0.70 m > all thresholds) -> 0 for all thr
    # col 1: rises above 0.15 at min 5, above 0.30 at min 10, never above 0.60
    # col 2: rises above 0.15 at min 10 only
    # col 3: always dry (0.0 m) -> -1 for all thr
    # col 4: always NaN (uncovered) -> NaN for all thr
    frame_0 = np.array([[0.70, 0.10, 0.05, 0.0, np.nan]], dtype=np.float32)
    frame_5 = np.array([[0.80, 0.25, 0.10, 0.0, np.nan]], dtype=np.float32)
    frame_10 = np.array([[0.90, 0.40, 0.20, 0.0, np.nan]], dtype=np.float32)

    series = [(0, frame_0), (5, frame_5), (10, frame_10)]
    tte = time_to_exceedance(series)

    assert tte.shape == (3, 1, 5)
    # Band 0: thr 0.15
    # col 0: min 0, col 1: min 5, col 2: min 10, col 3: -1, col 4: nan
    expected_015 = np.array([[0.0, 5.0, 10.0, -1.0, np.nan]], dtype=np.float32)
    np.testing.assert_allclose(tte[0], expected_015)

    # Band 1: thr 0.30
    # col 0: min 0, col 1: min 10, col 2: -1, col 3: -1, col 4: nan
    expected_030 = np.array([[0.0, 10.0, -1.0, -1.0, np.nan]], dtype=np.float32)
    np.testing.assert_allclose(tte[1], expected_030)

    # Band 2: thr 0.60
    # col 0: min 0, col 1: -1, col 2: -1, col 3: -1, col 4: nan
    expected_060 = np.array([[0.0, -1.0, -1.0, -1.0, np.nan]], dtype=np.float32)
    np.testing.assert_allclose(tte[2], expected_060)
