"""Reach and gauge table construction and contract-validated serialization."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import numpy as np
import pandas as pd

from flood.contracts.validate import validate_json
from flood.engine.forcing import ParquetForcingView
from flood.engine.rating import stage_from_q, wet_area
from flood.interfaces import RoutedSeries, SOURCE_CODES
from flood.timegrid import grid_range, parse_iso, to_iso


def build_reaches(
    run: Any,
    routed: RoutedSeries,
    t: datetime | str,
    member_fields: Any = None,
) -> pd.DataFrame:
    """Build reaches DataFrame covering all AOI reaches at target time t."""
    if isinstance(t, str):
        t_dt = parse_iso(t)
    else:
        t_dt = t.astimezone(timezone.utc) if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)

    p_dt = routed.p
    if p_dt.tzinfo is None:
        p_dt = p_dt.replace(tzinfo=timezone.utc)
    else:
        p_dt = p_dt.astimezone(timezone.utc)

    cube = run.cube
    network = cube.network
    aoi_network = network[network["in_aoi"].astype(bool)].copy()
    aoi_network = aoi_network.sort_values(by="feature_id").reset_index(drop=True)
    fids = aoi_network["feature_id"].to_numpy(dtype=np.int64)
    n_reaches = len(fids)

    routed_fid_to_idx = {int(fid): i for i, fid in enumerate(routed.feature_ids)}
    aoi_routed_indices = np.array([routed_fid_to_idx[fid] for fid in fids], dtype=np.int64)

    # Discharges at t: [3, R]
    q_at_t = routed.at(t_dt)
    q_low_cms = np.maximum(0.0, q_at_t[0, aoi_routed_indices]).astype(np.float32)
    q_mid_cms = np.maximum(0.0, q_at_t[1, aoi_routed_indices]).astype(np.float32)
    q_high_cms = np.maximum(0.0, q_at_t[2, aoi_routed_indices]).astype(np.float32)

    # Stages at t
    stage_mid_m = np.zeros(n_reaches, dtype=np.float32)
    stage_low_m = np.zeros(n_reaches, dtype=np.float32)
    stage_high_m = np.zeros(n_reaches, dtype=np.float32)
    velocity_ms = np.zeros(n_reaches, dtype=np.float32)

    # Group by preferred branch for rating table lookups
    pref_branches = aoi_network["preferred_branch"].to_numpy(dtype=np.int64)
    rep_cidxs = aoi_network["representative_cidx"].to_numpy(dtype=np.int64)

    for branch in cube.branches:
        bid = branch.branch_id
        rt = branch.rating
        mask = (pref_branches == bid) & (rep_cidxs >= 0)
        indices = np.where(mask)[0]
        if len(indices) == 0:
            continue

        cidxs = rep_cidxs[indices]
        q_l = q_low_cms[indices]
        q_m = q_mid_cms[indices]
        q_h = q_high_cms[indices]

        s_l, _ = stage_from_q(rt, cidxs, q_l)
        s_m, _ = stage_from_q(rt, cidxs, q_m)
        s_h, _ = stage_from_q(rt, cidxs, q_h)

        stage_low_m[indices] = s_l
        stage_mid_m[indices] = s_m
        stage_high_m[indices] = s_h

        wa = wet_area(rt, cidxs, s_m)
        safe_wa = np.where(wa > 0.0, wa, 1.0)
        v = np.where(wa > 0.0, q_m / safe_wa, 0.0)
        velocity_ms[indices] = v.astype(np.float32)

    # Rate of rise: (stage(t) - stage(t - 30 min)) * 2 using routed mid series
    rate_of_rise = np.zeros(n_reaches, dtype=np.float32)
    t_prev = t_dt - timedelta(minutes=30)
    prev_tau_s = np.datetime64(t_prev.replace(tzinfo=None), "s")
    if prev_tau_s in routed.taus:
        q_at_prev = routed.at(t_prev)
        q_mid_prev = np.maximum(0.0, q_at_prev[1, aoi_routed_indices]).astype(np.float32)
        stage_mid_prev = np.zeros(n_reaches, dtype=np.float32)

        for branch in cube.branches:
            bid = branch.branch_id
            rt = branch.rating
            mask = (pref_branches == bid) & (rep_cidxs >= 0)
            indices = np.where(mask)[0]
            if len(indices) == 0:
                continue

            cidxs = rep_cidxs[indices]
            s_prev, _ = stage_from_q(rt, cidxs, q_mid_prev[indices])
            stage_mid_prev[indices] = s_prev

        rate_of_rise = ((stage_mid_m - stage_mid_prev) * 2.0).astype(np.float32)

    # Source decoding
    t_idx = routed.index_of(t_dt)
    src_codes = routed.source[aoi_routed_indices, t_idx]
    sources = [SOURCE_CODES.get(int(c), "routed") for c in src_codes]

    # Clipped to rating curve from member_fields
    if hasattr(member_fields, "clipped"):
        clipped_map = member_fields.clipped
    elif isinstance(member_fields, dict):
        mf = member_fields.get("mid") or member_fields.get(1)
        clipped_map = getattr(mf, "clipped", {}) if mf is not None else {}
    elif isinstance(member_fields, (list, tuple)) and len(member_fields) > 1:
        clipped_map = getattr(member_fields[1], "clipped", {})
    else:
        clipped_map = {}

    clipped_to_src = [bool(clipped_map.get(int(fid), False)) for fid in fids]

    # Gauge references
    gauge_refs = []
    for site in aoi_network["gauge_site"]:
        if pd.notna(site) and str(site).strip():
            gauge_refs.append(f"gauge:{str(site).strip()}")
        else:
            gauge_refs.append(None)

    # Hindsight mode check: is_forecast is False if t <= p_dt or if hindsight
    is_hindsight = (p_dt >= run.record_end)
    is_forecast = False if is_hindsight else bool(t_dt > p_dt)

    p_utc = p_dt.astimezone(timezone.utc)
    t_utc = t_dt.astimezone(timezone.utc)

    df = pd.DataFrame({
        "reach_ref": [f"reach:{fid}" for fid in fids],
        "feature_id": fids.astype(np.int64),
        "levelpath_id": aoi_network["levelpath_id"].to_numpy(dtype=np.int64),
        "stream_order": aoi_network["stream_order"].to_numpy(dtype=np.int8),
        "gauge_ref": gauge_refs,
        "p": pd.to_datetime([p_utc] * n_reaches, utc=True),
        "t": pd.to_datetime([t_utc] * n_reaches, utc=True),
        "is_forecast": [is_forecast] * n_reaches,
        "q_mid_cms": q_mid_cms,
        "q_low_cms": q_low_cms,
        "q_high_cms": q_high_cms,
        "stage_mid_m": stage_mid_m,
        "stage_low_m": stage_low_m,
        "stage_high_m": stage_high_m,
        "rate_of_rise_m_per_h": rate_of_rise,
        "velocity_ms": velocity_ms,
        "source": sources,
        "clipped_to_src": clipped_to_src,
    })
    return df


def build_gauges(
    run: Any,
    routed: RoutedSeries,
    p_internal: datetime | str,
) -> pd.DataFrame:
    """Build gauges DataFrame covering all scenario gauges from record_start to p + max_horizon."""
    if isinstance(p_internal, str):
        if p_internal.lower() == "hindsight":
            p_dt = run.record_end
        else:
            p_dt = parse_iso(p_internal)
    else:
        p_dt = p_internal.astimezone(timezone.utc) if p_internal.tzinfo is not None else p_internal.replace(tzinfo=timezone.utc)

    is_hindsight = (p_dt >= run.record_end)
    t_end = min(p_dt + timedelta(minutes=run.max_horizon_minutes), run.record_end)
    taus = grid_range(run.record_start, t_end)

    view = ParquetForcingView(
        run.scenario,
        run.store,
        p_dt,
        network=run.cube.network,
        gauges=run.cube.gauges,
    )

    fid_to_r_idx = {int(fid): i for i, fid in enumerate(routed.feature_ids)}
    cube_gauges = run.cube.gauges
    network = run.cube.network

    rows: list[dict[str, Any]] = []

    for g in run.scenario.hydrology.gauges:
        site_str = str(g.site)
        g_fid = int(g.feature_id)
        g_ref = f"gauge:{site_str}"
        r_idx = fid_to_r_idx.get(g_fid)

        # Elevation lookup
        cg_match = cube_gauges[cube_gauges["site"].astype(str) == site_str]
        if not cg_match.empty and "dem_adj_elevation_m" in cg_match.columns:
            dem_adj_elev = float(cg_match["dem_adj_elevation_m"].iloc[0])
        else:
            dem_adj_elev = 0.0

        # Reach network rating lookup for gauge reach
        net_match = network[network["feature_id"] == g_fid]
        if not net_match.empty:
            pref_branch = int(net_match["preferred_branch"].iloc[0])
            rep_cidx = int(net_match["representative_cidx"].iloc[0])
            try:
                rt = run.cube.branch(pref_branch).rating if rep_cidx >= 0 else None
            except KeyError:
                rt = None
        else:
            rt = None
            rep_cidx = -1

        obs_q_series = view.obs_q(site_str)
        obs_wse_series = view.obs_wse(site_str)

        for t in taus:
            is_forecast = False if is_hindsight else bool(t > p_dt)

            obs_q = float(obs_q_series.loc[t]) if t in obs_q_series.index else None
            obs_wse = float(obs_wse_series.loc[t]) if t in obs_wse_series.index else None

            tau_s = np.datetime64(t.replace(tzinfo=None), "s")
            if tau_s in routed.taus and r_idx is not None:
                t_idx = routed.index_of(t)
                pq_low = float(routed.q[0, r_idx, t_idx])
                pq_mid = float(routed.q[1, r_idx, t_idx])
                pq_high = float(routed.q[2, r_idx, t_idx])
            else:
                pq_low = 0.0
                pq_mid = 0.0
                pq_high = 0.0

            if rt is not None and rep_cidx >= 0:
                s_mid, _ = stage_from_q(rt, rep_cidx, pq_mid)
                stage_mid_f = float(s_mid)
            else:
                stage_mid_f = 0.0

            pred_wse_mid = dem_adj_elev + stage_mid_f

            rows.append({
                "gauge_ref": g_ref,
                "site": site_str,
                "feature_id": g_fid,
                "p": p_dt,
                "t": t,
                "is_forecast": is_forecast,
                "observed_q_cms": obs_q,
                "observed_wse_m": obs_wse,
                "predicted_q_mid_cms": np.float32(pq_mid),
                "predicted_q_low_cms": np.float32(pq_low),
                "predicted_q_high_cms": np.float32(pq_high),
                "predicted_wse_mid_m": np.float32(pred_wse_mid),
                "wse_datum": "NAVD88",
            })

    df = pd.DataFrame(rows)
    df["p"] = pd.to_datetime(df["p"], utc=True)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df["feature_id"] = df["feature_id"].astype(np.int64)
    df["is_forecast"] = df["is_forecast"].astype(bool)
    df["predicted_q_mid_cms"] = df["predicted_q_mid_cms"].astype(np.float32)
    df["predicted_q_low_cms"] = df["predicted_q_low_cms"].astype(np.float32)
    df["predicted_q_high_cms"] = df["predicted_q_high_cms"].astype(np.float32)
    df["predicted_wse_mid_m"] = df["predicted_wse_mid_m"].astype(np.float32)
    if not df.empty:
        df["observed_q_cms"] = df["observed_q_cms"].astype(np.float32)
        df["observed_wse_m"] = df["observed_wse_m"].astype(np.float32)
    return df


def reaches_to_json(df: pd.DataFrame) -> list[dict]:
    """Convert reaches DataFrame to a list of dicts that validate against reach-row schema."""
    records = []
    for _, row in df.iterrows():
        p_dt = pd.to_datetime(row["p"]).to_pydatetime()
        t_dt = pd.to_datetime(row["t"]).to_pydatetime()
        r = {
            "reach_ref": str(row["reach_ref"]),
            "feature_id": int(row["feature_id"]),
            "levelpath_id": int(row["levelpath_id"]),
            "stream_order": int(row["stream_order"]),
            "gauge_ref": str(row["gauge_ref"]) if pd.notna(row["gauge_ref"]) and row["gauge_ref"] is not None else None,
            "p": to_iso(p_dt),
            "t": to_iso(t_dt),
            "is_forecast": bool(row["is_forecast"]),
            "q_mid_cms": float(row["q_mid_cms"]),
            "q_low_cms": float(row["q_low_cms"]),
            "q_high_cms": float(row["q_high_cms"]),
            "stage_mid_m": float(row["stage_mid_m"]),
            "stage_low_m": float(row["stage_low_m"]),
            "stage_high_m": float(row["stage_high_m"]),
            "rate_of_rise_m_per_h": float(row["rate_of_rise_m_per_h"]),
            "velocity_ms": float(row["velocity_ms"]),
            "source": str(row["source"]),
            "clipped_to_src": bool(row["clipped_to_src"]),
        }
        validate_json("reach-row", r)
        records.append(r)
    return records


def gauges_to_json(df: pd.DataFrame) -> list[dict]:
    """Convert gauges DataFrame to a list of dicts that validate against gauge-row schema."""
    records = []
    for _, row in df.iterrows():
        p_dt = pd.to_datetime(row["p"]).to_pydatetime()
        t_dt = pd.to_datetime(row["t"]).to_pydatetime()
        obs_q = float(row["observed_q_cms"]) if pd.notna(row["observed_q_cms"]) else None
        obs_wse = float(row["observed_wse_m"]) if pd.notna(row["observed_wse_m"]) else None
        r = {
            "gauge_ref": str(row["gauge_ref"]),
            "site": str(row["site"]),
            "feature_id": int(row["feature_id"]),
            "p": to_iso(p_dt),
            "t": to_iso(t_dt),
            "is_forecast": bool(row["is_forecast"]),
            "observed_q_cms": obs_q,
            "observed_wse_m": obs_wse,
            "predicted_q_mid_cms": float(row["predicted_q_mid_cms"]),
            "predicted_q_low_cms": float(row["predicted_q_low_cms"]),
            "predicted_q_high_cms": float(row["predicted_q_high_cms"]),
            "predicted_wse_mid_m": float(row["predicted_wse_mid_m"]),
            "wse_datum": "NAVD88",
        }
        validate_json("gauge-row", r)
        records.append(r)
    return records
