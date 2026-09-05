"""Tests for boundary forecasting functions."""
from datetime import datetime, timedelta, timezone
import math
import numpy as np
import pandas as pd
import pytest
from flood.engine.boundary import persistence, trend_relax


def test_trend_relax_tau_le_t_last():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    times = [t0 + timedelta(minutes=10 * i) for i in range(6)]
    values = [10.0, 15.0, 20.0, 25.0, 30.0, 35.0]
    s = pd.Series(values, index=pd.DatetimeIndex(times, tz=timezone.utc))

    # Before first index -> holds first value
    assert trend_relax(s, t0 - timedelta(minutes=10), m=1.0) == 10.0

    # Exactly on points
    assert trend_relax(s, times[2], m=1.0) == 20.0

    # Intermediate point
    mid_time = t0 + timedelta(minutes=25)
    assert math.isclose(trend_relax(s, mid_time, m=1.0), 22.5, rel_tol=1e-6)

    # At t_last
    assert math.isclose(trend_relax(s, times[-1], m=1.0), 35.0, rel_tol=1e-6)


def test_trend_relax_d_zero():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    times = [t0 + timedelta(minutes=10 * i) for i in range(4)]
    values = [10.0, 12.0, 14.0, 16.0]
    s = pd.Series(values, index=pd.DatetimeIndex(times, tz=timezone.utc))

    t_last = times[-1]
    # d = 0 (tau == t_last) returns q0
    assert math.isclose(trend_relax(s, t_last, m=1.0), 16.0, rel_tol=1e-6)


def test_trend_relax_asymptote():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    times = [t0 + timedelta(minutes=10 * i) for i in range(7)]  # 0 to 60 min
    # slope = 0.5 per minute
    values = [10.0 + 0.5 * 10 * i for i in range(7)]
    s = pd.Series(values, index=pd.DatetimeIndex(times, tz=timezone.utc))

    t_last = times[-1]
    relax_min = 60
    trend_win = 30
    m = 1.2

    # q0 = 40.0
    # q_prev at t_last - 30 min = values[3] = 25.0
    # r = (40.0 - 25.0) / 30 = 0.5
    # As d -> inf, val -> q0 + m * r * relax_min = 40.0 + 1.2 * 0.5 * 60 = 40.0 + 36.0 = 76.0
    far_future = t_last + timedelta(days=10)
    expected = 40.0 + m * 0.5 * relax_min
    val = trend_relax(s, far_future, m=m, relax_minutes=relax_min, trend_window_minutes=trend_win)
    assert math.isclose(val, expected, rel_tol=1e-4)


def test_trend_relax_m_zero_and_persistence():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    times = [t0 + timedelta(minutes=10 * i) for i in range(4)]
    values = [10.0, 12.0, 14.0, 16.0]
    s = pd.Series(values, index=pd.DatetimeIndex(times, tz=timezone.utc))

    t_last = times[-1]
    for delta_m in [1, 10, 60, 300]:
        t = t_last + timedelta(minutes=delta_m)
        val_m0 = trend_relax(s, t, m=0.0)
        val_pers = persistence(s, t)
        assert math.isclose(val_m0, 16.0, rel_tol=1e-6)
        assert math.isclose(val_pers, 16.0, rel_tol=1e-6)


def test_trend_relax_clipped_to_zero():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    times = [t0, t0 + timedelta(minutes=30)]
    values = [20.0, 5.0]  # Falling rapidly
    s = pd.Series(values, index=pd.DatetimeIndex(times, tz=timezone.utc))

    # r = (5 - 20) / 30 = -0.5
    # With large m or relax, q would go negative, must be clipped to 0
    t = times[-1] + timedelta(minutes=60)
    val = trend_relax(s, t, m=2.0, relax_minutes=60, trend_window_minutes=30)
    assert val >= 0.0
