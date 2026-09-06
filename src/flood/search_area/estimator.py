"""Deterministic, topology-constrained missing-person search-area estimates.

This module deliberately consumes an already-resolved physics ``Run``.  It
does not open raster products or infer a velocity vector: the scalar velocity
proxy comes from ``Run.state`` and the downstream direction comes solely from
the declared flowline topology and geometry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Literal

import geopandas as gpd
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import CRS
from shapely.geometry import LineString, Point, mapping
from shapely.ops import nearest_points, substring, unary_union
from shapely import wkb

from flood.interfaces import MIN_DEPTH_M, StateArrays
from flood.timegrid import parse_iso, to_iso


SCHEMA_VERSION = "1.0"
WEIGHT_LIMITATION = "relative search-priority weights are not calibrated probabilities"
VELOCITY_PROXY = "Physics Engine Manning/HAND velocity proxy; scalar velocity magnitude, not observed current direction"


class SearchAreaInputError(ValueError):
    """Invalid caller input that must be fixed rather than estimated around."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SearchAreaConfig:
    """Named deterministic controls for snapping, sampling, and uncertainty bands."""

    snap_distance_cells: float = 2.0
    topology_join_tolerance_cells: float = 2.0
    velocity_sample_step_cells: float = 1.0
    base_width_cells: float = 1.0
    downstream_widening_per_m: float = 0.05
    high_band_multiplier: float = 1.0
    medium_band_multiplier: float = 2.0
    low_band_multiplier: float = 3.0
    high_weight: float = 0.6
    medium_weight: float = 0.3
    low_weight: float = 0.1

    def validate(self) -> None:
        if self.snap_distance_cells <= 0 or self.topology_join_tolerance_cells <= 0:
            raise ValueError("snap and topology tolerances must be positive")
        if self.velocity_sample_step_cells <= 0 or self.base_width_cells < 1:
            raise ValueError("sampling must be positive and base width must be at least one cell")
        if self.downstream_widening_per_m < 0:
            raise ValueError("downstream widening must be non-negative")
        if min(self.high_band_multiplier, self.medium_band_multiplier, self.low_band_multiplier) <= 0:
            raise ValueError("band multipliers must be positive")
        if not (self.high_band_multiplier <= self.medium_band_multiplier <= self.low_band_multiplier):
            raise ValueError("band multipliers must be nested high <= medium <= low")
        if min(self.high_weight, self.medium_weight, self.low_weight) < 0:
            raise ValueError("relative weights must be non-negative")
        if self.high_weight + self.medium_weight + self.low_weight <= 0:
            raise ValueError("at least one relative weight must be positive")


DEFAULT_SEARCH_AREA_CONFIG = SearchAreaConfig()


class SearchAreaRequest(BaseModel):
    """Estimator input after a caller has resolved the run itself."""

    model_config = ConfigDict(extra="forbid")

    p: str | datetime | None
    t: str | datetime
    last_known_position_id: str = Field(min_length=1)


class SearchAreaFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class SearchAreaResult(BaseModel):
    """JSON-safe GeoJSON FeatureCollection plus search-specific provenance."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SearchAreaFeature]
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    status: Literal["available", "unavailable"]
    search_area_id: str
    requested: dict[str, str | None]
    canonical: dict[str, str | None]
    last_known_position: dict[str, str]
    source_refs: list[str]
    relative_weights: dict[str, float]
    configuration: dict[str, float]
    velocity_proxy: str
    limitations: list[str]
    truncated: bool
    reason: str | None = None

    @model_validator(mode="after")
    def _check_geometry_contract(self) -> "SearchAreaResult":
        if self.status == "unavailable":
            if self.features:
                raise ValueError("unavailable result must contain no geometry")
            return self
        if len(self.features) != 3:
            raise ValueError("available result must contain exactly three bands")
        expected = {"high", "medium", "low"}
        actual = {str(feature.properties.get("band")) for feature in self.features}
        if actual != expected:
            raise ValueError("available result bands must be high, medium, and low")
        for feature in self.features:
            if feature.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                raise ValueError("search-area geometry must be Polygon or MultiPolygon")
        total = sum(self.relative_weights.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("relative weights must normalize to one")
        return self


@dataclass(frozen=True)
class _Reach:
    feature_id: int
    to_feature_id: int
    geometry: LineString


def _json_time(value: str | datetime | None) -> str | None:
    if value is None:
        return "hindsight"
    if isinstance(value, datetime):
        return to_iso(value)
    return value


def _state_arrays(state_result: Any) -> StateArrays:
    """Accept the current Run tuple contract and a future direct-arrays contract."""
    arrays = state_result[0] if isinstance(state_result, tuple) else state_result
    if not isinstance(arrays, StateArrays):
        raise TypeError("Run.state did not return StateArrays")
    return arrays


def _sample_state(arrays: StateArrays, grid: Any, point: Point) -> tuple[float, float] | None:
    """Read the state cell containing a projected point without interpolation."""
    a, b, c, d, e, f = grid.transform
    determinant = a * e - b * d
    if determinant == 0:
        return None
    x_offset = point.x - c
    y_offset = point.y - f
    col_float = (e * x_offset - b * y_offset) / determinant
    row_float = (-d * x_offset + a * y_offset) / determinant
    col = int(math.floor(col_float))
    row = int(math.floor(row_float))
    if row < 0 or col < 0 or row >= grid.height or col >= grid.width:
        return None
    depth = float(arrays.depth_mid[row, col])
    velocity = float(arrays.velocity_ms[row, col])
    if not (np.isfinite(depth) and np.isfinite(velocity)):
        return None
    return depth, velocity


def _load_reaches(network: Any) -> dict[int, _Reach]:
    required = {"feature_id", "to_feature_id", "flowline_wkb"}
    if not required.issubset(network.columns):
        missing = ", ".join(sorted(required - set(network.columns)))
        raise SearchAreaInputError("network_columns_missing", f"network missing required columns: {missing}")
    reaches: dict[int, _Reach] = {}
    for _, row in network.iterrows():
        feature_id = int(row["feature_id"])
        if feature_id in reaches:
            raise SearchAreaInputError("ambiguous_feature_id", f"multiple network rows for feature {feature_id}")
        downstream_raw = row["to_feature_id"]
        downstream = 0 if downstream_raw is None or (isinstance(downstream_raw, float) and np.isnan(downstream_raw)) else int(downstream_raw)
        try:
            geometry = wkb.loads(bytes(row["flowline_wkb"]))
        except Exception as exc:  # malformed source topology cannot be guessed around
            raise SearchAreaInputError("invalid_flowline_wkb", f"could not load flowline for feature {feature_id}") from exc
        if not isinstance(geometry, LineString) or geometry.is_empty or len(geometry.coords) < 2:
            raise SearchAreaInputError("invalid_flowline_geometry", f"feature {feature_id} is not a usable LineString")
        reaches[feature_id] = _Reach(feature_id, downstream, geometry)
    return reaches


def _oriented(reach: _Reach, reaches: dict[int, _Reach], join_tolerance_m: float) -> LineString | None:
    """Return a reach ordered towards its declared downstream geometry, if provable."""
    if reach.to_feature_id <= 0 or reach.to_feature_id not in reaches:
        return None
    downstream = reaches[reach.to_feature_id].geometry
    coords = list(reach.geometry.coords)
    first_distance = Point(coords[0]).distance(downstream)
    last_distance = Point(coords[-1]).distance(downstream)
    tie_tolerance = max(1e-8, join_tolerance_m * 1e-6)
    if min(first_distance, last_distance) > join_tolerance_m or abs(first_distance - last_distance) <= tie_tolerance:
        return None
    return LineString(coords if last_distance < first_distance else list(reversed(coords)))


def _append_travelled(coords: list[tuple[float, float]], line: LineString, start: float, stop: float) -> None:
    if stop <= start:
        return
    piece = substring(line, start, stop)
    if isinstance(piece, Point):
        candidate = (piece.x, piece.y)
        if not coords or coords[-1] != candidate:
            coords.append(candidate)
        return
    for coordinate in piece.coords:
        candidate = (float(coordinate[0]), float(coordinate[1]))
        if not coords or coords[-1] != candidate:
            coords.append(candidate)


def _normalized_weights(config: SearchAreaConfig) -> dict[str, float]:
    raw = {"high": config.high_weight, "medium": config.medium_weight, "low": config.low_weight}
    total = sum(raw.values())
    return {band: value / total for band, value in raw.items()}


def _stable_id(run: Any, request: SearchAreaRequest, arrays: StateArrays, lkp_id: str, config: SearchAreaConfig) -> str:
    payload = {
        "run_id": str(run.run_id),
        "requested": {"p": _json_time(request.p), "t": _json_time(request.t)},
        "canonical": {"p": _json_time(arrays.p), "t": to_iso(arrays.t)},
        "last_known_position_id": lkp_id,
        "configuration": asdict(config),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return f"search-area-{digest}"


def _result(
    *,
    run: Any,
    request: SearchAreaRequest,
    arrays: StateArrays,
    lkp: Any,
    config: SearchAreaConfig,
    status: Literal["available", "unavailable"],
    source_refs: list[str],
    features: list[dict[str, Any]] | None = None,
    truncated: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    weights = _normalized_weights(config)
    result = SearchAreaResult.model_validate(
        {
            "type": "FeatureCollection",
            "features": features or [],
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "search_area_id": _stable_id(run, request, arrays, str(lkp.id), config),
            "requested": {"p": _json_time(request.p), "t": _json_time(request.t)},
            "canonical": {"p": _json_time(arrays.p), "t": to_iso(arrays.t)},
            "last_known_position": {"id": str(lkp.id), "t": str(lkp.t)},
            "source_refs": source_refs,
            "relative_weights": weights,
            "configuration": {key: float(value) for key, value in asdict(config).items()},
            "velocity_proxy": VELOCITY_PROXY,
            "limitations": [
                VELOCITY_PROXY,
                "Flow direction is constrained by declared flowline topology and geometry.",
                WEIGHT_LIMITATION,
            ],
            "truncated": truncated,
            "reason": reason,
        }
    )
    return result.model_dump(mode="json")


class SearchAreaEstimator:
    """Bounded deterministic search-area estimator for an already resolved Run."""

    def __init__(self, config: SearchAreaConfig = DEFAULT_SEARCH_AREA_CONFIG) -> None:
        config.validate()
        self.config = config

    def estimate(
        self,
        run: Any,
        p: str | datetime | None,
        t: str | datetime,
        last_known_position_id: str,
    ) -> dict[str, Any]:
        request = SearchAreaRequest(p=p, t=t, last_known_position_id=last_known_position_id)
        matches = [lkp for lkp in run.scenario.last_known_positions if lkp.id == request.last_known_position_id]
        if not matches:
            raise SearchAreaInputError("unknown_last_known_position_id", "last_known_position_id is not in this scenario")
        if len(matches) != 1:
            raise SearchAreaInputError("ambiguous_last_known_position_id", "last_known_position_id is not unique in this scenario")
        lkp = matches[0]

        # Exactly one direct, in-memory physics call.  No product URI or raster is used.
        arrays = _state_arrays(run.state(request.p, request.t, write=False))
        if arrays.t.tzinfo is None:
            raise SearchAreaInputError("canonical_time_invalid", "state target time must be timezone-aware")
        lkp_time = parse_iso(str(lkp.t))
        base_refs = [f"scenario_lkp:{lkp.id}"]
        if arrays.t < lkp_time:
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason="target_before_last_known_position")
        elapsed_seconds = (arrays.t - lkp_time).total_seconds()
        max_horizon_minutes = int(getattr(run, "manifest", {}).get("time", {}).get(
            "max_horizon_minutes", getattr(run, "max_horizon_minutes", 0)
        ))
        if elapsed_seconds > max_horizon_minutes * 60:
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason="last_known_position_horizon_exceeded")

        grid = run.cube.grid
        if not CRS.from_user_input(grid.crs).is_projected:
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason="grid_crs_not_projected")
        try:
            lkp_point = gpd.GeoSeries([Point(float(lkp.lon), float(lkp.lat))], crs="EPSG:4326").to_crs(grid.crs).iloc[0]
            reaches = _load_reaches(run.cube.network)
        except SearchAreaInputError as exc:
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason=exc.code)

        resolution = float(grid.resolution_m)
        snap_limit = self.config.snap_distance_cells * resolution
        join_tolerance = self.config.topology_join_tolerance_cells * resolution
        candidates: list[tuple[float, int, LineString, Point]] = []
        directed_nearby = False
        unresolved_nearby = False
        for reach in reaches.values():
            distance = lkp_point.distance(reach.geometry)
            if distance > snap_limit:
                continue
            oriented = _oriented(reach, reaches, join_tolerance)
            if oriented is None:
                unresolved_nearby = True
                continue
            directed_nearby = True
            snap_point = nearest_points(lkp_point, oriented)[1]
            sample = _sample_state(arrays, grid, snap_point)
            if sample is not None and sample[0] >= MIN_DEPTH_M and sample[1] > 0:
                candidates.append((distance, reach.feature_id, oriented, snap_point))
        if not candidates:
            reason = "direction_unproven_at_start" if unresolved_nearby and not directed_nearby else "dry_or_distant_start"
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason=reason)
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
        if len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1e-8):
            return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                           status="unavailable", source_refs=base_refs, reason="ambiguous_start_flowline")

        _, current_id, current_line, current_point = candidates[0]
        current_distance = current_line.project(current_point)
        remaining_seconds = elapsed_seconds
        sample_step = self.config.velocity_sample_step_cells * resolution
        travelled_coords: list[tuple[float, float]] = [(float(current_point.x), float(current_point.y))]
        traversed_ids: list[int] = [current_id]
        truncated = False
        reason: str | None = None
        seen_ids: set[int] = {current_id}

        while remaining_seconds > 1e-9:
            current_reach = reaches[current_id]
            current_point = current_line.interpolate(current_distance)
            state_sample = _sample_state(arrays, grid, current_point)
            if state_sample is None or state_sample[0] < MIN_DEPTH_M:
                truncated, reason = True, "dry_or_nodata_state"
                break
            if state_sample[1] <= 0:
                truncated, reason = True, "nonpositive_velocity"
                break
            to_boundary = max(0.0, current_line.length - current_distance)
            if to_boundary <= 1e-8:
                next_id = current_reach.to_feature_id
                if next_id <= 0:
                    truncated, reason = True, "topology_termination"
                    break
                next_reach = reaches.get(next_id)
                if next_reach is None:
                    truncated, reason = True, "missing_downstream_reach"
                    break
                next_line = _oriented(next_reach, reaches, join_tolerance)
                if next_line is None:
                    truncated, reason = True, "downstream_direction_unproven"
                    break
                if current_point.distance(Point(next_line.coords[0])) > join_tolerance:
                    truncated, reason = True, "topology_continuation_unproven"
                    break
                if next_id in seen_ids:
                    truncated, reason = True, "topology_cycle"
                    break
                current_id, current_line, current_distance = next_id, next_line, 0.0
                seen_ids.add(current_id)
                if current_id not in traversed_ids:
                    traversed_ids.append(current_id)
                continue

            advance_limit = min(sample_step, to_boundary)
            time_to_limit = advance_limit / state_sample[1]
            if remaining_seconds < time_to_limit:
                next_distance = current_distance + state_sample[1] * remaining_seconds
                _append_travelled(travelled_coords, current_line, current_distance, next_distance)
                current_distance = next_distance
                remaining_seconds = 0.0
                break
            _append_travelled(travelled_coords, current_line, current_distance, current_distance + advance_limit)
            current_distance += advance_limit
            remaining_seconds -= time_to_limit

        source_refs = base_refs + [f"reach:{feature_id}" for feature_id in traversed_ids]
        base_width = self.config.base_width_cells * resolution
        multipliers = {
            "high": self.config.high_band_multiplier,
            "medium": self.config.medium_band_multiplier,
            "low": self.config.low_band_multiplier,
        }
        cumulative = 0.0
        radii: list[tuple[Point, float]] = []
        previous: tuple[float, float] | None = None
        for coordinate in travelled_coords:
            if previous is not None:
                cumulative += Point(previous).distance(Point(coordinate))
            radii.append((Point(coordinate), cumulative))
            previous = coordinate
        weights = _normalized_weights(self.config)
        features: list[dict[str, Any]] = []
        for band in ("high", "medium", "low"):
            multiplier = multipliers[band]
            buffered = [
                point.buffer((base_width + self.config.downstream_widening_per_m * distance) * multiplier)
                for point, distance in radii
            ]
            geometry = unary_union(buffered).buffer(0)
            # Transform only finished vector geometry back to GeoJSON's WGS84 CRS.
            geometry_4326 = gpd.GeoSeries([geometry], crs=grid.crs).to_crs("EPSG:4326").iloc[0]
            geojson_geometry = json.loads(json.dumps(mapping(geometry_4326)))
            properties = {
                "band": band,
                "relative_weight": weights[band],
                "search_area_id": _stable_id(run, request, arrays, str(lkp.id), self.config),
                "source_refs": source_refs,
                "canonical_time": to_iso(arrays.t),
                "requested_time": _json_time(request.t),
                "velocity_proxy": VELOCITY_PROXY,
                "weight_limitation": WEIGHT_LIMITATION,
            }
            features.append({"type": "Feature", "geometry": geojson_geometry, "properties": properties})

        return _result(run=run, request=request, arrays=arrays, lkp=lkp, config=self.config,
                       status="available", source_refs=source_refs, features=features,
                       truncated=truncated, reason=reason)


def estimate_missing_person_search_area(
    run: Any,
    p: str | datetime | None,
    t: str | datetime,
    last_known_position_id: str,
    *,
    config: SearchAreaConfig = DEFAULT_SEARCH_AREA_CONFIG,
) -> dict[str, Any]:
    """Estimate three uncertain downstream polygon bands from one physics state."""
    return SearchAreaEstimator(config).estimate(run, p, t, last_known_position_id)


# Short alias for direct engine callers.
estimate_search_area = estimate_missing_person_search_area
