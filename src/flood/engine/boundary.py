"""Boundary forecast functions for reach boundaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import numpy as np
import pandas as pd


def _get_series_xp_fp(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    xp = getattr(series, "_xp_timestamps", None)
    fp = getattr(series, "_fp_values", None)
    if xp is None:
        xp = np.array([ts.timestamp() for ts in series.index], dtype=np.float64)
        try:
            series._xp_timestamps = xp
        except Exception:
            pass
    if fp is None:
        fp = series.to_numpy(dtype=np.float64)
        try:
            series._fp_values = fp
        except Exception:
            pass
    return xp, fp


def _interp_series(series: pd.Series, t: datetime) -> float:
    """Interpolate series at time t with first value held for t < series.index[0]."""
    n = len(series)
    if n == 0:
        return 0.0
    if n == 1:
        return float(series.iloc[0])

    idx = series.index
    if idx.tz is not None:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        else:
            t = t.astimezone(idx.tz)
    elif t.tzinfo is not None:
        t = t.replace(tzinfo=None)

    xp, fp = _get_series_xp_fp(series)
    tau_s = t.timestamp()

    val = np.interp(tau_s, xp, fp, left=fp[0], right=fp[-1])
    return float(val)


def trend_relax(
    series: pd.Series,
    tau: datetime,
    m: float,
    relax_minutes: int = 60,
    trend_window_minutes: int = 30,
) -> float:
    """Extrapolate boundary discharge using trend relaxation beyond t_last."""
    n = len(series)
    if n == 0:
        return 0.0

    t_last = series.index[-1]
    if t_last.tzinfo is not None:
        if tau.tzinfo is None:
            tau = tau.replace(tzinfo=timezone.utc)
        else:
            tau = tau.astimezone(t_last.tzinfo)
    elif tau.tzinfo is not None:
        tau = tau.replace(tzinfo=None)

    if tau <= t_last:
        return _interp_series(series, tau)

    q0 = float(series.iloc[-1])
    if n == 1:
        return max(0.0, q0)

    t_prev = t_last - timedelta(minutes=trend_window_minutes)
    q_prev = _interp_series(series, t_prev)
    r = (q0 - q_prev) / float(trend_window_minutes)
    d = (tau - t_last).total_seconds() / 60.0

    val = q0 + m * r * float(relax_minutes) * (1.0 - math.exp(-d / float(relax_minutes)))
    return max(0.0, float(val))


def persistence(
    series: pd.Series,
    tau: datetime,
    relax_minutes: int = 60,
    trend_window_minutes: int = 30,
) -> float:
    """Persistence forecast (trend_relax with m = 0)."""
    return trend_relax(
        series,
        tau,
        m=0.0,
        relax_minutes=relax_minutes,
        trend_window_minutes=trend_window_minutes,
    )
