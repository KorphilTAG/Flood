"""Hazard-fused vulnerability heatmap (PRD Addendum 2).

Combines the frozen demographic-risk output (Addendum 1's ``output/demographic_risk.geojson``,
one static ``weight`` per OSM building footprint) with the impact extractor's live per-timestep
depth facts (Contract 2), multiplicatively, at render time. Nothing here retrains or extends
either input: the model stays frozen, the impact extractor stays untouched, and this module only
does the downstream arithmetic join described in the addendum's Section 3.

``feature_id`` alignment (Section 4): the demographic model's GeoJSON keys each footprint as
``building:osm:<osm_ref>``. The FEMA ingestion loader spatially matches that already-frozen OSM
centroid to a FEMA footprint once, persists the source-derived OSM-compatible alias, and the
structure view exposes it as ``structure:<osm_id>``. This module remains a deterministic
string-key join; it never runs a spatial join or consults raw geometry at render time.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"
SCORE_SOURCE = "vulnerability_x_hazard_v1"
#: Fallback when the exposure layer providing hazard_severity has no configured threshold.
DEFAULT_DEPTH_THRESHOLD_M = 0.3

_LEADING_LAYER_PREFIX = re.compile(r"^[a-z_]+:")


class ExposureFusionError(ValueError):
    """A vulnerability or impact input cannot be fused."""


def demographic_feature_id_to_feature_ref(feature_id: str, layer_id: str = "structure") -> str:
    """Map a demographic-model ``building:osm:<ref>`` feature_id to a Contract 2 feature_ref.

    Mirrors ``ingestion/db/exposure_views.sql``'s ``kerr_2025_07_04_structure`` view exactly:
    strip the leading ``<word>:`` prefix, then fold ``:`` and ``/`` to ``.``.
    """
    if not feature_id:
        raise ExposureFusionError("feature_id is required")
    stripped = _LEADING_LAYER_PREFIX.sub("", feature_id, count=1)
    source_id = stripped.replace(":", ".").replace("/", ".")
    if not source_id:
        raise ExposureFusionError(f"feature_id {feature_id!r} has no source id after its layer prefix")
    return f"{layer_id}:{source_id}"


def load_vulnerability_geojson(path: str | Path) -> dict[str, Any]:
    """Read the frozen static vulnerability layer as-is (for direct passthrough to the frontend)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def weights_from_geojson(geojson: Mapping[str, Any], layer_id: str = "structure") -> dict[str, dict[str, Any]]:
    """Index the static layer's footprints by their impact-extractor feature_ref.

    A footprint with ``weight: null`` (Addendum 1's ``insufficient_data`` abstention) is skipped
    entirely rather than treated as zero -- Addendum 1 Section 4.3 is explicit that an abstained
    footprint must never be rendered as a confident "no risk".
    """
    out: dict[str, dict[str, Any]] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        feature_id = props.get("feature_id")
        weight = props.get("weight")
        if not feature_id or weight is None:
            continue
        ref = demographic_feature_id_to_feature_ref(feature_id, layer_id=layer_id)
        out[ref] = {
            "weight": float(weight),
            "citation_ids": list(props.get("citation_ids") or []),
        }
    return out


def load_vulnerability_weights(path: str | Path, layer_id: str = "structure") -> dict[str, dict[str, Any]]:
    """Convenience: read the frozen GeoJSON and index it in one call."""
    return weights_from_geojson(load_vulnerability_geojson(path), layer_id=layer_id)


def depth_threshold_for(scenario: Any, layer_id: str = "structure", default: float = DEFAULT_DEPTH_THRESHOLD_M) -> float:
    """The registry's own damage threshold for ``layer_id``, so normalization tracks the scenario."""
    for layer in getattr(scenario, "exposure_layers", []):
        if layer.layer_id != layer_id:
            continue
        impact = layer.impact
        if impact is None:
            break
        threshold = impact.threatened_depth_m if layer.geometry == "polygon" else impact.impassable_depth_m
        if threshold is not None and threshold > 0:
            return float(threshold)
        break
    return float(default)


def normalize_depth(depth_m: float, threshold_m: float) -> float:
    """Depth as a 0-1 hazard severity, clamped, against a structure-damage threshold."""
    if threshold_m <= 0:
        return 0.0
    return max(0.0, min(1.0, float(depth_m) / threshold_m))


def compute_exposure_layer(
    impact_payload: Mapping[str, Any],
    vulnerability_weights: Mapping[str, Mapping[str, Any]],
    depth_threshold_m: float = DEFAULT_DEPTH_THRESHOLD_M,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fuse static vulnerability with this tick's hazard depth: one density_point per footprint.

    ``vulnerability_weight(f) x hazard_severity(f, t)`` (Section 3): multiplicative, so a
    vulnerable footprint that is currently dry scores zero rather than glowing regardless of
    hazard. A footprint absent from ``impact_payload["facts"]`` has no hazard reading at this
    ``t`` (the extractor omits dry features entirely) and is skipped rather than assigned a
    fabricated zero.
    """
    t = impact_payload.get("t")
    if not t:
        raise ExposureFusionError("impact_payload has no 't'")
    facts_by_ref = {f["feature_ref"]: f for f in impact_payload.get("facts", [])}
    citation_suffix = f"impact_extractor:{run_id}:{t}" if run_id else f"impact_extractor:{t}"

    features: list[dict[str, Any]] = []
    for feature_ref, entry in vulnerability_weights.items():
        fact = facts_by_ref.get(feature_ref)
        if fact is None:
            continue
        vuln_weight = float(entry["weight"])
        hazard_severity = normalize_depth(fact["depth_max_m"], depth_threshold_m)
        fused = vuln_weight * hazard_severity
        citation_ids = [*entry.get("citation_ids", []), citation_suffix]
        features.append(
            {
                "type": "density_point",
                "feature_id": feature_ref,
                "weight": round(fused, 6),
                "score_source": SCORE_SOURCE,
                "static_vulnerability_weight": round(vuln_weight, 6),
                "hazard_severity_t": round(hazard_severity, 6),
                "citation_ids": citation_ids,
                "t": t,
            }
        )
    features.sort(key=lambda f: f["feature_id"])
    return features


def validate_exposure_layer(features: Sequence[Mapping[str, Any]], impact_payload: Mapping[str, Any]) -> None:
    """Output-validator extension (Section 8): reject anything the fused layer must never emit.

    Beyond the JSON-schema shape, a density_point is rejected if its feature_id did not come from
    the impact extractor's own facts (i.e. is not backed by a real PostGIS feature at this tick),
    or if its ``t`` does not match the impact document actually served -- the race condition where
    a client requests a tick the backend has not finished computing yet.
    """
    known_refs = {f["feature_ref"] for f in impact_payload.get("facts", [])}
    expected_t = impact_payload.get("t")
    for point in features:
        feature_id = point.get("feature_id")
        if feature_id not in known_refs:
            raise ExposureFusionError(
                f"density_point feature_id {feature_id!r} is not among this tick's impact facts"
            )
        if not point.get("citation_ids"):
            raise ExposureFusionError(f"density_point {feature_id!r} has no citation_ids")
        if point.get("t") != expected_t:
            raise ExposureFusionError(
                f"density_point {feature_id!r} has t={point.get('t')!r}, but the impact "
                f"document served is t={expected_t!r}"
            )
