"""FakeRun and FakeRunStore test doubles for API tests."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flood.interfaces import (
    Grid,
    MIN_DEPTH_M,
    NODATA,
    RASTER_BANDS,
    StateArrays,
    TimeGridError,
)
from flood.products.raster import write_depth_cog, write_tte_cog
from flood.timegrid import (
    check_pair,
    parse_iso,
    snap_p,
    snap_t,
    to_compact,
    to_iso,
)


def _coerce_dt(val: datetime | str, name: str) -> datetime:
    if isinstance(val, str):
        return parse_iso(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    raise ValueError(f"{name} must be a datetime or ISO string")


class FakeRun:
    """Test fake for flood.engine.run.Run on the mini_huc grid."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        manifest: dict[str, Any],
        record_start: datetime | str = "2025-01-01T00:00:00Z",
        record_end: datetime | str = "2025-01-01T12:00:00Z",
        max_horizon_minutes: int = 360,
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.manifest = manifest
        self.record_start = _coerce_dt(record_start, "record_start")
        self.record_end = _coerce_dt(record_end, "record_end")
        self.max_horizon_minutes = max_horizon_minutes
        self.grid = Grid.from_bounds((0.0, 0.0, 400.0, 200.0), resolution_m=10.0, crs="EPSG:5070")

    def _resolve_pt(
        self,
        p: datetime | str | None,
        t: datetime | str | None,
    ) -> tuple[datetime | None, datetime | None]:
        p_dt: datetime | None = None
        if p is not None and p != "hindsight":
            p_dt = snap_p(_coerce_dt(p, "p"))
        t_dt: datetime | None = None
        if t is not None:
            t_dt = snap_t(_coerce_dt(t, "t"))
        return p_dt, t_dt

    def state(
        self,
        p: datetime | str,
        t: datetime | str,
        write: bool = False,
    ) -> tuple[StateArrays, dict[str, Any]]:
        is_hindsight = p == "hindsight"
        p_orig = str(p)
        t_orig = str(t)

        t_dt = snap_t(_coerce_dt(t, "t"))
        if is_hindsight:
            if t_dt < self.record_start or t_dt > self.record_end:
                raise TimeGridError(
                    code="outside_record",
                    message=f"Query ({p}, {t}) is outside record [{self.record_start}, {self.record_end}]",
                )
            mode = "hindsight"
            p_dt = None
            horizon_minutes = 0
            p_iso = None
            p_compact = "hindsight"
        else:
            p_dt = snap_p(_coerce_dt(p, "p"))
            check_pair(p_dt, t_dt, self.record_start, self.record_end, self.max_horizon_minutes)
            if t_dt == p_dt:
                mode = "nowcast"
                horizon_minutes = 0
            else:
                mode = "forecast"
                horizon_minutes = int((t_dt - p_dt).total_seconds() // 60)
            p_iso = to_iso(p_dt)
            p_compact = to_compact(p_dt)

        t_iso = to_iso(t_dt)
        t_compact = to_compact(t_dt)

        # Synthetic wet block on mini_huc grid (height=20, width=40)
        h, w = self.grid.height, self.grid.width
        depth_mid = np.zeros((h, w), dtype=np.float32)
        depth_mid[5:15, 10:30] = 1.5
        depth_low = (depth_mid * 0.8).astype(np.float32)
        depth_high = (depth_mid * 1.2).astype(np.float32)
        velocity_ms = np.where(depth_mid > 0, 1.2, 0.0).astype(np.float32)
        hazard_dv = (depth_mid * velocity_ms).astype(np.float32)
        prob_inundated = np.where(depth_mid >= MIN_DEPTH_M, 1.0, 0.0).astype(np.float32)

        compute_ms = {
            "state_estimation": 12,
            "boundary_forecast": 3,
            "routing": 8,
            "hand_mapping": 140,
            "reduce": 20,
            "write": 0,
            "total": 183,
        }

        arrays = StateArrays(
            p=p_dt,
            t=t_dt,
            depth_mid=depth_mid,
            depth_low=depth_low,
            depth_high=depth_high,
            velocity_ms=velocity_ms,
            hazard_dv=hazard_dv,
            prob_inundated=prob_inundated,
            compute_ms=compute_ms,
        )

        p_query = "hindsight" if is_hindsight else p_iso
        if is_hindsight:
            products = {
                "raster": f"/runs/{self.run_id}/raster?p=hindsight&t={t_iso}",
                "reaches_parquet": f"/runs/{self.run_id}/hindsight/t={t_compact}/reaches.parquet",
                "reaches_json": f"/runs/{self.run_id}/reaches?p=hindsight&t={t_iso}",
                "overlay_png": f"/runs/{self.run_id}/overlay.png?p=hindsight&t={t_iso}&band=depth_mid",
            }
        else:
            products = {
                "raster": f"/runs/{self.run_id}/raster?p={p_iso}&t={t_iso}",
                "reaches_parquet": f"/runs/{self.run_id}/products/p={p_compact}/t={t_compact}/reaches.parquet",
                "reaches_json": f"/runs/{self.run_id}/reaches?p={p_iso}&t={t_iso}",
                "time_to_exceedance": f"/runs/{self.run_id}/tte?p={p_iso}",
                "gauges_json": f"/runs/{self.run_id}/gauges?p={p_iso}",
                "overlay_png": f"/runs/{self.run_id}/overlay.png?p={p_iso}&t={t_iso}&band=depth_mid",
            }

        response_dict = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "mode": mode,
            "p": p_iso,
            "t": t_iso,
            "requested": {"p": p_orig, "t": t_orig},
            "horizon_minutes": horizon_minutes,
            "members": ["low", "mid", "high"],
            "products": products,
            "computed_at": "2026-09-06T01:05:12Z",
            "compute_ms": compute_ms,
            "cache": "miss",
        }

        if write:
            raster_file = self.product_path("raster", p, t)
            if not raster_file.exists():
                write_depth_cog(raster_file, self.grid, arrays)
            reaches_file = self.product_path("reaches", p, t)
            if not reaches_file.exists():
                df = self.reaches(p, t)
                df.to_parquet(reaches_file)

        return arrays, response_dict

    def reaches(self, p: datetime | str, t: datetime | str) -> pd.DataFrame:
        is_hindsight = p == "hindsight"
        t_dt = snap_t(_coerce_dt(t, "t"))
        if is_hindsight:
            if t_dt < self.record_start or t_dt > self.record_end:
                raise TimeGridError(
                    code="outside_record",
                    message=f"Query ({p}, {t}) is outside record [{self.record_start}, {self.record_end}]",
                )
            p_dt = None
            is_forecast = False
            p_val = "2025-07-04T08:00:00Z"
        else:
            p_dt = snap_p(_coerce_dt(p, "p"))
            check_pair(p_dt, t_dt, self.record_start, self.record_end, self.max_horizon_minutes)
            is_forecast = t_dt > p_dt
            p_val = to_iso(p_dt)

        t_val = to_iso(t_dt)
        data = [
            {
                "reach_ref": "reach:3586192",
                "feature_id": 3586192,
                "levelpath_id": 1619000006,
                "stream_order": 4,
                "gauge_ref": "gauge:08165500",
                "p": p_val,
                "t": t_val,
                "is_forecast": is_forecast,
                "q_mid_cms": 520.0,
                "q_low_cms": 520.0,
                "q_high_cms": 520.0,
                "stage_mid_m": 3.41,
                "stage_low_m": 3.41,
                "stage_high_m": 3.41,
                "rate_of_rise_m_per_h": 4.2,
                "velocity_ms": 2.6,
                "source": "observed",
                "clipped_to_src": False,
            },
            {
                "reach_ref": "reach:3585750",
                "feature_id": 3585750,
                "levelpath_id": 1619000016,
                "stream_order": 3,
                "gauge_ref": None,
                "p": p_val,
                "t": t_val,
                "is_forecast": is_forecast,
                "q_mid_cms": 310.0,
                "q_low_cms": 310.0,
                "q_high_cms": 310.0,
                "stage_mid_m": 3.05,
                "stage_low_m": 3.05,
                "stage_high_m": 3.05,
                "rate_of_rise_m_per_h": 3.8,
                "velocity_ms": 2.4,
                "source": "mass_balance",
                "clipped_to_src": False,
            },
            {
                "reach_ref": "reach:3585724",
                "feature_id": 3585724,
                "levelpath_id": 1619000006,
                "stream_order": 4,
                "gauge_ref": "gauge:08166200",
                "p": p_val,
                "t": t_val,
                "is_forecast": is_forecast,
                "q_mid_cms": 1450.0,
                "q_low_cms": 980.0,
                "q_high_cms": 2100.0,
                "stage_mid_m": 6.8,
                "stage_low_m": 5.6,
                "stage_high_m": 8.1,
                "rate_of_rise_m_per_h": 2.9,
                "velocity_ms": 3.1,
                "source": "routed",
                "clipped_to_src": False,
            },
        ]
        return pd.DataFrame(data)

    def gauges(self, p: datetime | str) -> pd.DataFrame:
        if p == "hindsight":
            p_val = "2025-07-04T08:00:00Z"
        else:
            p_dt = snap_p(_coerce_dt(p, "p"))
            if p_dt < self.record_start or p_dt > self.record_end:
                raise TimeGridError(
                    code="outside_record",
                    message=f"p ({p_dt}) is outside record [{self.record_start}, {self.record_end}]",
                )
            p_val = to_iso(p_dt)

        data = [
            {
                "gauge_ref": "gauge:08165500",
                "site": "08165500",
                "feature_id": 3586192,
                "p": p_val,
                "t": p_val,
                "is_forecast": False,
                "observed_q_cms": 520.0,
                "observed_wse_m": 528.2,
                "predicted_q_mid_cms": 520.0,
                "predicted_q_low_cms": 520.0,
                "predicted_q_high_cms": 520.0,
                "predicted_wse_mid_m": 528.0,
                "wse_datum": "NAVD88",
            },
            {
                "gauge_ref": "gauge:08166200",
                "site": "08166200",
                "feature_id": 3585724,
                "p": p_val,
                "t": p_val,
                "is_forecast": False,
                "observed_q_cms": None,
                "observed_wse_m": None,
                "predicted_q_mid_cms": 1450.0,
                "predicted_q_low_cms": 980.0,
                "predicted_q_high_cms": 2100.0,
                "predicted_wse_mid_m": 494.9,
                "wse_datum": "NAVD88",
            },
        ]
        return pd.DataFrame(data)

    def tte(self, p: datetime | str, write: bool = False) -> np.ndarray:
        if p == "hindsight":
            raise TimeGridError(code="hindsight_has_no_tte", message="Hindsight has no time-to-exceedance")
        p_dt = snap_p(_coerce_dt(p, "p"))
        if p_dt < self.record_start or p_dt > self.record_end:
            raise TimeGridError(
                code="outside_record",
                message=f"p ({p_dt}) is outside record [{self.record_start}, {self.record_end}]",
            )
        h, w = self.grid.height, self.grid.width
        arr = np.full((3, h, w), -1.0, dtype=np.float32)
        arr[0, 5:15, 10:30] = 15.0
        arr[1, 5:15, 10:30] = 30.0
        arr[2, 5:15, 10:30] = 60.0

        if write:
            out_file = self.product_path("time_to_exceedance", p)
            if not out_file.exists():
                write_tte_cog(out_file, self.grid, arr)
        return arr

    def product_path(self, kind: str, p: Any, t: Any = None) -> Path:
        is_hindsight = p == "hindsight"
        if is_hindsight:
            t_dt = snap_t(_coerce_dt(t, "t")) if t is not None else None
            t_compact = to_compact(t_dt) if t_dt is not None else ""
            if kind == "raster":
                path = self.run_dir / "hindsight" / f"t={t_compact}" / "depth.tif"
            elif kind == "reaches":
                path = self.run_dir / "hindsight" / f"t={t_compact}" / "reaches.parquet"
            else:
                raise ValueError(f"Unknown hindsight product kind: {kind}")
        else:
            p_dt = snap_p(_coerce_dt(p, "p"))
            p_compact = to_compact(p_dt)
            if kind == "raster":
                t_dt = snap_t(_coerce_dt(t, "t")) if t is not None else None
                t_compact = to_compact(t_dt) if t_dt is not None else ""
                path = self.run_dir / "products" / f"p={p_compact}" / f"t={t_compact}" / "depth.tif"
            elif kind == "reaches":
                t_dt = snap_t(_coerce_dt(t, "t")) if t is not None else None
                t_compact = to_compact(t_dt) if t_dt is not None else ""
                path = self.run_dir / "products" / f"p={p_compact}" / f"t={t_compact}" / "reaches.parquet"
            elif kind == "time_to_exceedance":
                path = self.run_dir / "products" / f"p={p_compact}" / "time_to_exceedance.tif"
            elif kind == "gauges":
                path = self.run_dir / "products" / f"p={p_compact}" / "gauges.parquet"
            else:
                raise ValueError(f"Unknown product kind: {kind}")

        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class FakeRunStore:
    """In-memory or directory-backed FakeRunStore for testing."""

    def __init__(self, runs_dir: Path | str, data_dir: Path | str = "data") -> None:
        self.runs_dir = Path(runs_dir)
        self.data_dir = Path(data_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.url_base = ""
        self._runs: dict[str, FakeRun] = {}

    def list(self) -> list[dict[str, Any]]:
        return [r.manifest for r in self._runs.values()]

    def get(self, run_id: str) -> FakeRun:
        if run_id not in self._runs:
            raise KeyError(f"Unknown run: {run_id}")
        return self._runs[run_id]

    def exists(self, run_id: str) -> bool:
        return run_id in self._runs

    def create(
        self,
        scenario: Any,
        mode: str,
        overrides: dict[str, Any] | None = None,
    ) -> FakeRun:
        if isinstance(scenario, str):
            scenario_id = scenario
            scenario_dict = {
                "scenario_id": scenario_id,
                "name": f"Scenario {scenario_id}",
                "huc8": ["12100201"],
                "fim_version": "4.9.9.0",
                "record_start": "2025-07-03T12:00:00Z",
                "record_end": "2025-07-05T12:00:00Z",
                "timezone": "UTC",
            }
            base_forcing = None
        elif hasattr(scenario, "scenario_id"):
            scenario_id = scenario.scenario_id
            scenario_dict = {
                "scenario_id": scenario_id,
                "name": scenario.name,
                "huc8": list(scenario.hydrology.huc8),
                "fim_version": scenario.hydrology.fim_version,
                "record_start": to_iso(scenario.hydrology.record.start)
                if hasattr(scenario.hydrology.record.start, "tzinfo")
                else str(scenario.hydrology.record.start),
                "record_end": to_iso(scenario.hydrology.record.end)
                if hasattr(scenario.hydrology.record.end, "tzinfo")
                else str(scenario.hydrology.record.end),
                "timezone": scenario.timezone,
            }
            base_forcing = (
                scenario.forcing_defaults.model_dump(mode="json")
                if hasattr(scenario, "forcing_defaults") and hasattr(scenario.forcing_defaults, "model_dump")
                else None
            )
        elif isinstance(scenario, dict):
            scenario_id = scenario["scenario_id"]
            scenario_dict = {
                "scenario_id": scenario_id,
                "name": scenario.get("name", scenario_id),
                "huc8": scenario.get("hydrology", {}).get("huc8", ["12100201"]),
                "fim_version": scenario.get("hydrology", {}).get("fim_version", "4.9.9.0"),
                "record_start": scenario.get("hydrology", {}).get("record", {}).get("start", "2025-07-03T12:00:00Z"),
                "record_end": scenario.get("hydrology", {}).get("record", {}).get("end", "2025-07-05T12:00:00Z"),
                "timezone": scenario.get("timezone", "UTC"),
            }
            base_forcing = scenario.get("forcing_defaults")
        else:
            raise ValueError(f"Unsupported scenario type: {type(scenario)}")

        if base_forcing is None:
            base_forcing = {
                "sources": [
                    {
                        "type": "usgs_continuous",
                        "availability_latency_min": 5,
                        "sites": ["08165300", "08165500", "08166000", "08166140", "08166200", "08166250", "08167000"],
                        "parameters": ["00060", "00065"],
                    },
                    {"type": "nwm_analysis_assim", "availability_latency_min": 60},
                    {"type": "nwm_short_range", "availability_latency_min": 90, "max_lead_hours": 6},
                ],
                "state_estimation": {
                    "bias_correction": "nearest_gauge_ratio",
                    "use_junction_inferences": True,
                    "ratio_clamp": [0.2, 10.0],
                },
                "boundary_forecast": {
                    "method": "trend_relax",
                    "members": {"low": 0.5, "mid": 1.0, "high": 1.5},
                    "relax_minutes": 60,
                    "trend_window_minutes": 30,
                },
                "routing": {"method": "muskingum_cunge", "dt_minutes": 1},
                "roughness": {"manning_n_scale": 1.0},
                "scenario_overrides": [],
            }

        if overrides is not None:
            # Check for illegal override keys
            valid_override_keys = {
                "sources",
                "state_estimation",
                "boundary_forecast",
                "routing",
                "roughness",
                "scenario_overrides",
            }
            if set(overrides.keys()) - valid_override_keys:
                raise ValueError("Invalid forcing override keys")

        merged_forcing = dict(base_forcing)
        if overrides:
            merged_forcing.update(overrides)

        config_str = json.dumps(merged_forcing, sort_keys=True)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:6]
        run_id = f"{scenario_id}-{mode}-{config_hash}"

        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": "1.0",
            "run_id": run_id,
            "created_at": "2026-09-06T01:00:00Z",
            "engine_version": "0.1.0",
            "mode": mode,
            "scenario": scenario_dict,
            "grid": {
                "crs": "EPSG:5070",
                "resolution_m": 10.0,
                "width": 40,
                "height": 20,
                "transform": [10.0, 0.0, 0.0, 0.0, -10.0, 200.0],
                "bounds": [0.0, 0.0, 400.0, 200.0],
            },
            "time": {"step_minutes": 5, "max_horizon_minutes": 360},
            "members": ["low", "mid", "high"],
            "forcing": {
                "config": merged_forcing,
                "config_hash": f"sha256:{hashlib.sha256(config_str.encode()).hexdigest()}",
            },
            "products": {
                "raster": "products/p={p}/t={t}/depth.tif",
                "reaches": "products/p={p}/t={t}/reaches.parquet",
                "time_to_exceedance": "products/p={p}/time_to_exceedance.tif",
                "gauges": "products/p={p}/gauges.parquet",
                "hindsight_raster": "hindsight/t={t}/depth.tif",
                "hindsight_reaches": "hindsight/t={t}/reaches.parquet",
            },
            "limitations": [
                "HAND proxy on synthetic grid.",
            ],
        }

        # Save run.json to disk
        (run_dir / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        run = FakeRun(
            run_id=run_id,
            run_dir=run_dir,
            manifest=manifest,
            record_start=scenario_dict["record_start"],
            record_end=scenario_dict["record_end"],
        )
        self._runs[run_id] = run
        return run
