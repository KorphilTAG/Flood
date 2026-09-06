"""Manifest creation, config hashing, and forcing configuration merge."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from flood.contracts.models import ForcingConfig, Scenario
from flood.contracts.validate import validate_json
from flood.interfaces import Grid, MEMBERS, STEP_MINUTES
from flood.timegrid import to_iso

ENGINE_LIMITATIONS: tuple[str, ...] = (
    "HAND underpredicts on stream order 1 and 2.",
    "Velocity is a Manning proxy from reach discharge over wetted area, not a measurement.",
    "Debris dams, bridge backwater, and channel avulsion are not modelled.",
    "Rating curves use a uniform Manning n of 0.06.",
)


def config_hash(config: dict | ForcingConfig) -> str:
    """Return 'sha256:' + sha256 of canonical json of forcing configuration."""
    if hasattr(config, "model_dump"):
        data = config.model_dump(mode="json", exclude_none=True)
    else:
        data = config
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def make_run_id(scenario_id: str, mode: str, config_hash_val: str) -> str:
    """Generate run_id slug: <scenario_id>-<mode>-<first 6 hex of config_hash>."""
    return f"{scenario_id}-{mode}-{config_hash_val[7:13]}"


def merge_forcing(defaults: dict, overrides: dict | None) -> dict:
    """Deep-merge overrides into defaults, replace lists wholesale, and validate against forcing-config."""
    if hasattr(defaults, "model_dump"):
        d = defaults.model_dump(mode="json", exclude_none=True)
    else:
        d = copy.deepcopy(defaults)

    if overrides is None:
        o: dict[str, Any] = {}
    elif hasattr(overrides, "model_dump"):
        o = overrides.model_dump(mode="json", exclude_none=True)
    else:
        o = overrides

    def _deep_merge(base: dict, patch: dict) -> dict:
        result = copy.deepcopy(base)
        for k, v in patch.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = _deep_merge(result[k], v)
            elif isinstance(v, list):
                result[k] = copy.deepcopy(v)
            else:
                result[k] = copy.deepcopy(v)
        return result

    merged = _deep_merge(d, o)
    validate_json("forcing-config", merged)
    return merged


def build_manifest(
    scenario: Scenario,
    mode: str,
    merged_config: dict | ForcingConfig,
    grid: Grid,
    engine_version: str,
    created_at: datetime | str | None = None,
) -> dict:
    """Build a run manifest dictionary that validates against run-manifest schema."""
    if not isinstance(merged_config, ForcingConfig):
        fc = ForcingConfig.model_validate(merged_config)
    else:
        fc = merged_config

    cfg_dict = fc.model_dump(mode="json", exclude_none=True)
    cfg_hash = config_hash(cfg_dict)
    run_id = make_run_id(scenario.scenario_id, mode, cfg_hash)

    if created_at is None:
        created_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(created_at, datetime):
        created_at_str = to_iso(created_at)
    else:
        created_at_str = str(created_at)

    limitations = list(ENGINE_LIMITATIONS)
    n_scale = float(fc.roughness.manning_n_scale) if fc.roughness is not None else 1.0
    if n_scale != 1.0:
        limitations.append(
            f"Rating-curve conveyance is scaled by a Manning n scale of {n_scale:g} for stage and wave celerity, "
            "calibrated to gauge observations for this scenario; see the scenario's decision record."
        )
    for ji in scenario.hydrology.junction_inferences:
        limitations.append(f"{ji.label} is inferred by mass balance, not observed.")

    products_template = {
        "raster": "products/p={p}/t={t}/depth.tif",
        "reaches": "products/p={p}/t={t}/reaches.parquet",
        "time_to_exceedance": "products/p={p}/time_to_exceedance.tif",
        "gauges": "products/p={p}/gauges.parquet",
        "hindsight_raster": "hindsight/t={t}/depth.tif",
        "hindsight_reaches": "hindsight/t={t}/reaches.parquet",
    }

    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": created_at_str,
        "engine_version": engine_version,
        "mode": mode,
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "huc8": list(scenario.hydrology.huc8),
            "fim_version": scenario.hydrology.fim_version,
            "record_start": scenario.hydrology.record.start,
            "record_end": scenario.hydrology.record.end,
            "timezone": scenario.timezone,
        },
        "grid": {
            "crs": "EPSG:5070",
            "resolution_m": float(grid.resolution_m),
            "width": int(grid.width),
            "height": int(grid.height),
            "transform": list(grid.transform),
            "bounds": list(grid.bounds),
        },
        "time": {
            "step_minutes": STEP_MINUTES,
            "max_horizon_minutes": 360,
        },
        "members": list(MEMBERS),
        "forcing": {
            "config": cfg_dict,
            "config_hash": cfg_hash,
        },
        "products": products_template,
        "limitations": limitations,
    }

    validate_json("run-manifest", manifest)
    return manifest
