"""Hindcast skill computation, summarisation, target checking, and output."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Sequence
import numpy as np
import pandas as pd

from flood.contracts.models import Scenario
from flood.contracts.validate import validate_json
from flood.engine.forcing import ParquetForcingView, load_forcing_store
from flood.interfaces import MEMBER_INDEX, StateArrays


def _ensure_utc(dt: datetime | str) -> datetime:
    """Ensure datetime is tz-aware UTC."""
    if isinstance(dt, str):
        s = dt.replace("Z", "+00:00")
        res = datetime.fromisoformat(s)
    else:
        res = dt
    if res.tzinfo is None:
        res = res.replace(tzinfo=timezone.utc)
    return res.astimezone(timezone.utc)


def _get_forcing_store(run: Any) -> Any:
    store = getattr(run, "_forcing_store", None)
    if store is None:
        store = load_forcing_store(run.scenario, run.data_dir)
        try:
            run._forcing_store = store
        except (AttributeError, TypeError):
            pass
    return store


def _get_truth_view(run: Any, store: Any) -> ParquetForcingView:
    truth_view = getattr(run, "_truth_view", None)
    if truth_view is None:
        truth_view = ParquetForcingView(
            run.scenario,
            store,
            run.record_end,
            network=run.cube.network,
            gauges=getattr(run.cube, "gauges", None),
        )
        try:
            run._truth_view = truth_view
        except (AttributeError, TypeError):
            pass
    return truth_view


def skill_rows(
    run: Any,
    p: datetime,
    horizons: Sequence[int],
) -> list[dict[str, Any]]:
    """Compute skill evaluation rows for a single cutoff across specified horizons.

    Returns one row per gauge per horizon with keys:
      gauge_ref, site, feature_id, p, horizon_minutes, t,
      observed_q_cms, predicted_q_mid_cms, predicted_q_low_cms, predicted_q_high_cms,
      persistence_q_cms, abs_error_cms, persistence_abs_error_cms, within_band.
    Rows are skipped when no observation exists at t in the full record.
    """
    p_utc = _ensure_utc(p)
    store = _get_forcing_store(run)
    truth_view = _get_truth_view(run, store)

    # Persistence view at cutoff p
    p_view = ParquetForcingView(
        run.scenario,
        store,
        p_utc,
        network=run.cube.network,
        gauges=getattr(run.cube, "gauges", None),
    )

    # Build reach-to-gauge mapping from cube.network.gauge_site
    # Only evaluate gauges present in the network topology
    network = run.cube.network
    site_to_reach: dict[str, int] = {}
    for _, row in network.iterrows():
        gs = row.get("gauge_site")
        if pd.notna(gs):
            site_to_reach[str(gs)] = int(row["feature_id"])

    # Routed series from run at cutoff p
    routed_series = run.routed(p_utc)
    fid_to_idx = {int(fid): idx for idx, fid in enumerate(routed_series.feature_ids)}

    # Pre-fetch observation series for evaluated gauges
    scenario_gauges = run.scenario.hydrology.gauges
    rows: list[dict[str, Any]] = []

    for g in scenario_gauges:
        site = str(g.site)
        if site not in site_to_reach:
            continue
        fid = site_to_reach[site]
        if fid not in fid_to_idx:
            continue
        reach_idx = fid_to_idx[fid]

        # Truth observations from full record
        truth_series = truth_view.obs_q(site)
        if truth_series.empty:
            continue

        # Persistence: last known observation at p
        p_obs = p_view.obs_q(site)
        if p_obs.empty:
            continue
        persistence_q = float(p_obs.iloc[-1])

        gauge_ref = f"gauge:{site}"

        for h in horizons:
            t = p_utc + timedelta(minutes=int(h))

            # Skip row when no observation exists at t in the full record
            if t not in truth_series.index:
                continue
            obs_val = truth_series.loc[t]
            if isinstance(obs_val, pd.Series):
                obs_val = obs_val.iloc[-1]
            if pd.isna(obs_val):
                continue
            observed_q = float(obs_val)

            # Get predicted discharges from routed series at t
            try:
                q_at_t = routed_series.at(t)
            except KeyError:
                continue

            q_low = float(q_at_t[MEMBER_INDEX["low"], reach_idx])
            q_mid = float(q_at_t[MEMBER_INDEX["mid"], reach_idx])
            q_high = float(q_at_t[MEMBER_INDEX["high"], reach_idx])

            abs_err = abs(q_mid - observed_q)
            p_abs_err = abs(persistence_q - observed_q)
            within_band = bool(min(q_low, q_high) <= observed_q <= max(q_low, q_high))

            rows.append({
                "gauge_ref": gauge_ref,
                "site": site,
                "feature_id": fid,
                "p": p_utc,
                "horizon_minutes": int(h),
                "t": t,
                "observed_q_cms": observed_q,
                "predicted_q_mid_cms": q_mid,
                "predicted_q_low_cms": q_low,
                "predicted_q_high_cms": q_high,
                "persistence_q_cms": persistence_q,
                "abs_error_cms": abs_err,
                "persistence_abs_error_cms": p_abs_err,
                "within_band": within_band,
            })

    return rows


def _compute_extent_iou(
    run: Any,
    p: datetime,
    t: datetime,
    iou_threshold_m: float,
) -> float:
    """Compute IoU between forecast depth_mid and hindsight depth_mid >= threshold."""
    s_fcst = run.state(p, t, write=False)
    if isinstance(s_fcst, tuple):
        s_fcst = s_fcst[0]

    s_hind = run.state("hindsight", t, write=False)
    if isinstance(s_hind, tuple):
        s_hind = s_hind[0]

    d_fcst = s_fcst.depth_mid
    d_hind = s_hind.depth_mid

    valid = ~np.isnan(d_fcst) & ~np.isnan(d_hind)
    m_fcst = (d_fcst >= iou_threshold_m) & valid
    m_hind = (d_hind >= iou_threshold_m) & valid

    intersection = int(np.count_nonzero(m_fcst & m_hind))
    union = int(np.count_nonzero(m_fcst | m_hind))

    if union == 0:
        return 1.0 if intersection == 0 else 0.0
    return float(intersection) / float(union)


def compute_skill(
    run: Any,
    cutoffs: Sequence[datetime],
    horizons: Sequence[int],
    iou_threshold_m: float = 0.15,
) -> pd.DataFrame:
    """Compute hindcast skill across a grid of cutoffs and horizons with extent IoU.

    Concatenates skill rows for all cutoffs and adds iou_015 (null except at horizons 60 and 120)
    computed as intersection / union of depth_mid >= threshold masks against hindsight.
    """
    all_rows: list[dict[str, Any]] = []
    for p in cutoffs:
        p_utc = _ensure_utc(p)
        rows_p = skill_rows(run, p_utc, horizons)
        all_rows.extend(rows_p)

    columns = [
        "gauge_ref",
        "site",
        "feature_id",
        "p",
        "horizon_minutes",
        "t",
        "observed_q_cms",
        "predicted_q_mid_cms",
        "predicted_q_low_cms",
        "predicted_q_high_cms",
        "persistence_q_cms",
        "abs_error_cms",
        "persistence_abs_error_cms",
        "within_band",
        "iou_015",
    ]

    if not all_rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(all_rows)

    # Compute IoU only at horizons 60 and 120, caching by (p, t)
    iou_cache: dict[tuple[datetime, datetime], float] = {}
    iou_values: list[float] = []

    for _, row in df.iterrows():
        h = int(row["horizon_minutes"])
        if h in (60, 120):
            key = (row["p"], row["t"])
            if key not in iou_cache:
                iou_cache[key] = _compute_extent_iou(run, row["p"], row["t"], iou_threshold_m)
            iou_values.append(iou_cache[key])
        else:
            iou_values.append(np.nan)

    df["iou_015"] = iou_values
    return df


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    """Summarise skill detail DataFrame by gauge_ref and horizon_minutes.

    Computes mae_cms, persistence_mae_cms, bias_cms, coverage (mean within_band),
    n, skill = 1 - mae_cms / persistence_mae_cms, and iou_015 (mean).
    """
    columns = [
        "gauge_ref",
        "horizon_minutes",
        "mae_cms",
        "persistence_mae_cms",
        "bias_cms",
        "coverage",
        "n",
        "skill",
        "iou_015",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for (gauge_ref, h), grp in df.groupby(["gauge_ref", "horizon_minutes"], as_index=False):
        n = len(grp)
        mae_cms = float(grp["abs_error_cms"].mean())
        persistence_mae_cms = float(grp["persistence_abs_error_cms"].mean())
        bias_cms = float((grp["predicted_q_mid_cms"] - grp["observed_q_cms"]).mean())
        coverage = float(grp["within_band"].astype(float).mean())

        if persistence_mae_cms > 0:
            skill = 1.0 - (mae_cms / persistence_mae_cms)
        else:
            skill = np.nan

        iou_series = grp["iou_015"].dropna()
        iou_015 = float(iou_series.mean()) if not iou_series.empty else np.nan

        rows.append({
            "gauge_ref": str(gauge_ref),
            "horizon_minutes": int(h),
            "mae_cms": mae_cms,
            "persistence_mae_cms": persistence_mae_cms,
            "bias_cms": bias_cms,
            "coverage": coverage,
            "n": n,
            "skill": skill,
            "iou_015": iou_015,
        })

    summary = pd.DataFrame(rows)
    return summary.sort_values(by=["gauge_ref", "horizon_minutes"]).reset_index(drop=True)


def write_skill(
    run_or_dir: Any,
    detail_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> tuple[Path, Path]:
    """Write summary rows to skill.parquet and full detail rows to skill_detail.parquet."""
    if hasattr(run_or_dir, "run_dir"):
        target_dir = Path(run_or_dir.run_dir)
    else:
        target_dir = Path(run_or_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    summary_path = target_dir / "skill.parquet"
    detail_path = target_dir / "skill_detail.parquet"

    summary_df.to_parquet(summary_path, index=False)
    detail_df.to_parquet(detail_path, index=False)
    return summary_path, detail_path


def target_check(summary_df: pd.DataFrame, scenario: Scenario) -> list[str]:
    """Check hindcast skill against target for interior gauges at horizons 60 and 120.

    If skill <= 0 for any pair, returns one limitation line per failing pair:
      'Hindcast skill at <gauge_ref> for <h> min horizon did not beat persistence (MAE <x> vs <y> cms).'
    If all pass, returns one line stating the median skill at 60 and 120 minutes.
    """
    interior_gauges = [g for g in scenario.hydrology.gauges if g.role == "interior"]
    target_horizons = [60, 120]

    failing_lines: list[str] = []
    passing_skills_by_h: dict[int, list[float]] = {60: [], 120: []}

    for g in interior_gauges:
        gauge_ref = f"gauge:{g.site}"
        for h in target_horizons:
            match = summary_df[
                (summary_df["gauge_ref"] == gauge_ref) & (summary_df["horizon_minutes"] == h)
            ]
            if match.empty:
                continue

            mae = float(match["mae_cms"].iloc[0])
            p_mae = float(match["persistence_mae_cms"].iloc[0])
            skill_val = match["skill"].iloc[0]

            if pd.isna(skill_val) or skill_val <= 0:
                failing_lines.append(
                    f"Hindcast skill at {gauge_ref} for {h} min horizon did not beat persistence "
                    f"(MAE {mae:.2f} vs {p_mae:.2f} cms)."
                )
            else:
                passing_skills_by_h[h].append(float(skill_val))

    if failing_lines:
        return failing_lines

    # If all pass, append one line stating the median skill at 60 and 120 minutes
    med_60 = float(np.median(passing_skills_by_h[60])) if passing_skills_by_h[60] else None
    med_120 = float(np.median(passing_skills_by_h[120])) if passing_skills_by_h[120] else None

    if med_60 is not None and med_120 is not None:
        return [
            f"Hindcast skill meets target for interior gauges: median skill is {med_60:.2f} at 60 min, "
            f"{med_120:.2f} at 120 min."
        ]
    elif med_60 is not None:
        return [
            f"Hindcast skill meets target for interior gauges: median skill is {med_60:.2f} at 60 min."
        ]
    elif med_120 is not None:
        return [
            f"Hindcast skill meets target for interior gauges: median skill is {med_120:.2f} at 120 min."
        ]

    return []


def update_limitations(run_json_path: Path | str, lines: list[str]) -> None:
    """Append lines to limitations in run.json and rewrite validating against manifest schema."""
    p = Path(run_json_path)
    data = json.loads(p.read_text(encoding="utf-8"))

    if "limitations" not in data or not isinstance(data["limitations"], list):
        data["limitations"] = []

    for line in lines:
        if line not in data["limitations"]:
            data["limitations"].append(line)

    validate_json("run-manifest", data)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
