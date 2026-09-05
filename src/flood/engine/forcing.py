"""Forcing store and ForcingView implementation over Parquet files."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from flood.contracts.models import Scenario
from flood.interfaces import ForcingView


def _parse_utc(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        s = dt.replace("Z", "+00:00")
        res = datetime.fromisoformat(s)
    else:
        res = dt
    if res.tzinfo is None:
        res = res.replace(tzinfo=timezone.utc)
    return res.astimezone(timezone.utc)


@dataclass
class ForcingStore:
    """In-memory store of raw forcing DataFrames and latency rules."""
    usgs: pd.DataFrame
    nwm_analysis: pd.DataFrame
    nwm_short_range: pd.DataFrame
    latencies: dict[str, int]


def load_forcing_store(scenario: Scenario, data_dir: Path | str) -> ForcingStore:
    """Load the forcing store for a scenario from Parquet in data_dir."""
    data_dir = Path(data_dir)
    scenario_id = scenario.scenario_id

    usgs_path = data_dir / "usgs" / scenario_id / "continuous.parquet"
    analysis_path = data_dir / "nwm" / scenario_id / "analysis.parquet"
    short_range_path = data_dir / "nwm" / scenario_id / "short_range.parquet"

    if usgs_path.exists():
        usgs_df = pd.read_parquet(usgs_path)
        if not usgs_df.empty and "valid_time" in usgs_df.columns:
            usgs_df["valid_time"] = pd.to_datetime(usgs_df["valid_time"], utc=True)
    else:
        usgs_df = pd.DataFrame(columns=["site", "valid_time", "parameter", "value_si", "approval"])
        usgs_df["valid_time"] = pd.to_datetime(usgs_df["valid_time"], utc=True)

    if analysis_path.exists():
        analysis_df = pd.read_parquet(analysis_path)
        if not analysis_df.empty and "valid_time" in analysis_df.columns:
            analysis_df["valid_time"] = pd.to_datetime(analysis_df["valid_time"], utc=True)
    else:
        analysis_df = pd.DataFrame(columns=["valid_time", "feature_id", "q_cms", "v_ms", "qlat_cms"])
        analysis_df["valid_time"] = pd.to_datetime(analysis_df["valid_time"], utc=True)

    if short_range_path.exists():
        short_range_df = pd.read_parquet(short_range_path)
        if not short_range_df.empty:
            if "issue_time" in short_range_df.columns:
                short_range_df["issue_time"] = pd.to_datetime(short_range_df["issue_time"], utc=True)
            if "valid_time" in short_range_df.columns:
                short_range_df["valid_time"] = pd.to_datetime(short_range_df["valid_time"], utc=True)
    else:
        short_range_df = pd.DataFrame(columns=["issue_time", "valid_time", "feature_id", "q_cms", "qlat_cms"])
        short_range_df["issue_time"] = pd.to_datetime(short_range_df["issue_time"], utc=True)
        short_range_df["valid_time"] = pd.to_datetime(short_range_df["valid_time"], utc=True)

    latencies: dict[str, int] = {
        "usgs_continuous": 5,
        "nwm_analysis_assim": 60,
        "nwm_short_range": 90,
    }
    for src in scenario.forcing_defaults.sources:
        if hasattr(src, "availability_latency_min"):
            latencies[src.type] = src.availability_latency_min

    return ForcingStore(
        usgs=usgs_df,
        nwm_analysis=analysis_df,
        nwm_short_range=short_range_df,
        latencies=latencies,
    )


class ParquetForcingView:
    """Everything known at cutoff p from ingested Parquet forcing files."""

    def __init__(
        self,
        scenario: Scenario,
        store: ForcingStore,
        p: datetime | str,
        network: pd.DataFrame | None = None,
        gauges: pd.DataFrame | None = None,
    ) -> None:
        self.scenario = scenario
        self.store = store
        self.p = _parse_utc(p)
        self.network = network
        self.gauges = gauges
        self._ratio_cache: dict[int, float] = {}
        self._qlat_tables: dict = {}
        self._cutoff_analysis_ns: int = 0

    def obs_q(self, site: str) -> pd.Series:
        """Observed discharge in cms with latency applied and outages removed."""
        site_str = str(site)
        df = self.store.usgs
        if df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        mask = (df["site"].astype(str) == site_str) & (df["parameter"] == "00060")
        site_df = df[mask]
        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        latency_min = self.store.latencies.get("usgs_continuous", 5)
        cutoff = self.p - timedelta(minutes=latency_min)
        site_df = site_df[site_df["valid_time"] <= cutoff]
        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        # Remove outages
        site_ref = f"gauge:{site_str}"
        for override in self.scenario.forcing_defaults.scenario_overrides:
            if override.type == "gauge_outage" and (override.gauge_ref == site_ref or override.gauge_ref.endswith(site_str)):
                from_dt = _parse_utc(override.from_)
                if override.to is not None:
                    to_dt = _parse_utc(override.to)
                    site_df = site_df[~((site_df["valid_time"] >= from_dt) & (site_df["valid_time"] < to_dt))]
                else:
                    site_df = site_df[site_df["valid_time"] < from_dt]

        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        site_df = site_df.sort_values(by="valid_time")
        series = pd.Series(
            data=site_df["value_si"].values.astype(np.float64),
            index=pd.DatetimeIndex(site_df["valid_time"], tz=timezone.utc),
            name="q_cms",
        )
        return series

    def obs_wse(self, site: str) -> pd.Series:
        """Observed water surface elevation in m (or stage if no datum) with latency and outages removed."""
        site_str = str(site)
        df = self.store.usgs
        if df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        mask = (df["site"].astype(str) == site_str) & (df["parameter"] == "00065")
        site_df = df[mask]
        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        latency_min = self.store.latencies.get("usgs_continuous", 5)
        cutoff = self.p - timedelta(minutes=latency_min)
        site_df = site_df[site_df["valid_time"] <= cutoff]
        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        site_ref = f"gauge:{site_str}"
        for override in self.scenario.forcing_defaults.scenario_overrides:
            if override.type == "gauge_outage" and (override.gauge_ref == site_ref or override.gauge_ref.endswith(site_str)):
                from_dt = _parse_utc(override.from_)
                if override.to is not None:
                    to_dt = _parse_utc(override.to)
                    site_df = site_df[~((site_df["valid_time"] >= from_dt) & (site_df["valid_time"] < to_dt))]
                else:
                    site_df = site_df[site_df["valid_time"] < from_dt]

        if site_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        site_df = site_df.sort_values(by="valid_time")
        values = site_df["value_si"].values.astype(np.float64)

        if self.gauges is not None and not self.gauges.empty:
            gauge_rows = self.gauges[self.gauges["site"].astype(str) == site_str]
            if not gauge_rows.empty and "gauge_altitude_m" in gauge_rows.columns:
                alt = gauge_rows["gauge_altitude_m"].iloc[0]
                if pd.notna(alt):
                    values = values + float(alt)

        series = pd.Series(
            data=values,
            index=pd.DatetimeIndex(site_df["valid_time"], tz=timezone.utc),
            name="wse_m",
        )
        return series

    def nwm_analysis(self, feature_id: int) -> pd.Series:
        """NWM analysis discharge in cms with latency applied."""
        fid = int(feature_id)
        df = self.store.nwm_analysis
        if df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        feat_df = df[df["feature_id"] == fid]
        if feat_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        latency_min = self.store.latencies.get("nwm_analysis_assim", 60)
        cutoff = self.p - timedelta(minutes=latency_min)
        feat_df = feat_df[feat_df["valid_time"] <= cutoff]
        if feat_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        feat_df = feat_df.sort_values(by="valid_time")
        series = pd.Series(
            data=feat_df["q_cms"].values.astype(np.float64),
            index=pd.DatetimeIndex(feat_df["valid_time"], tz=timezone.utc),
            name="q_cms",
        )
        return series

    def latest_short_range(self, feature_id: int) -> pd.Series:
        """Rows of the single cycle with greatest issue_time satisfying issue_time + latency <= p."""
        fid = int(feature_id)
        df = self.store.nwm_short_range
        if df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        feat_df = df[df["feature_id"] == fid]
        if feat_df.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        latency_min = self.store.latencies.get("nwm_short_range", 90)
        cutoff = self.p - timedelta(minutes=latency_min)
        eligible = feat_df[feat_df["issue_time"] <= cutoff]
        if eligible.empty:
            return pd.Series(dtype=np.float64, index=pd.DatetimeIndex([], tz=timezone.utc))

        max_issue = eligible["issue_time"].max()
        cycle_df = eligible[eligible["issue_time"] == max_issue]
        cycle_df = cycle_df.sort_values(by="valid_time")

        series = pd.Series(
            data=cycle_df["q_cms"].values.astype(np.float64),
            index=pd.DatetimeIndex(cycle_df["valid_time"], tz=timezone.utc),
            name="q_cms",
        )
        return series

    def ratio(self, feature_id: int) -> float:
        """Levelpath bias correction ratio for feature_id, clamped and cached."""
        fid = int(feature_id)
        if fid in self._ratio_cache:
            return self._ratio_cache[fid]

        if self.network is None or self.network.empty:
            self._ratio_cache[fid] = 1.0
            return 1.0

        state_est = self.scenario.forcing_defaults.state_estimation
        if state_est.bias_correction == "none":
            self._ratio_cache[fid] = 1.0
            return 1.0

        net = self.network
        reach_rows = net[net["feature_id"] == fid]
        if reach_rows.empty:
            self._ratio_cache[fid] = 1.0
            return 1.0

        target_lp = reach_rows["levelpath_id"].iloc[0]

        # Gather eligible gauges (interior or boundary)
        eligible_gauges_by_fid: dict[int, list[str]] = {}
        for g in self.scenario.hydrology.gauges:
            if g.role in ("interior", "boundary"):
                eligible_gauges_by_fid.setdefault(int(g.feature_id), []).append(str(g.site))

        if self.gauges is not None and not self.gauges.empty and "role" in self.gauges.columns:
            for _, grow in self.gauges.iterrows():
                if grow["role"] in ("interior", "boundary"):
                    eligible_gauges_by_fid.setdefault(int(grow["feature_id"]), []).append(str(grow["site"]))

        for k in eligible_gauges_by_fid:
            eligible_gauges_by_fid[k] = list(dict.fromkeys(eligible_gauges_by_fid[k]))

        # Check if reach itself has an eligible gauge
        target_gauge_site: str | None = None
        target_gauge_fid: int | None = None

        if fid in eligible_gauges_by_fid and eligible_gauges_by_fid[fid]:
            target_gauge_site = eligible_gauges_by_fid[fid][0]
            target_gauge_fid = fid
        else:
            net_by_fid: dict[int, dict[str, Any]] = {}
            for _, r in net.iterrows():
                net_by_fid[int(r["feature_id"])] = {
                    "to_feature_id": int(r["to_feature_id"]),
                    "levelpath_id": r["levelpath_id"],
                }

            # Downstream walk: follow to_feature_id while next reach has same levelpath_id; stop at 0
            cur = fid
            visited = {cur}
            while cur in net_by_fid:
                next_fid = net_by_fid[cur]["to_feature_id"]
                if next_fid == 0 or next_fid not in net_by_fid:
                    break
                if net_by_fid[next_fid]["levelpath_id"] != target_lp:
                    break
                if next_fid in visited:
                    break
                visited.add(next_fid)
                if next_fid in eligible_gauges_by_fid and eligible_gauges_by_fid[next_fid]:
                    target_gauge_site = eligible_gauges_by_fid[next_fid][0]
                    target_gauge_fid = next_fid
                    break
                cur = next_fid

            # Upstream BFS over reverse edges on same levelpath
            if target_gauge_site is None:
                reverse_adj: dict[int, list[int]] = {}
                for f, info in net_by_fid.items():
                    if info["levelpath_id"] == target_lp:
                        to_f = info["to_feature_id"]
                        reverse_adj.setdefault(to_f, []).append(f)

                queue = [fid]
                bfs_visited = {fid}
                while queue:
                    curr_node = queue.pop(0)
                    for up_fid in reverse_adj.get(curr_node, []):
                        if up_fid not in bfs_visited:
                            bfs_visited.add(up_fid)
                            if up_fid in eligible_gauges_by_fid and eligible_gauges_by_fid[up_fid]:
                                target_gauge_site = eligible_gauges_by_fid[up_fid][0]
                                target_gauge_fid = up_fid
                                break
                            queue.append(up_fid)
                    if target_gauge_site is not None:
                        break

        if target_gauge_site is None or target_gauge_fid is None:
            self._ratio_cache[fid] = 1.0
            return 1.0

        obs = self.obs_q(target_gauge_site)
        nwm = self.nwm_analysis(target_gauge_fid)
        if obs.empty or nwm.empty:
            self._ratio_cache[fid] = 1.0
            return 1.0

        common_times = obs.index.intersection(nwm.index)
        if len(common_times) == 0:
            self._ratio_cache[fid] = 1.0
            return 1.0

        common_times_desc = common_times.sort_values(ascending=False)
        found_ratio: float | None = None
        for t in common_times_desc:
            o_val = float(obs.loc[t])
            n_val = float(nwm.loc[t])
            if o_val >= 0.1 and n_val > 0.0:
                found_ratio = o_val / n_val
                break

        if found_ratio is None:
            self._ratio_cache[fid] = 1.0
            return 1.0

        clamp_min, clamp_max = state_est.ratio_clamp
        clamped = max(clamp_min, min(clamp_max, found_ratio))
        self._ratio_cache[fid] = float(clamped)
        return float(clamped)

    def _qlat_table(self, fid: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float | None]:
        """Precompute the qlat fallback chain for one feature as sorted arrays.

        Returns (analysis_times_ns, analysis_vals, sr_times_ns, sr_vals, last_known_analysis):
        analysis rows for the feature (all valid times), the latest short-range cycle known at
        p, and the last analysis value known at p (or None). Cached per feature so routing can
        call qlat once per reach per time step cheaply.
        """
        cached = self._qlat_tables.get(fid)
        if cached is not None:
            return cached
        latency_analysis = timedelta(minutes=self.store.latencies.get("nwm_analysis_assim", 60))
        cutoff_analysis = self.p - latency_analysis
        a = self.store.nwm_analysis
        fa = a[a["feature_id"] == fid].sort_values("valid_time") if not a.empty else a
        if not fa.empty and "qlat_cms" in fa.columns:
            a_times = fa["valid_time"].values.astype("datetime64[ns]").astype(np.int64)
            a_vals = fa["qlat_cms"].values.astype(np.float64)
            known = fa[fa["valid_time"] <= cutoff_analysis]
            last_known = float(known["qlat_cms"].iloc[-1]) if not known.empty else None
        else:
            a_times = np.empty(0, np.int64); a_vals = np.empty(0, np.float64); last_known = None
        latency_sr = timedelta(minutes=self.store.latencies.get("nwm_short_range", 90))
        cutoff_sr = self.p - latency_sr
        sr = self.store.nwm_short_range
        sr_times = np.empty(0, np.int64); sr_vals = np.empty(0, np.float64)
        if not sr.empty and "qlat_cms" in sr.columns:
            fsr = sr[(sr["feature_id"] == fid) & (sr["issue_time"] <= cutoff_sr)]
            if not fsr.empty:
                cyc = fsr[fsr["issue_time"] == fsr["issue_time"].max()].sort_values("valid_time")
                sr_times = cyc["valid_time"].values.astype("datetime64[ns]").astype(np.int64)
                sr_vals = cyc["qlat_cms"].values.astype(np.float64)
        self._cutoff_analysis_ns = int(np.datetime64(cutoff_analysis.replace(tzinfo=None), "ns").astype(np.int64))
        table = (a_times, a_vals, sr_times, sr_vals, last_known)
        self._qlat_tables[fid] = table
        return table

    def qlat(self, feature_id: int, tau: datetime | str) -> float:
        """Lateral inflow at tau, with fallback chain and ratio multiplier.

        Chain: analysis value at the last valid_time <= tau if that value is known at p;
        else the latest known short-range cycle's value at the last valid_time <= tau;
        else the last analysis value known at p; else 0.0.
        """
        fid = int(feature_id)
        tau_utc = _parse_utc(tau)
        tau_ns = int(np.datetime64(tau_utc.replace(tzinfo=None), "ns").astype(np.int64))
        a_times, a_vals, sr_times, sr_vals, last_known = self._qlat_table(fid)
        base_qlat = None
        if len(a_times):
            i = int(np.searchsorted(a_times, tau_ns, side="right")) - 1
            if i >= 0 and a_times[i] <= self._cutoff_analysis_ns:
                base_qlat = float(a_vals[i])
        if base_qlat is None and len(sr_times):
            j = int(np.searchsorted(sr_times, tau_ns, side="right")) - 1
            if j >= 0:
                base_qlat = float(sr_vals[j])
        if base_qlat is None:
            base_qlat = float(last_known) if last_known is not None else 0.0
        return float(base_qlat * self.ratio(fid))
