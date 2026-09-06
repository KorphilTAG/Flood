"""Muskingum-Cunge reach routing with gauge controls and boundary forecasts."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Sequence
import numpy as np
import pandas as pd

from flood.contracts.models import ForcingConfig, Scenario
from flood.engine.boundary import _interp_series, trend_relax
from flood.engine.cube import HandCube
from flood.engine.rating import apply_n_scale
from flood.interfaces import (
    ForcingView,
    MEMBERS,
    RatingTable,
    RoutedSeries,
    SOURCE_INDEX,
    STEP_MINUTES,
)


# Module caches are keyed by object identity and store the keyed object alongside the
# value, so a recycled id() after garbage collection can never return a stale entry.
_CELERITY_CACHE: dict[tuple[int, int], tuple[RatingTable, np.ndarray]] = {}
_SCALED_RATING_CACHE: dict[tuple, tuple[RatingTable, object, RatingTable]] = {}
_AREA_CACHE: dict[tuple[int, int], tuple[RatingTable, np.ndarray, np.ndarray]] = {}


def _scaled_rating(rt: RatingTable, n_scale: float | np.ndarray) -> RatingTable:
    """Rating table with discharge divided by the Manning n scale, cached per table and scale.

    The scale multiplies conveyance, so both stage (in mapping) and kinematic celerity
    dQ/dA (here) respond consistently. n_scale is a scalar or a per-catchment array.
    Cached so the celerity cache keyed by table identity keeps working across route calls.
    """
    scalar = np.ndim(n_scale) == 0
    if scalar and float(n_scale) == 1.0:
        return rt
    key: tuple = (id(rt), float(n_scale)) if scalar else (id(rt), id(n_scale))
    entry = _SCALED_RATING_CACHE.get(key)
    if entry is not None and entry[0] is rt and (scalar or entry[1] is n_scale):
        return entry[2]
    scaled = dataclasses.replace(rt, q_cms=apply_n_scale(rt.q_cms, n_scale))
    _SCALED_RATING_CACHE[key] = (rt, n_scale, scaled)
    return scaled


def _area_of_q(rt: RatingTable, cidx: int, q: float) -> float:
    """Wetted area at discharge q from the table row (linear in the table)."""
    key = (id(rt), cidx)
    entry = _AREA_CACHE.get(key)
    if entry is None or entry[0] is not rt:
        entry = (rt, rt.q_cms[cidx], rt.wet_area_m2[cidx])
        _AREA_CACHE[key] = entry
    return float(np.interp(q, entry[1], entry[2]))


# Kinematic celerity of a wide channel with Manning friction is c = (5/3) V. FIM's synthetic
# rating curves lump channel and floodplain into one section, so on the floodplain their
# tangent dQ/dA falls to about V or below while the conveying channel still moves the
# wave at (5/3) V; observed fronts on the reference corridor travel at 2.5 to 3 m/s where
# the tables give 1 to 2. The wide-channel value is therefore used as a floor.
KINEMATIC_BETA = 5.0 / 3.0


def kinematic_celerity(rt: RatingTable, cidx: int, q: float) -> float:
    """Celerity at discharge q: the larger of the table's dQ/dA and the Manning wide-channel (5/3) Q/A."""
    c = _celerity(rt, cidx, q)
    a = _area_of_q(rt, cidx, q)
    if a > 0.0 and q > 0.0:
        c = max(c, KINEMATIC_BETA * q / a)
    return float(np.clip(c, 0.1, 10.0))


def _shock_celerity(rt: RatingTable, cidx: int, q_hi: float, q_lo: float) -> float | None:
    """Kinematic shock speed (Q_hi - Q_lo) / (A_hi - A_lo) between two flow states.

    On a rising limb the leading face of a flood steepens into a kinematic shock
    (Lighthill and Whitham 1955); its speed is this secant of the rating curve, not the
    local dQ/dA that the tangent celerity gives at the low flow ahead of the front.
    """
    a_hi = _area_of_q(rt, cidx, q_hi)
    a_lo = _area_of_q(rt, cidx, q_lo)
    if a_hi - a_lo <= 1e-6:
        return None
    return (q_hi - q_lo) / (a_hi - a_lo)


# Scalar rating helpers. These deliberately duplicate the definitions in
# flood.engine.rating (vectorised) because the routing loop calls them once per
# reach per time step per member; wrapping each call in numpy arrays made the
# loop about ten times slower. tests/test_routing.py::test_scalar_helpers_match_rating
# pins them to the vectorised implementation.
def _stage_from_q(rt: RatingTable, cidx: int, q: float) -> tuple[float, bool]:
    if q <= 0.0:
        return float(rt.stage_m[cidx, 0]), False
    q_row = rt.q_cms[cidx]
    stage_row = rt.stage_m[cidx]
    if q >= q_row[-1]:
        return float(stage_row[-1]), True
    return float(np.interp(q, q_row, stage_row)), False


def _wet_area(rt: RatingTable, cidx: int, stage: float) -> float:
    return float(np.interp(stage, rt.stage_m[cidx], rt.wet_area_m2[cidx]))


def _top_width(rt: RatingTable, cidx: int, stage: float) -> float:
    return float(np.interp(stage, rt.stage_m[cidx], rt.top_width_m[cidx]))


def _celerity(rt: RatingTable, cidx: int, q: float) -> float:
    q_row = rt.q_cms[cidx]
    key = (id(rt), cidx)
    entry = _CELERITY_CACHE.get(key)
    if entry is None or entry[0] is not rt:
        a_row = rt.wet_area_m2[cidx]
        entry = (rt, np.gradient(q_row, a_row))
        _CELERITY_CACHE[key] = entry
    dq_da = entry[1]
    c = float(np.interp(q, q_row, dq_da))
    return float(np.clip(c, 0.1, 10.0))


def mc_params(
    rt: RatingTable | None,
    cidx: int,
    q_ref: float,
    length_m: float,
    slope: float,
    dt_s: float,
    q_out_prev: float | None = None,
) -> tuple[float, float]:
    """Compute Muskingum-Cunge parameters (K, X) from the rating table or a fallback.

    q_ref is the reference discharge (the three-point average of the cell's known flows in
    the variable-parameter method). When q_out_prev is given and the cell is on a rising
    limb (q_ref clearly above the previous outflow) the celerity is the kinematic shock
    speed between the two states instead of the tangent celerity at q_ref, so the front
    travels at the speed of the flood behind it rather than of the trickle ahead of it.
    """
    if rt is None or cidx == -1:
        c = (1.0 / 0.06) * (1.0 ** (2.0 / 3.0)) * math.sqrt(max(slope, 1e-6)) * (5.0 / 3.0)
        B = 10.0
    else:
        c = kinematic_celerity(rt, cidx, q_ref)
        if q_out_prev is not None and q_ref > q_out_prev + max(0.5, 0.05 * q_out_prev):
            c_shock = _shock_celerity(rt, cidx, q_ref, max(q_out_prev, 0.0))
            if c_shock is not None:
                c = max(c, c_shock)
        stage, _ = _stage_from_q(rt, cidx, q_ref)
        B = _top_width(rt, cidx, stage)

    if B <= 0.0:
        B = 10.0
    c = float(np.clip(c, 0.1, 10.0))

    K = length_m / c if c > 0.0 else 0.0
    denom = B * slope * c * length_m
    if denom > 0.0:
        X_val = 0.5 * (1.0 - q_ref / denom)
    else:
        X_val = 0.0
    X = float(np.clip(X_val, 0.0, 0.5))
    return K, X


def mc_step(
    q_in_prev: float,
    q_in_next: float,
    q_out_prev: float,
    K: float,
    X: float,
    dt: float,
) -> float:
    """Single Muskingum-Cunge time step with sub-stepping if dt > 2K(1-X)."""
    limit = 2.0 * K * (1.0 - X)
    if limit <= 1e-9:
        return max(0.0, float(q_in_next))

    if dt > limit:
        n = math.ceil(dt / limit)
        sub_dt = dt / float(n)
        denom = 2.0 * K * (1.0 - X) + sub_dt
        c0 = (sub_dt - 2.0 * K * X) / denom
        c1 = (sub_dt + 2.0 * K * X) / denom
        c2 = (2.0 * K * (1.0 - X) - sub_dt) / denom

        cur_q_out = q_out_prev
        for i in range(1, n + 1):
            frac_prev = (i - 1) / float(n)
            frac_next = i / float(n)
            sub_in_prev = q_in_prev + frac_prev * (q_in_next - q_in_prev)
            sub_in_next = q_in_prev + frac_next * (q_in_next - q_in_prev)
            cur_q_out = max(0.0, c0 * sub_in_next + c1 * sub_in_prev + c2 * cur_q_out)
        return float(cur_q_out)

    denom = limit + dt
    c0 = (dt - 2.0 * K * X) / denom
    c1 = (dt + 2.0 * K * X) / denom
    c2 = (limit - dt) / denom
    res = c0 * q_in_next + c1 * q_in_prev + c2 * q_out_prev
    return max(0.0, float(res))


def _topological_order(
    network: pd.DataFrame,
    inferred_reach_set: set[int],
) -> list[int]:
    """Compute topological reach order (upstream to downstream) with cycle detection."""
    fids = network["feature_id"].tolist()
    fid_set = set(fids)

    in_degree: dict[int, int] = {fid: 0 for fid in fids}
    downstream: dict[int, list[int]] = {fid: [] for fid in fids}

    for _, row in network.iterrows():
        u = int(row["feature_id"])
        v = int(row["to_feature_id"])
        if v != 0 and v in fid_set:
            downstream[u].append(v)
            in_degree[v] += 1

    # Ready queue: prioritize inferred reaches
    ready = [fid for fid in fids if in_degree[fid] == 0]
    ready.sort(key=lambda fid: (0 if fid in inferred_reach_set else 1, fid))

    order: list[int] = []
    while ready:
        curr = ready.pop(0)
        order.append(curr)
        for ds in downstream[curr]:
            in_degree[ds] -= 1
            if in_degree[ds] == 0:
                ready.append(ds)
                ready.sort(key=lambda fid: (0 if fid in inferred_reach_set else 1, fid))

    if len(order) < len(fids):
        raise ValueError("Cycle detected in reach network")
    return order


def route(
    cube: HandCube,
    view: ForcingView,
    scenario: Scenario,
    config: ForcingConfig,
    members: Sequence[str] = MEMBERS,
    max_horizon_minutes: int = 360,
    warmup_minutes: int = 360,
    n_scale_field: Any = None,
) -> RoutedSeries:
    """Route flow through the reach network producing a RoutedSeries."""
    p = view.p
    p_tz = p.tzinfo if p.tzinfo is not None else timezone.utc
    if p.tzinfo is None:
        p = p.replace(tzinfo=timezone.utc)

    rec_start = pd.to_datetime(scenario.hydrology.record.start).to_pydatetime()
    if rec_start.tzinfo is None:
        rec_start = rec_start.replace(tzinfo=p_tz)
    else:
        rec_start = rec_start.astimezone(p_tz)

    rec_end = pd.to_datetime(scenario.hydrology.record.end).to_pydatetime()
    if rec_end.tzinfo is None:
        rec_end = rec_end.replace(tzinfo=p_tz)
    else:
        rec_end = rec_end.astimezone(p_tz)

    is_hindsight = (p >= rec_end)

    if is_hindsight:
        warmup_start = rec_start
    else:
        warmup_start = p - timedelta(minutes=warmup_minutes)
        if warmup_start < rec_start:
            warmup_start = rec_start

    t_end = p + timedelta(minutes=max_horizon_minutes)
    if t_end > rec_end:
        t_end = rec_end

    dt_minutes = float(config.routing.dt_minutes)
    dt_s = dt_minutes * 60.0
    roughness = getattr(config, "roughness", None)
    n_scale_default = float(roughness.manning_n_scale) if roughness is not None else 1.0

    def _branch_scale(branch_id: int):
        if n_scale_field is not None:
            return n_scale_field.scale_for_branch(branch_id)
        return n_scale_default
    total_seconds = int(round((t_end - warmup_start).total_seconds()))
    step_seconds = int(round(dt_s))
    num_steps = max(1, total_seconds // step_seconds + 1)
    sim_times = [warmup_start + timedelta(seconds=i * step_seconds) for i in range(num_steps)]

    # Output downsampled indices (exact samples on 5-minute grid)
    downsample_indices = [
        i for i, t in enumerate(sim_times)
        if (t.minute % STEP_MINUTES == 0 and t.second == 0)
    ]
    output_taus = np.array(
        [np.datetime64(sim_times[i].replace(tzinfo=None), "s") for i in downsample_indices],
        dtype="datetime64[s]",
    )

    network = cube.network
    n_reaches = len(network)
    feature_ids = network["feature_id"].to_numpy(dtype=np.int64)
    fid_to_idx = {int(fid): idx for idx, fid in enumerate(feature_ids)}

    # Upstream mapping
    upstream_indices: list[list[int]] = [[] for _ in range(n_reaches)]
    for _, row in network.iterrows():
        u = int(row["feature_id"])
        v = int(row["to_feature_id"])
        if v != 0 and v in fid_to_idx:
            upstream_indices[fid_to_idx[v]].append(fid_to_idx[u])

    # Gauge configuration
    gauge_role_by_site = {g.site: g.role for g in scenario.hydrology.gauges}
    reach_gauge_site: list[str | None] = [None] * n_reaches
    reach_gauge_role: list[str | None] = [None] * n_reaches
    for idx, row in network.iterrows():
        site = row["gauge_site"]
        if pd.notna(site):
            site_str = str(site)
            role = gauge_role_by_site.get(site_str)
            if role in ("boundary", "interior"):
                reach_gauge_site[idx] = site_str
                reach_gauge_role[idx] = role

    # Pre-fetch observations and their t_last
    obs_series_by_site: dict[str, pd.Series] = {}
    t_last_by_site: dict[str, datetime | None] = {}
    for g in scenario.hydrology.gauges:
        s = view.obs_q(g.site)
        obs_series_by_site[g.site] = s
        if len(s) > 0:
            t_max = s.index.max().to_pydatetime()
            if t_max.tzinfo is None:
                t_max = t_max.replace(tzinfo=p_tz)
            else:
                t_max = t_max.astimezone(p_tz)
            t_last_by_site[g.site] = t_max
        else:
            t_last_by_site[g.site] = None

    # Junction inference configuration
    use_ji = config.state_estimation.use_junction_inferences
    ji_by_reach: dict[int, any] = {}
    inferred_reach_set: set[int] = set()
    if use_ji:
        for ji in scenario.hydrology.junction_inferences:
            ji_by_reach[ji.inferred_reach] = ji
            inferred_reach_set.add(ji.inferred_reach)

    # Topological order
    topological_order = _topological_order(network, inferred_reach_set)
    topological_indices = [fid_to_idx[fid] for fid in topological_order]

    # Pre-extract reach hydraulic parameters
    reach_params = []
    for idx in range(n_reaches):
        row = network.iloc[idx]
        length_m = float(row["length_m"])
        slope = float(row["slope"])
        pref_branch = int(row["preferred_branch"])
        cidx = int(row["representative_cidx"])
        rt: RatingTable | None = None
        if cidx != -1:
            try:
                b = cube.branch(pref_branch)
                rt = _scaled_rating(b.rating, _branch_scale(pref_branch))
            except KeyError:
                cidx = -1
        reach_params.append((rt, cidx, length_m, slope))

    # Reaches without a rating row (connectors HAND has no catchment for) borrow the
    # hydraulics of the nearest rated reach, upstream first, then downstream. Left to the
    # slope-only fallback, a 400 m connector with a recorded slope of zero becomes a
    # 0.1 m/s reservoir that delays and flattens the whole flood wave behind it.
    downstream_index: dict[int, int] = {}
    for idx in range(n_reaches):
        for u in upstream_indices[idx]:
            downstream_index[u] = idx
    for idx in range(n_reaches):
        rt, cidx, length_m, slope = reach_params[idx]
        if cidx != -1:
            continue
        donor = None
        frontier, seen = list(upstream_indices[idx]), {idx}
        while frontier and donor is None:
            u = frontier.pop(0)
            if u in seen:
                continue
            seen.add(u)
            if reach_params[u][1] != -1:
                donor = u
            else:
                frontier.extend(upstream_indices[u])
        d = downstream_index.get(idx)
        while donor is None and d is not None and d not in seen:
            seen.add(d)
            if reach_params[d][1] != -1:
                donor = d
            d = downstream_index.get(d)
        if donor is not None:
            d_rt, d_cidx, _, d_slope = reach_params[donor]
            reach_params[idx] = (d_rt, d_cidx, length_m, slope if slope > 1e-4 else d_slope)

    relax_min = float(config.boundary_forecast.relax_minutes)
    trend_win_min = int(config.boundary_forecast.trend_window_minutes)

    # Precompute lateral inflows for speed
    qlat_cache = np.zeros((n_reaches, num_steps), dtype=np.float32)
    for step_i, tau in enumerate(sim_times):
        for idx in range(n_reaches):
            fid = int(feature_ids[idx])
            qlat_cache[idx, step_i] = float(view.qlat(fid, tau))

    qlat_src_fn = getattr(view, "qlat_source", None)

    q_members = np.zeros((len(members), n_reaches, len(downsample_indices)), dtype=np.float32)
    source_mid = np.zeros((n_reaches, len(downsample_indices)), dtype=np.int8)

    for m_idx, member_name in enumerate(members):
        if hasattr(config.boundary_forecast.members, member_name):
            m_val = float(getattr(config.boundary_forecast.members, member_name))
        else:
            m_val = float(config.boundary_forecast.members[member_name])

        sim_q_out = np.zeros((n_reaches, num_steps), dtype=np.float32)
        sim_q_in = np.zeros((n_reaches, num_steps), dtype=np.float32)
        sim_uncontrolled = np.zeros((n_reaches, num_steps), dtype=np.float32)
        sim_source = np.zeros((n_reaches, num_steps), dtype=np.int8)

        # Track history for junction inferences
        ji_history: dict[int, list[tuple[datetime, float]]] = {
            fid: [] for fid in inferred_reach_set
        }
        ji_series_cache: dict[int, pd.Series | None] = {}
        interior_bias: dict[int, float] = {}

        for step_i, tau in enumerate(sim_times):
            for idx in topological_indices:
                fid = int(feature_ids[idx])
                up_idxs = upstream_indices[idx]
                inflow = float(qlat_cache[idx, step_i])
                if up_idxs:
                    for u in up_idxs:
                        inflow += float(sim_q_out[u, step_i])
                sim_q_in[idx, step_i] = inflow

                rt, cidx, length_m, slope = reach_params[idx]

                if step_i == 0:
                    routed_val = inflow
                else:
                    q_in_prev = float(sim_q_in[idx, step_i - 1])
                    q_out_prev = float(sim_uncontrolled[idx, step_i - 1])
                    # Three-point reference discharge (variable-parameter Muskingum-Cunge);
                    # the shock branch inside mc_params takes over on rising limbs.
                    q_ref = max((q_in_prev + inflow + q_out_prev) / 3.0, 1e-4)
                    K, X = mc_params(rt, cidx, q_ref, length_m, slope, dt_s, q_out_prev=q_out_prev)
                    routed_val = mc_step(q_in_prev, inflow, q_out_prev, K, X, dt_s)

                sim_uncontrolled[idx, step_i] = routed_val

                # Controls / Inferences
                if fid in ji_by_reach:
                    ji = ji_by_reach[fid]
                    t_eval_ds = tau + timedelta(minutes=ji.travel_time_minutes)
                    s_ds = obs_series_by_site.get(ji.downstream_gauge)
                    t_last_ds = t_last_by_site.get(ji.downstream_gauge)

                    all_obs_exist = False
                    if s_ds is not None and len(s_ds) > 0 and t_last_ds is not None and t_eval_ds <= t_last_ds:
                        all_obs_exist = True
                        for sg in ji.subtract_gauges:
                            s_sg = obs_series_by_site.get(sg)
                            t_last_sg = t_last_by_site.get(sg)
                            if s_sg is None or len(s_sg) == 0 or t_last_sg is None or tau > t_last_sg:
                                all_obs_exist = False
                                break

                    if all_obs_exist:
                        ds_val = _interp_series(s_ds, t_eval_ds)
                        sub_sum = sum(
                            _interp_series(obs_series_by_site[sg], tau)
                            for sg in ji.subtract_gauges
                        )
                        val = max(0.0, ds_val - sub_sum)
                        sim_q_out[idx, step_i] = val
                        sim_source[idx, step_i] = SOURCE_INDEX["mass_balance"]
                        ji_history[fid].append((tau, val))
                    elif is_hindsight:
                        ds_val = _interp_series(s_ds, t_eval_ds) if s_ds is not None else 0.0
                        sub_sum = sum(
                            _interp_series(obs_series_by_site[sg], tau)
                            for sg in ji.subtract_gauges
                        )
                        val = max(0.0, ds_val - sub_sum)
                        sim_q_out[idx, step_i] = val
                        sim_source[idx, step_i] = SOURCE_INDEX["mass_balance"]
                    else:
                        if fid not in ji_series_cache:
                            hist = ji_history[fid]
                            if hist:
                                times, vals = zip(*hist)
                                ji_series_cache[fid] = pd.Series(vals, index=pd.DatetimeIndex(times))
                            else:
                                ji_series_cache[fid] = None

                        inf_series = ji_series_cache.get(fid)
                        if inf_series is not None:
                            val = trend_relax(
                                inf_series,
                                tau,
                                m_val,
                                relax_minutes=int(relax_min),
                                trend_window_minutes=trend_win_min,
                            )
                        else:
                            val = routed_val
                        sim_q_out[idx, step_i] = val
                        sim_source[idx, step_i] = SOURCE_INDEX["forecast_trend"]

                elif reach_gauge_role[idx] == "boundary":
                    site = reach_gauge_site[idx]
                    s_obs = obs_series_by_site[site]
                    t_last = t_last_by_site[site]
                    if len(s_obs) > 0 and t_last is not None:
                        if is_hindsight or tau <= t_last:
                            sim_q_out[idx, step_i] = _interp_series(s_obs, tau)
                            sim_source[idx, step_i] = SOURCE_INDEX["observed"]
                        else:
                            sim_q_out[idx, step_i] = trend_relax(
                                s_obs,
                                tau,
                                m_val,
                                relax_minutes=int(relax_min),
                                trend_window_minutes=trend_win_min,
                            )
                            sim_source[idx, step_i] = SOURCE_INDEX["forecast_trend"]
                    else:
                        sim_q_out[idx, step_i] = routed_val
                        sim_source[idx, step_i] = SOURCE_INDEX["routed"]

                elif reach_gauge_role[idx] == "interior":
                    site = reach_gauge_site[idx]
                    s_obs = obs_series_by_site[site]
                    t_last = t_last_by_site[site]
                    if len(s_obs) > 0 and t_last is not None:
                        if tau <= t_last:
                            sim_q_out[idx, step_i] = _interp_series(s_obs, tau)
                            sim_source[idx, step_i] = SOURCE_INDEX["observed"]
                        else:
                            if idx not in interior_bias:
                                obs_at_t_last = _interp_series(s_obs, t_last)
                                if step_i > 0:
                                    t_prev = sim_times[step_i - 1]
                                    frac = (t_last - t_prev).total_seconds() / dt_s
                                    uncontrolled_t_last = (
                                        sim_uncontrolled[idx, step_i - 1]
                                        + frac * (routed_val - sim_uncontrolled[idx, step_i - 1])
                                    )
                                else:
                                    uncontrolled_t_last = routed_val
                                interior_bias[idx] = obs_at_t_last - uncontrolled_t_last

                            bias0 = interior_bias[idx]
                            d_min = (tau - t_last).total_seconds() / 60.0
                            decay = math.exp(-d_min / relax_min)
                            sim_q_out[idx, step_i] = max(0.0, routed_val + bias0 * decay)
                            sim_source[idx, step_i] = SOURCE_INDEX["routed"]
                    else:
                        sim_q_out[idx, step_i] = routed_val
                        sim_source[idx, step_i] = SOURCE_INDEX["routed"]

                else:
                    sim_q_out[idx, step_i] = routed_val
                    if not up_idxs:
                        if qlat_src_fn is not None:
                            src_name = qlat_src_fn(fid, tau)
                        else:
                            r = view.ratio(fid)
                            src_name = "nwm_analysis_scaled" if abs(r - 1.0) > 1e-6 else "nwm_analysis"
                        sim_source[idx, step_i] = SOURCE_INDEX[src_name]
                    else:
                        sim_source[idx, step_i] = SOURCE_INDEX["routed"]

        q_members[m_idx, :, :] = sim_q_out[:, downsample_indices]
        if member_name == "mid" or m_idx == 1:
            source_mid[:, :] = sim_source[:, downsample_indices]

    return RoutedSeries(
        p=p,
        taus=output_taus,
        feature_ids=feature_ids,
        q=q_members,
        source=source_mid,
    )
