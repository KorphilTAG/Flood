"""Run orchestrator, caching, stage timing, and RunStore."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
from typing import Any

import numpy as np
import pandas as pd

from flood.contracts.models import ForcingConfig, Scenario
from flood.contracts.validate import validate_json
from flood.engine.cube import HandCube
from flood.engine.ensemble import reduce_members, time_to_exceedance
from flood.engine.forcing import ForcingStore, load_forcing_store, ParquetForcingView
from flood.engine.mapping import map_member
from flood.engine.routing import route
from flood.interfaces import MEMBERS, RoutedSeries, StateArrays, TimeGridError
from flood.products.manifest import build_manifest, config_hash, make_run_id, merge_forcing
from flood.products.raster import write_depth_cog, write_tte_cog
from flood.products.tables import build_gauges, build_reaches
from flood.scenario import load_scenario
from flood.timegrid import check_pair, grid_range, parse_iso, snap_p, snap_t, to_compact, to_iso
from flood.timing import StageTimer

logger = logging.getLogger("flood.run")


@dataclass(frozen=True)
class ResolvedQuery:
    """Snapped and validated query."""
    mode: str
    p: datetime | None
    t: datetime
    p_internal: datetime
    horizon_minutes: int
    requested: dict[str, str]


def _compact_timestamp(val: datetime | str | None) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return to_compact(val)
    if isinstance(val, str):
        if val.lower() == "hindsight":
            return "hindsight"
        if len(val) == 14 and val[8] == "T" and val.endswith("Z"):
            return val
        return to_compact(parse_iso(val))
    raise ValueError(f"Cannot convert {val!r} to compact timestamp")


class Run:
    """One scenario under one forcing configuration producing products with caching and timing."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        data_dir: Path,
        manifest: dict,
        scenario: Scenario,
        cube: HandCube,
        store: ForcingStore,
        url_base: str = "/runs",
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.data_dir = Path(data_dir)
        self.manifest = manifest
        self.scenario = scenario
        self.cube = cube
        self.store = store
        self.url_base = url_base

        self.record_start = pd.to_datetime(scenario.hydrology.record.start, utc=True).to_pydatetime()
        self.record_end = pd.to_datetime(scenario.hydrology.record.end, utc=True).to_pydatetime()
        self.max_horizon_minutes = int(manifest.get("time", {}).get("max_horizon_minutes", 360))

        # In-memory LRU cache of RoutedSeries, maxsize=8
        self._routed_cache: OrderedDict[datetime, RoutedSeries] = OrderedDict()

    def resolve(self, p: datetime | str | None, t: datetime | str) -> ResolvedQuery:
        """Resolve, snap, and validate a (p, t) query against the scenario record and horizon."""
        req_p = "hindsight" if (p is None or (isinstance(p, str) and p.lower() == "hindsight")) else (p if isinstance(p, str) else to_iso(p))
        req_t = t if isinstance(t, str) else to_iso(t)
        requested = {"p": req_p, "t": req_t}

        t_dt = parse_iso(t) if isinstance(t, str) else t
        t_snapped = snap_t(t_dt)

        if p is None or (isinstance(p, str) and p.lower() == "hindsight"):
            mode = "hindsight"
            p_resolved = None
            p_internal = self.record_end
            horizon_minutes = 0
            if t_snapped < self.record_start or t_snapped > self.record_end:
                raise TimeGridError(
                    code="outside_record",
                    message=f"Target time {t_snapped} is outside record [{self.record_start}, {self.record_end}]",
                )
        else:
            p_dt = parse_iso(p) if isinstance(p, str) else p
            p_snapped = snap_p(p_dt)
            check_pair(p_snapped, t_snapped, self.record_start, self.record_end, self.max_horizon_minutes)
            p_resolved = p_snapped
            p_internal = p_snapped
            horizon_minutes = int(round((t_snapped - p_snapped).total_seconds() / 60))
            mode = "nowcast" if t_snapped == p_snapped else "forecast"

        return ResolvedQuery(
            mode=mode,
            p=p_resolved,
            t=t_snapped,
            p_internal=p_internal,
            horizon_minutes=horizon_minutes,
            requested=requested,
        )

    def routed(self, p_internal: datetime) -> RoutedSeries:
        """Fetch or compute the RoutedSeries for p_internal from an LRU cache of size 8."""
        if p_internal.tzinfo is None:
            p_dt = p_internal.replace(tzinfo=timezone.utc)
        else:
            p_dt = p_internal.astimezone(timezone.utc)

        if p_dt in self._routed_cache:
            self._routed_cache.move_to_end(p_dt)
            return self._routed_cache[p_dt]

        view = ParquetForcingView(
            self.scenario,
            self.store,
            p_dt,
            network=self.cube.network,
            gauges=self.cube.gauges,
        )
        config = ForcingConfig.model_validate(self.manifest["forcing"]["config"])
        routed_series = route(
            self.cube,
            view,
            self.scenario,
            config,
            members=MEMBERS,
            max_horizon_minutes=self.max_horizon_minutes,
            warmup_minutes=360,
        )

        self._routed_cache[p_dt] = routed_series
        if len(self._routed_cache) > 8:
            self._routed_cache.popitem(last=False)

        return routed_series

    def product_path(self, kind: str, p: datetime | str | None, t: datetime | str | None = None) -> Path:
        """Return the absolute path to a product file using manifest templates."""
        is_hindsight = (p is None or (isinstance(p, str) and p.lower() == "hindsight"))
        templates = self.manifest["products"]

        if is_hindsight:
            if kind == "raster":
                tpl = templates["hindsight_raster"]
            elif kind == "reaches":
                tpl = templates["hindsight_reaches"]
            else:
                raise ValueError(f"Product kind '{kind}' is not supported in hindsight mode")
        else:
            if kind in templates:
                tpl = templates[kind]
            else:
                raise ValueError(f"Unknown product kind: {kind}")

        p_str = _compact_timestamp(p) if not is_hindsight else ""
        t_str = _compact_timestamp(t) if t is not None else ""
        rel = tpl.format(p=p_str, t=t_str)
        return self.run_dir / rel

    def state(self, p: datetime | str | None, t: datetime | str, write: bool = False) -> tuple[StateArrays, dict]:
        """Compute state arrays and contract state response, with optional idempotent writing to disk."""
        res = self.resolve(p, t)
        p_internal = res.p_internal
        t_target = res.t

        raster_path = self.product_path("raster", res.p if res.mode != "hindsight" else "hindsight", t_target)
        raster_exists_before = raster_path.exists()
        is_cached_routed = p_internal in self._routed_cache

        if is_cached_routed:
            cache_status = "hit"
        elif raster_exists_before:
            cache_status = "precomputed"
        else:
            cache_status = "miss"

        with StageTimer() as st:
            with st.stage("state_estimation"):
                if not is_cached_routed:
                    view = ParquetForcingView(
                        self.scenario,
                        self.store,
                        p_internal,
                        network=self.cube.network,
                        gauges=self.cube.gauges,
                    )
                else:
                    view = None

            with st.stage("boundary_forecast"):
                pass

            with st.stage("routing"):
                if not is_cached_routed:
                    config = ForcingConfig.model_validate(self.manifest["forcing"]["config"])
                    routed_series = route(
                        self.cube,
                        view,
                        self.scenario,
                        config,
                        members=MEMBERS,
                        max_horizon_minutes=self.max_horizon_minutes,
                        warmup_minutes=360,
                    )
                    self._routed_cache[p_internal] = routed_series
                    if len(self._routed_cache) > 8:
                        self._routed_cache.popitem(last=False)
                else:
                    routed_series = self._routed_cache[p_internal]
                    self._routed_cache.move_to_end(p_internal)

            with st.stage("hand_mapping"):
                q_at_t = routed_series.at(t_target)
                fids = routed_series.feature_ids
                roughness = self.manifest["forcing"]["config"].get("roughness") or {}
                n_scale = float(roughness.get("manning_n_scale", 1.0))

                q_low = {fid: float(q_at_t[0, i]) for i, fid in enumerate(fids)}
                low_mf = map_member(self.cube, q_low, n_scale=n_scale, with_velocity=False)

                q_mid = {fid: float(q_at_t[1, i]) for i, fid in enumerate(fids)}
                mid_mf = map_member(self.cube, q_mid, n_scale=n_scale, with_velocity=True)

                q_high = {fid: float(q_at_t[2, i]) for i, fid in enumerate(fids)}
                high_mf = map_member(self.cube, q_high, n_scale=n_scale, with_velocity=False)

            with st.stage("reduce"):
                arrays = reduce_members(
                    low=low_mf,
                    mid=mid_mf,
                    high=high_mf,
                    p=res.p,
                    t=res.t,
                )

            with st.stage("write"):
                if write:
                    if not raster_path.exists():
                        write_depth_cog(raster_path, self.cube.grid, arrays)

                    reaches_path = self.product_path("reaches", res.p if res.mode != "hindsight" else "hindsight", t_target)
                    if not reaches_path.exists():
                        reaches_df = build_reaches(self, routed_series, t_target, mid_mf)
                        reaches_path.parent.mkdir(parents=True, exist_ok=True)
                        reaches_df.to_parquet(reaches_path, index=False)

                    if res.mode != "hindsight":
                        gauges_path = self.product_path("gauges", res.p)
                        if not gauges_path.exists():
                            gauges_df = build_gauges(self, routed_series, p_internal)
                            gauges_path.parent.mkdir(parents=True, exist_ok=True)
                            gauges_df.to_parquet(gauges_path, index=False)

                        tte_path = self.product_path("time_to_exceedance", res.p)
                        if not tte_path.exists():
                            tte_arr = self.tte(res.p, write=False)
                            write_tte_cog(tte_path, self.cube.grid, tte_arr)

        stages_ms = {
            "state_estimation": 0,
            "boundary_forecast": 0,
            "routing": 0,
            "hand_mapping": 0,
            "reduce": 0,
            "write": 0,
            "total": 0,
        }
        stages_ms.update(st.as_ms())
        arrays.compute_ms = stages_ms

        st.log(
            logger,
            run_id=self.run_id,
            mode=res.mode,
            p=to_iso(res.p) if res.p is not None else "hindsight",
            t=to_iso(res.t),
            cache=cache_status,
        )

        base = f"{self.url_base}/{self.run_id}"
        t_iso = to_iso(res.t)

        if res.mode == "hindsight":
            products = {
                "raster": f"{base}/raster?t={t_iso}",
                "reaches_parquet": f"{base}/hindsight/t={to_compact(res.t)}/reaches.parquet",
                "reaches_json": f"{base}/reaches?p=hindsight&t={t_iso}",
                "overlay_png": f"{base}/overlay.png?p=hindsight&t={t_iso}&band=depth_mid",
            }
        else:
            p_iso = to_iso(res.p)
            p_comp = to_compact(res.p)
            t_comp = to_compact(res.t)
            products = {
                "raster": f"{base}/raster?p={p_iso}&t={t_iso}",
                "reaches_parquet": f"{base}/products/p={p_comp}/t={t_comp}/reaches.parquet",
                "reaches_json": f"{base}/reaches?p={p_iso}&t={t_iso}",
                "time_to_exceedance": f"{base}/tte?p={p_iso}",
                "gauges_json": f"{base}/gauges?p={p_iso}",
                "overlay_png": f"{base}/overlay.png?p={p_iso}&t={t_iso}&band=depth_mid",
            }

        response = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "mode": res.mode,
            "p": to_iso(res.p) if res.p is not None else None,
            "t": to_iso(res.t),
            "requested": res.requested,
            "horizon_minutes": res.horizon_minutes,
            "members": list(MEMBERS),
            "products": products,
            "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "compute_ms": stages_ms,
            "cache": cache_status,
        }

        validate_json("state-response", response)
        return arrays, response

    def reaches(self, p: datetime | str | None, t: datetime | str) -> pd.DataFrame:
        """Compute reach DataFrame for query (p, t)."""
        res = self.resolve(p, t)
        routed = self.routed(res.p_internal)
        q_at_t = routed.at(res.t)
        fids = routed.feature_ids
        q_mid = {fid: float(q_at_t[1, i]) for i, fid in enumerate(fids)}
        roughness = self.manifest["forcing"]["config"].get("roughness") or {}
        n_scale = float(roughness.get("manning_n_scale", 1.0))
        mid_mf = map_member(self.cube, q_mid, n_scale=n_scale, with_velocity=True)
        return build_reaches(self, routed, res.t, mid_mf)

    def gauges(self, p: datetime | str | None) -> pd.DataFrame:
        """Compute gauges DataFrame for forecast cutoff p."""
        if p is None or (isinstance(p, str) and p.lower() == "hindsight"):
            p_internal = self.record_end
        else:
            p_dt = parse_iso(p) if isinstance(p, str) else p
            p_internal = snap_p(p_dt)

        routed = self.routed(p_internal)
        return build_gauges(self, routed, p_internal)

    def tte(self, p: datetime | str, write: bool = False) -> np.ndarray:
        """Compute time-to-exceedance float32 array [3, H, W] for cutoff p."""
        p_dt = parse_iso(p) if isinstance(p, str) else p
        p_snapped = snap_p(p_dt)
        t_end = min(p_snapped + pd.Timedelta(minutes=self.max_horizon_minutes), self.record_end)
        taus = grid_range(p_snapped, t_end)

        routed = self.routed(p_snapped)
        fids = routed.feature_ids
        roughness = self.manifest["forcing"]["config"].get("roughness") or {}
        n_scale = float(roughness.get("manning_n_scale", 1.0))

        series = []
        for tau in taus:
            m = int(round((tau - p_snapped).total_seconds() / 60))
            q_at_tau = routed.at(tau)
            q_mid = {fid: float(q_at_tau[1, i]) for i, fid in enumerate(fids)}
            mf = map_member(self.cube, q_mid, n_scale=n_scale, with_velocity=False)
            series.append((m, mf.depth))

        tte_arr = time_to_exceedance(series)

        if write:
            tte_path = self.product_path("time_to_exceedance", p_snapped)
            if not tte_path.exists():
                write_tte_cog(tte_path, self.cube.grid, tte_arr)

        return tte_arr

    @classmethod
    def create(
        cls,
        scenario: Scenario,
        mode: str,
        overrides: dict | None,
        runs_dir: Path | str,
        data_dir: Path | str,
        engine_version: str = "0.1.0",
    ) -> "Run":
        """Create or open a run on disk under runs_dir."""
        runs_dir = Path(runs_dir)
        data_dir = Path(data_dir)

        defaults = scenario.forcing_defaults.model_dump(mode="json", exclude_none=True)
        merged = merge_forcing(defaults, overrides)
        fc = ForcingConfig.model_validate(merged)
        cfg_dict = fc.model_dump(mode="json", exclude_none=True)
        cfg_hash = config_hash(cfg_dict)

        run_id = make_run_id(scenario.scenario_id, mode, cfg_hash)
        run_dir = runs_dir / run_id
        run_json_path = run_dir / "run.json"

        cube_dir = data_dir / "cube" / scenario.scenario_id
        cube = HandCube.load(cube_dir)
        store = load_forcing_store(scenario, data_dir)

        if run_json_path.exists():
            manifest = json.loads(run_json_path.read_text(encoding="utf-8"))
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "products").mkdir(parents=True, exist_ok=True)
            (run_dir / "hindsight").mkdir(parents=True, exist_ok=True)

            manifest = build_manifest(scenario, mode, cfg_dict, cube.grid, engine_version)
            run_json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # Persist scenario into run_dir for reliable Run.open
            (run_dir / "scenario.json").write_text(
                scenario.model_dump_json(indent=2, by_alias=True),
                encoding="utf-8",
            )

        return cls(
            run_id=run_id,
            run_dir=run_dir,
            data_dir=data_dir,
            manifest=manifest,
            scenario=scenario,
            cube=cube,
            store=store,
        )

    @classmethod
    def open(cls, run_dir: Path | str, data_dir: Path | str) -> "Run":
        """Open an existing run from disk."""
        run_dir = Path(run_dir)
        data_dir = Path(data_dir)
        run_json_path = run_dir / "run.json"
        if not run_json_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_json_path}")

        manifest = json.loads(run_json_path.read_text(encoding="utf-8"))
        validate_json("run-manifest", manifest)

        scenario_id = manifest["scenario"]["scenario_id"]

        # Locate scenario file
        scenario_candidates = [
            run_dir / "scenario.json",
            data_dir / "scenario.json",
            data_dir / "cube" / scenario_id / "scenario.json",
            Path("scenarios") / f"{scenario_id}.json",
            Path(__file__).resolve().parent.parent.parent.parent / "scenarios" / f"{scenario_id}.json",
            Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "mini_huc" / "out" / "scenario.json",
        ]
        scenario = None
        for cand in scenario_candidates:
            if cand.exists():
                try:
                    scenario = load_scenario(cand)
                    break
                except Exception:
                    continue

        if scenario is None:
            raise FileNotFoundError(f"Scenario file for {scenario_id} could not be located")

        cube_dir = data_dir / "cube" / scenario_id
        cube = HandCube.load(cube_dir)
        store = load_forcing_store(scenario, data_dir)

        return cls(
            run_id=manifest["run_id"],
            run_dir=run_dir,
            data_dir=data_dir,
            manifest=manifest,
            scenario=scenario,
            cube=cube,
            store=store,
        )


class RunStore:
    """Run directory manager providing list, get, create, and exists."""

    def __init__(self, runs_dir: Path | str, data_dir: Path | str, url_base: str = "/runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.data_dir = Path(data_dir)
        self.url_base = url_base

    def list(self) -> list[dict]:
        """Return all run manifests sorted by created_at."""
        if not self.runs_dir.exists():
            return []
        manifests = []
        for child in self.runs_dir.iterdir():
            run_json = child / "run.json"
            if run_json.is_file():
                try:
                    data = json.loads(run_json.read_text(encoding="utf-8"))
                    manifests.append(data)
                except Exception:
                    continue
        manifests.sort(key=lambda m: m.get("created_at", ""))
        return manifests

    def get(self, run_id: str) -> Run:
        """Load and return an existing Run by ID."""
        run_dir = self.runs_dir / run_id
        if not (run_dir / "run.json").is_file():
            raise KeyError(f"Run '{run_id}' not found in {self.runs_dir}")
        run = Run.open(run_dir, self.data_dir)
        run.url_base = self.url_base
        return run

    def create(self, scenario: Scenario, mode: str, overrides: dict | None = None) -> Run:
        """Create a new run and return it."""
        run = Run.create(scenario, mode, overrides, self.runs_dir, self.data_dir)
        run.url_base = self.url_base
        return run

    def exists(self, run_id: str) -> bool:
        """Check if a run with run_id exists."""
        return (self.runs_dir / run_id / "run.json").is_file()
