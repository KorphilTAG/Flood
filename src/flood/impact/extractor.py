"""Contract 2 extraction: Contract 1 rasters plus configured exposure features to facts.

The extractor is a direct raster consumer. It takes explicit COG and reach-sidecar paths
so it can be driven by the engine in production and by fixtures in tests, and it never
opens a database itself: an exposure store is injected.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

import geopandas as gpd
import numpy as np
import rasterio

from flood.contracts.models import ExposureLayer, Scenario
from flood.contracts.validate import validate_json
from flood.impact.postgis import ExposureConfigError, require_postgis
from flood.interfaces import MIN_DEPTH_M, NODATA
from flood.timegrid import to_compact, to_iso

SCHEMA_VERSION = "1.0"
#: Same-`p` targets required by Contract 2, in minutes after the requested `t`.
PROJECTION_OFFSETS_MIN: tuple[int, ...] = (30, 60, 120)
#: Contract 1 band descriptions this extractor reads. Resolved by name, never by index.
REQUIRED_BANDS: tuple[str, ...] = ("depth_mid", "velocity_ms", "hazard_dv")


class ExposureStore(Protocol):
    """What the extractor needs from an exposure source; PostGISExposureStore implements it."""

    def load(
        self,
        layer: ExposureLayer,
        bounds: tuple[float, float, float, float],
        bounds_crs: str,
        target_crs: str,
    ) -> gpd.GeoDataFrame: ...


class ImpactExtractionError(ValueError):
    """A required engine product is missing or inconsistent."""


@dataclass(frozen=True)
class RasterTarget:
    """One evaluated time and the COG that backs it."""
    t: datetime
    path: Path


@dataclass
class _BandStats:
    depth_max: float
    depth_mean: float
    wet_fraction: float
    hazard_max: float


def _open_bands(path: Path) -> tuple[rasterio.DatasetReader, dict[str, int]]:
    """Open a Contract 1 COG and map required band descriptions to 1-based indices."""
    if not Path(path).exists():
        raise ImpactExtractionError(f"Required Contract 1 product is missing: {path}")
    ds = rasterio.open(path)
    index = {desc: i for i, desc in enumerate(ds.descriptions, 1) if desc}
    missing = [b for b in REQUIRED_BANDS if b not in index]
    if missing:
        ds.close()
        raise ImpactExtractionError(
            f"{path} does not carry required band description(s) {missing}; "
            f"found {list(ds.descriptions)}"
        )
    return ds, index


def _check_grid(reference: rasterio.DatasetReader, other: rasterio.DatasetReader, path: Path) -> None:
    """Projections must share the current raster's grid or the samples are not comparable."""
    if other.crs != reference.crs:
        raise ImpactExtractionError(f"{path} CRS {other.crs} does not match {reference.crs}")
    if (other.width, other.height) != (reference.width, reference.height):
        raise ImpactExtractionError(
            f"{path} shape {(other.height, other.width)} does not match "
            f"{(reference.height, reference.width)}"
        )
    if not np.allclose(np.asarray(other.transform)[:6], np.asarray(reference.transform)[:6], atol=1e-6):
        raise ImpactExtractionError(f"{path} affine transform does not match the current raster")


def _clean(values: np.ndarray) -> np.ndarray:
    """Drop nodata. `0` survives: dry ground is evidence, absent data is not."""
    arr = np.asarray(values, dtype="float64").ravel()
    arr = arr[np.isfinite(arr)]
    return arr[arr != NODATA]


def _stats_for_geometries(
    ds: rasterio.DatasetReader, bands: Mapping[str, int], gdf: gpd.GeoDataFrame, geom_kind: str
) -> list[_BandStats]:
    """Point-sample points; take zonal summaries over lines and polygons."""
    from rasterstats import point_query, zonal_stats

    affine = ds.transform
    depth = ds.read(bands["depth_mid"])
    hazard = ds.read(bands["hazard_dv"])
    geoms = list(gdf.geometry)

    if geom_kind == "point":
        d = point_query(geoms, depth, affine=affine, nodata=NODATA, interpolate="nearest")
        h = point_query(geoms, hazard, affine=affine, nodata=NODATA, interpolate="nearest")
        out = []
        for dv, hv in zip(d, h):
            dvals = _clean(np.array([dv if dv is not None else np.nan]))
            hvals = _clean(np.array([hv if hv is not None else np.nan]))
            dmax = float(dvals.max()) if dvals.size else 0.0
            out.append(
                _BandStats(
                    depth_max=dmax,
                    depth_mean=float(dvals.mean()) if dvals.size else 0.0,
                    wet_fraction=1.0 if dmax >= MIN_DEPTH_M else 0.0,
                    hazard_max=float(hvals.max()) if hvals.size else 0.0,
                )
            )
        return out

    # `all_touched` keeps a road narrower than one cell from sampling nothing at all.
    d_stats = zonal_stats(
        geoms, depth, affine=affine, nodata=NODATA, all_touched=True, raster_out=True, stats=["count"]
    )
    h_stats = zonal_stats(
        geoms, hazard, affine=affine, nodata=NODATA, all_touched=True, stats=["max"]
    )
    out = []
    for ds_row, hs_row in zip(d_stats, h_stats):
        masked = ds_row.get("mini_raster_array")
        dvals = _clean(masked.compressed()) if masked is not None else np.array([])
        dmax = float(dvals.max()) if dvals.size else 0.0
        hmax = hs_row.get("max")
        out.append(
            _BandStats(
                depth_max=dmax,
                depth_mean=float(dvals.mean()) if dvals.size else 0.0,
                wet_fraction=float((dvals >= MIN_DEPTH_M).mean()) if dvals.size else 0.0,
                hazard_max=float(hmax) if hmax is not None and hmax != NODATA else 0.0,
            )
        )
    return out


def _fact_kind(layer: ExposureLayer) -> str:
    """Points and lines are passability facts; polygons are exposure facts."""
    return "threatened" if layer.geometry == "polygon" else "impassable"


def _depth_threshold(layer: ExposureLayer) -> float | None:
    impact = layer.impact
    if impact is None:
        return None
    return impact.threatened_depth_m if layer.geometry == "polygon" else impact.impassable_depth_m


def require_threshold(layer: ExposureLayer) -> None:
    """A layer with no threshold applicable to its geometry type cannot be classified."""
    if _depth_threshold(layer) is None and (layer.impact is None or layer.impact.hazard_dv_limit is None):
        wanted = "threatened_depth_m" if layer.geometry == "polygon" else "impassable_depth_m"
        raise ExposureConfigError(
            f"Exposure layer '{layer.layer_id}' is '{layer.geometry}' but declares no "
            f"impact.{wanted} or impact.hazard_dv_limit"
        )


def _is_impacted(layer: ExposureLayer, stats: _BandStats) -> bool:
    """Registry thresholds only: no layer name, depth, or location is hard-coded here."""
    depth_thr = _depth_threshold(layer)
    if depth_thr is not None and stats.depth_max >= depth_thr:
        return True
    hazard_limit = layer.impact.hazard_dv_limit if layer.impact else None
    if hazard_limit is not None and stats.hazard_max >= hazard_limit:
        return True
    return False


def _attributes(row: Any, layer: ExposureLayer) -> dict[str, Any]:
    """Exactly the registry allow-list, coerced to JSON scalars."""
    out: dict[str, Any] = {}
    for name in layer.attributes:
        value = row[name]
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            out[name] = None
        elif isinstance(value, (np.integer,)):
            out[name] = int(value)
        elif isinstance(value, (np.floating,)):
            out[name] = float(value)
        elif isinstance(value, (np.bool_,)):
            out[name] = bool(value)
        elif isinstance(value, (str, int, float, bool)):
            out[name] = value
        else:
            out[name] = str(value)
    return out


class ImpactExtractor:
    """Turns explicit Contract 1 product paths into a validated Contract 2 document."""

    def __init__(self, scenario: Scenario, store: ExposureStore) -> None:
        self.scenario = scenario
        self.store = store
        self.layers: dict[str, ExposureLayer] = {l.layer_id: l for l in scenario.exposure_layers}

    def extract(
        self,
        run_id: str,
        p: datetime | None,
        t: datetime,
        current_cog: Path,
        projection_cogs: Mapping[datetime, Path] | None = None,
        reaches_parquet: Path | None = None,
    ) -> dict:
        """Build the Contract 2 payload for one resolved `(p, t)` query.

        ``projection_cogs`` holds same-`p` rasters for targets inside the Contract 1
        horizon. A target absent from the mapping is omitted from `projections`; a target
        present but unreadable is an error.
        """
        targets: list[RasterTarget] = [RasterTarget(t=t, path=Path(current_cog))]
        for offset in PROJECTION_OFFSETS_MIN:
            t_future = t + timedelta(minutes=offset)
            path = (projection_cogs or {}).get(t_future)
            if path is not None:
                targets.append(RasterTarget(t=t_future, path=Path(path)))

        for layer in self.scenario.exposure_layers:
            require_postgis(layer)
            require_threshold(layer)

        current_ds, current_bands = _open_bands(targets[0].path)
        try:
            crs = str(current_ds.crs)
            bounds = tuple(current_ds.bounds)
            features = {
                layer_id: self.store.load(layer, bounds, crs, crs)
                for layer_id, layer in self.layers.items()
            }
            # feature_ref -> {t: impacted}, plus the current-raster stats it is reported with.
            per_target: dict[datetime, dict[str, bool]] = {}
            current_stats: dict[str, tuple[ExposureLayer, Any, _BandStats]] = {}

            for target in targets:
                if target.t == targets[0].t:
                    ds, bands = current_ds, current_bands
                    close = False
                else:
                    ds, bands = _open_bands(target.path)
                    _check_grid(current_ds, ds, target.path)
                    close = True
                try:
                    impacted: dict[str, bool] = {}
                    for layer_id, layer in self.layers.items():
                        gdf = features[layer_id]
                        if gdf.empty:
                            continue
                        stats = _stats_for_geometries(ds, bands, gdf, layer.geometry)
                        for (_, row), st in zip(gdf.iterrows(), stats):
                            ref = f"{layer_id}:{row[layer.id_field]}"
                            impacted[ref] = _is_impacted(layer, st)
                            if target is targets[0]:
                                current_stats[ref] = (layer, row, st)
                    per_target[target.t] = impacted
                finally:
                    if close:
                        ds.close()
        finally:
            current_ds.close()

        facts = self._build_facts(targets, per_target, current_stats)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "p": to_iso(p) if p is not None else None,
            "t": to_iso(t),
            "velocity_is_proxy": True,
            "facts": facts,
            "egress": self._build_egress(features, facts, targets),
            "reaches": _read_reaches(reaches_parquet),
        }
        validate_json("impact-json", payload)
        return payload

    def _build_facts(
        self,
        targets: list[RasterTarget],
        per_target: dict[datetime, dict[str, bool]],
        current_stats: dict[str, tuple[ExposureLayer, Any, _BandStats]],
    ) -> list[dict]:
        """One fact per feature impacted at any evaluated target; dry features are omitted."""
        facts = []
        current_t = targets[0].t
        for ref, (layer, row, st) in current_stats.items():
            projections = [
                {"t": to_iso(tg.t), "impacted": bool(per_target[tg.t].get(ref, False))}
                for tg in targets[1:]
            ]
            impacted_now = bool(per_target[current_t].get(ref, False))
            first_impacted = next(
                (tg.t for tg in targets if per_target[tg.t].get(ref, False)), None
            )
            if first_impacted is None:
                continue
            facts.append(
                {
                    "feature_ref": ref,
                    "kind": _fact_kind(layer),
                    "impacted_now": impacted_now,
                    "depth_max_m": round(max(st.depth_max, 0.0), 4),
                    "depth_mean_m": round(max(st.depth_mean, 0.0), 4),
                    "wet_fraction": round(st.wet_fraction, 4),
                    "hazard_dv_max_m2_per_s": round(max(st.hazard_max, 0.0), 4),
                    "attributes": _attributes(row, layer),
                    "first_impacted_t": to_iso(first_impacted),
                    "projections": projections,
                }
            )
        facts.sort(key=lambda f: f["feature_ref"])
        return facts

    def _build_egress(
        self,
        features: Mapping[str, gpd.GeoDataFrame],
        facts: list[dict],
        targets: list[RasterTarget],
    ) -> list[dict]:
        """Join sites to their routes through the registry and derive a route state."""
        by_ref = {f["feature_ref"]: f for f in facts}
        out = []
        for layer_id, layer in self.layers.items():
            if layer.egress is None:
                continue
            routes_layer = self.layers.get(layer.egress.routes_layer)
            sites = features.get(layer_id)
            routes = features.get(layer.egress.routes_layer)
            if sites is None or sites.empty:
                continue
            for _, site in sites.iterrows():
                site_id = site[layer.id_field]
                site_ref = f"{layer_id}:{site_id}"
                route_refs: list[str] = []
                if routes is not None and routes_layer is not None:
                    join_field = layer.egress.join_field
                    if join_field in routes.columns:
                        matched = routes[routes[join_field].astype(str) == str(site_id)]
                        route_refs = [
                            f"{routes_layer.layer_id}:{r[routes_layer.id_field]}"
                            for _, r in matched.iterrows()
                        ]
                if not route_refs:
                    # No configured route: the relationship cannot establish a state.
                    out.append(
                        {
                            "site_ref": site_ref,
                            "route_refs": [],
                            "status": "unknown",
                            "first_blocked_t": None,
                        }
                    )
                    continue
                blocked_times = [
                    by_ref[r]["first_impacted_t"] for r in route_refs if r in by_ref
                ]
                # A site is only out when every one of its configured routes is impassable.
                all_blocked = len(blocked_times) == len(route_refs)
                out.append(
                    {
                        "site_ref": site_ref,
                        "route_refs": sorted(set(route_refs)),
                        "status": "blocked" if all_blocked else "open",
                        "first_blocked_t": max(blocked_times) if all_blocked else None,
                    }
                )
        out.sort(key=lambda e: e["site_ref"])
        return out


def _read_reaches(path: Path | None) -> list[dict]:
    """Copy only the five Contract 2 reach columns from the Contract 1 sidecar."""
    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        raise ImpactExtractionError(f"Required Contract 1 reach sidecar is missing: {path}")
    import pandas as pd

    df = pd.read_parquet(path)
    needed = ["reach_ref", "stage_mid_m", "rate_of_rise_m_per_h", "velocity_ms", "source"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ImpactExtractionError(f"{path} is missing reach column(s) {missing}")
    rows = []
    for _, r in df[needed].iterrows():
        rows.append(
            {
                "reach_ref": str(r["reach_ref"]),
                "stage_mid_m": round(max(float(r["stage_mid_m"]), 0.0), 4),
                "rate_of_rise_m_per_h": round(float(r["rate_of_rise_m_per_h"]), 4),
                "velocity_ms": round(max(float(r["velocity_ms"]), 0.0), 4),
                "source": str(r["source"]),
            }
        )
    return rows


def impact_path(run_dir: Path, p: datetime | None, t: datetime) -> Path:
    """Canonical Contract 2 location, with the hindsight analogue when `p` is null."""
    base = Path(run_dir) / "impacts"
    if p is None:
        return base / "hindsight" / f"t={to_compact(t)}" / "impact.json"
    return base / f"p={to_compact(p)}" / f"t={to_compact(t)}" / "impact.json"


def write_impact_json(path: Path, payload: dict) -> Path:
    """Validate, then write through a temporary file in the same directory and rename."""
    validate_json("impact-json", payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)
    return path
