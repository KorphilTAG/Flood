"""Per-gauge conveyance calibration of the synthetic rating curves.

FIM's synthetic rating curves carry no calibration on most catchments, so stage at a
given discharge is biased, and the same bias slows the kinematic celerity dQ/dA that the
routing uses. NOAA's own pipeline corrects this with a discharge adjustment factor fitted
at USGS gauges and propagated to neighbouring catchments. This module does the same with
the engine's single knob, the Manning n scale: the scaled table has discharge q / s, so
s < 1 raises conveyance.

Fitting: for a gauged reach, observed discharge and gauge height (00060, 00065) are paired
in time; the gauge-height rise above base flow is compared with the table's stage at the
same discharge, and s is chosen to minimise the squared stage error over the flood range.

Propagation: reaches on a levelpath with fitted gauges take the distance-weighted
interpolation between the bracketing gauges (nearest gauge beyond the ends); reaches on an
ungauged levelpath take the scale of the first calibrated reach reached walking
downstream; everything else keeps the scenario's global scale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from flood.engine.rating import stage_from_q

SCALE_GRID = np.round(np.arange(0.2, 2.0001, 0.01), 2)
# A gauge is trusted only if its paired record actually covers a flood: enough samples,
# a real discharge range and a real rise. Gauges that stalled or dropped out during the
# event (their pairs stop at base flow) are left unfitted and take the interpolated scale.
MIN_SAMPLES = 12
MIN_Q_MAX_CMS = 50.0
MIN_RISE_M = 1.0


@dataclass
class GaugeFit:
    site: str
    feature_id: int
    branch_id: int
    cidx: int
    scale: float
    rmse_m: float
    n_samples: int
    q_max_cms: float
    rise_max_m: float
    fitted: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "feature_id": int(self.feature_id),
            "branch_id": int(self.branch_id),
            "cidx": int(self.cidx),
            "scale": float(self.scale),
            "rmse_m": float(self.rmse_m),
            "n_samples": int(self.n_samples),
            "q_max_cms": float(self.q_max_cms),
            "rise_max_m": float(self.rise_max_m),
            "fitted": bool(self.fitted),
            "reason": self.reason,
        }


@dataclass
class ConveyanceField:
    """Per-branch, per-catchment Manning n scale arrays plus the fits that produced them."""

    default: float
    by_branch: dict[int, np.ndarray] = field(default_factory=dict)
    by_reach: dict[int, float] = field(default_factory=dict)
    fits: list[GaugeFit] = field(default_factory=list)

    def scale_for_branch(self, branch_id: int) -> np.ndarray | float:
        return self.by_branch.get(int(branch_id), self.default)

    def as_dict(self) -> dict[str, Any]:
        return {
            "default_scale": self.default,
            "gauges": [f.as_dict() for f in self.fits],
            "reach_scales": {str(k): float(v) for k, v in sorted(self.by_reach.items())},
        }


def _pair_observations(usgs: pd.DataFrame, site: str) -> pd.DataFrame:
    df = usgs[usgs["site"].astype(str) == str(site)]
    q = df[df["parameter"] == "00060"][["valid_time", "value_si"]].rename(columns={"value_si": "q"})
    h = df[df["parameter"] == "00065"][["valid_time", "value_si"]].rename(columns={"value_si": "gh"})
    if q.empty or h.empty:
        return pd.DataFrame(columns=["valid_time", "q", "gh"])
    merged = q.merge(h, on="valid_time", how="inner").dropna()
    return merged.sort_values("valid_time").reset_index(drop=True)


def fit_gauge_scale(
    rt: Any,
    cidx: int,
    q: np.ndarray,
    gh: np.ndarray,
    min_fraction_of_peak: float = 0.03,
    min_q_cms: float = 2.0,
) -> tuple[float, float, int, float, float, bool, str]:
    """Fit the Manning n scale for one catchment from paired discharge and gauge height.

    Returns (scale, rmse_m, n_samples, q_max, rise_max, fitted, reason).
    """
    q = np.asarray(q, dtype=np.float64)
    gh = np.asarray(gh, dtype=np.float64)
    if q.size < 10:
        return 1.0, float("nan"), int(q.size), float(np.nanmax(q) if q.size else 0.0), 0.0, False, "fewer than 10 samples"
    q_max = float(np.nanmax(q))
    # Base state: median gauge height and discharge over the lowest tenth of flows. The
    # observed rise is measured from that gauge height, so the table's stage is measured
    # from its own stage at the same base discharge.
    low = q <= np.nanpercentile(q, 10)
    gh_base = float(np.nanmedian(gh[low]))
    q_base = float(np.nanmedian(q[low]))
    rise = gh - gh_base
    rise_max = float(np.nanmax(rise)) if rise.size else 0.0
    thr = max(min_q_cms, min_fraction_of_peak * q_max)
    sel = (q >= thr) & np.isfinite(rise)
    n = int(sel.sum())
    if q_max < MIN_Q_MAX_CMS or rise_max < MIN_RISE_M:
        return 1.0, float("nan"), n, q_max, rise_max, False, f"record covers no flood (q_max {q_max:.0f} cms, rise {rise_max:.1f} m)"
    if n < MIN_SAMPLES:
        return 1.0, float("nan"), n, q_max, rise_max, False, f"only {n} flood-range samples"
    qs = q[sel]
    rs = rise[sel]
    # Weight toward the high flows that decide the map.
    w = np.sqrt(qs / q_max)
    best_s, best_err = 1.0, float("inf")
    cidx_arr = np.full(qs.size, int(cidx), dtype=np.int64)

    def _table_rise(s: float) -> np.ndarray:
        st, _ = stage_from_q(rt, cidx_arr, (qs * s).astype(np.float32))
        st0, _ = stage_from_q(rt, np.array([int(cidx)]), np.array([q_base * s], dtype=np.float32))
        return st.astype(np.float64) - float(st0[0])

    for s in SCALE_GRID:
        err = float(np.sum(w * (_table_rise(float(s)) - rs) ** 2) / np.sum(w))
        if err < best_err:
            best_err, best_s = err, float(s)
    rmse = float(np.sqrt(np.mean((_table_rise(best_s) - rs) ** 2)))
    at_edge = best_s <= SCALE_GRID[0] + 1e-9 or best_s >= SCALE_GRID[-1] - 1e-9
    return best_s, rmse, n, q_max, rise_max, True, "fit at grid edge" if at_edge else ""


def fit_gauge_scales(cube: Any, usgs: pd.DataFrame, scenario: Any) -> list[GaugeFit]:
    """Fit one scale per scenario gauge that has paired observations and a rating row."""
    network = cube.network.set_index("feature_id")
    fits: list[GaugeFit] = []
    for g in scenario.hydrology.gauges:
        fid = int(g.feature_id)
        site = str(g.site)
        if fid not in network.index:
            fits.append(GaugeFit(site, fid, -1, -1, 1.0, float("nan"), 0, 0.0, 0.0, False, "reach not in network"))
            continue
        row = network.loc[fid]
        bid = int(row["preferred_branch"])
        cidx = int(row["representative_cidx"])
        if cidx < 0:
            fits.append(GaugeFit(site, fid, bid, cidx, 1.0, float("nan"), 0, 0.0, 0.0, False, "no rating row"))
            continue
        rt = cube.branch(bid).rating
        pairs = _pair_observations(usgs, site)
        s, rmse, n, q_max, rise_max, ok, reason = fit_gauge_scale(rt, cidx, pairs["q"].to_numpy(), pairs["gh"].to_numpy())
        fits.append(GaugeFit(site, fid, bid, cidx, s, rmse, n, q_max, rise_max, ok, reason))
    return fits


def propagate_scales(network: pd.DataFrame, gauge_scale_by_fid: Mapping[int, float], default: float) -> dict[int, float]:
    """Assign a scale to every reach: along-levelpath interpolation, then downstream inheritance."""
    net = network.set_index("feature_id")
    fids = [int(f) for f in net.index]
    to = {int(f): int(net.loc[f, "to_feature_id"]) for f in fids}
    length = {int(f): float(net.loc[f, "length_m"]) for f in fids}
    lp = {int(f): int(net.loc[f, "levelpath_id"]) for f in fids}

    # Position of each reach along its levelpath: distance from the levelpath outlet to the
    # reach's downstream end, following to_feature_id while the levelpath stays the same.
    pos: dict[int, float] = {}

    def _position(f: int) -> float:
        if f in pos:
            return pos[f]
        chain = []
        cur = f
        while cur in to and cur not in pos:
            chain.append(cur)
            nxt = to[cur]
            if nxt not in lp or lp[nxt] != lp[cur]:
                break
            cur = nxt
        base = pos.get(cur, 0.0) if cur != chain[-1] else 0.0
        # Walk back up the chain assigning cumulative distance.
        acc = base + (length[cur] if cur != chain[-1] else 0.0)
        for node in reversed(chain):
            if node == cur and cur in pos:
                continue
            pos[node] = acc
            acc += length[node]
        return pos[f]

    for f in fids:
        _position(f)

    scales: dict[int, float] = {}
    by_lp: dict[int, list[int]] = {}
    for f in fids:
        by_lp.setdefault(lp[f], []).append(f)
    for lp_id, members in by_lp.items():
        gauged = [(pos[f], float(gauge_scale_by_fid[f])) for f in members if f in gauge_scale_by_fid]
        if not gauged:
            continue
        gauged.sort()
        xs = np.array([x for x, _ in gauged])
        ys = np.array([s for _, s in gauged])
        for f in members:
            scales[f] = float(np.interp(pos[f], xs, ys))  # nearest gauge beyond the ends

    # Ungauged levelpaths inherit the first calibrated reach downstream.
    for f in fids:
        if f in scales:
            continue
        cur, seen = f, set()
        found = None
        while cur in to and cur not in seen:
            seen.add(cur)
            nxt = to[cur]
            if nxt in scales:
                found = scales[nxt]
                break
            cur = nxt
        scales[f] = found if found is not None else default
    return scales


def build_conveyance_field(cube: Any, usgs: pd.DataFrame, scenario: Any, default: float) -> ConveyanceField:
    """Fit the gauges, propagate along the network, and expand to per-branch catchment arrays."""
    fits = fit_gauge_scales(cube, usgs, scenario)
    gauge_scale_by_fid = {f.feature_id: f.scale for f in fits if f.fitted}
    by_reach = propagate_scales(cube.network, gauge_scale_by_fid, default)
    by_branch: dict[int, np.ndarray] = {}
    for branch in cube.branches:
        rt = branch.rating
        arr = np.full(len(rt.feature_id), float(default), dtype=np.float32)
        for i, fid in enumerate(rt.feature_id):
            s = by_reach.get(int(fid))
            if s is not None:
                arr[i] = s
        by_branch[int(branch.branch_id)] = arr
    return ConveyanceField(default=float(default), by_branch=by_branch, by_reach=by_reach, fits=fits)
