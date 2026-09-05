"""Ensemble reduction and time-to-exceedance calculation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
import numpy as np

from flood.interfaces import (
    MemberFields,
    MIN_DEPTH_M,
    StateArrays,
    TTE_THRESHOLDS_M,
)


def reduce_members(
    low: MemberFields,
    mid: MemberFields,
    high: MemberFields,
    p: datetime | None = None,
    t: datetime | None = None,
    compute_ms: dict[str, int] | None = None,
) -> StateArrays:
    """Reduce ensemble member fields to contract 1 StateArrays."""
    if t is None:
        t = datetime.now(timezone.utc)
    if compute_ms is None:
        compute_ms = {}

    d_low = low.depth.astype(np.float32)
    d_mid = mid.depth.astype(np.float32)
    d_high = high.depth.astype(np.float32)

    if mid.velocity is not None:
        v_ms = mid.velocity.astype(np.float32)
    else:
        v_ms = np.zeros_like(d_mid, dtype=np.float32)

    # hazard_dv = depth_mid * velocity_ms
    hazard_dv = (d_mid * v_ms).astype(np.float32)

    # prob_inundated = mean(depth_m >= MIN_DEPTH_M over members) as float32
    # NaN propagated where all members are NaN
    depths = np.stack([d_low, d_mid, d_high], axis=0)
    all_nan = np.all(np.isnan(depths), axis=0)

    inundated = (depths >= MIN_DEPTH_M).astype(np.float32)
    prob = np.mean(inundated, axis=0).astype(np.float32)
    prob_inundated = np.where(all_nan, np.nan, prob).astype(np.float32)

    return StateArrays(
        p=p,
        t=t,
        depth_mid=d_mid,
        depth_low=d_low,
        depth_high=d_high,
        velocity_ms=v_ms,
        hazard_dv=hazard_dv,
        prob_inundated=prob_inundated,
        compute_ms=compute_ms,
    )


def time_to_exceedance(
    depth_series: Iterable[tuple[int, np.ndarray]],
) -> np.ndarray:
    """Compute time-to-exceedance raster across thresholds (0.15, 0.30, 0.60 m).

    Returns float32 array of shape [3, H, W].
    Value is first minutes with depth > threshold, 0 if at minute 0, -1 if never,
    and NaN where cell was never covered.
    """
    thresholds = TTE_THRESHOLDS_M
    tte: np.ndarray | None = None
    exceeded: np.ndarray | None = None
    covered: np.ndarray | None = None

    for m, depth in depth_series:
        depth = depth.astype(np.float32)
        if tte is None:
            h, w = depth.shape
            tte = np.full((len(thresholds), h, w), -1.0, dtype=np.float32)
            exceeded = np.zeros((len(thresholds), h, w), dtype=bool)
            covered = np.zeros((h, w), dtype=bool)

        covered |= ~np.isnan(depth)

        for i, thr in enumerate(thresholds):
            mask = (depth > thr) & (~exceeded[i]) & (~np.isnan(depth))
            if np.any(mask):
                tte[i, mask] = float(m)
                exceeded[i, mask] = True

    if tte is None or covered is None:
        raise ValueError("depth_series must yield at least one frame")

    tte[:, ~covered] = np.nan
    return tte
