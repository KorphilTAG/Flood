"""Contract 2 impact facts as critic grounding context.

The critic is allowed to read the impact JSON the extractor writes -- never a
raster, never a coordinate (PRD 6.5, 6.6). This module parses that document into
the two things the critic needs from it: the set of feature IDs a response is
allowed to cite, and a compact plain-text rendering for the prompt.

Nothing here fetches, resolves, or invents a feature ID. Every ID returned was
present in the caller-supplied document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

# The shared feature-reference grammar (contracts common.schema.json#/$defs/feature_ref).
# Applied here as a guard: an ID that does not match never enters the valid-citation set.
FEATURE_REF = re.compile(r"^[a-z][a-z0-9_]{0,31}:[A-Za-z0-9_.-]{1,64}$")

# Contract 2 forbids these anywhere in the document. The critic re-checks rather than
# trusting its producer, because this is the last point before text reaches an LLM.
_BANNED_KEYS = {"geometry", "coordinates", "lon", "lat"}


class ImpactFactsError(ValueError):
    """The supplied impact document is not usable Contract 2 grounding."""


def _assert_no_coordinates(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _BANNED_KEYS:
                raise ImpactFactsError(
                    f"impact document carries a forbidden {key!r} field at {path}; "
                    "Contract 2 output must contain no geometry or coordinates"
                )
            _assert_no_coordinates(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _assert_no_coordinates(value, f"{path}[{i}]")


class ImpactFacts:
    """A parsed Contract 2 document, reduced to what the critic may use."""

    def __init__(self, document: dict) -> None:
        if not isinstance(document, dict):
            raise ImpactFactsError("impact document must be a JSON object")
        _assert_no_coordinates(document)
        self.document = document
        self.run_id = document.get("run_id")
        self.p = document.get("p")
        self.t = document.get("t")
        self.facts = list(document.get("facts") or [])
        self.egress = list(document.get("egress") or [])
        self.reaches = list(document.get("reaches") or [])

    @classmethod
    def from_path(cls, path: str | Path) -> "ImpactFacts":
        p = Path(path)
        if not p.exists():
            raise ImpactFactsError(f"impact document not found: {p}")
        try:
            return cls(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as err:
            raise ImpactFactsError(f"impact document is not valid JSON: {err}") from err

    def feature_ids(self) -> set[str]:
        """Every citable feature reference this document actually contains."""
        ids: set[str] = set()
        for fact in self.facts:
            ids.add(fact.get("feature_ref"))
        for entry in self.egress:
            ids.add(entry.get("site_ref"))
            ids.update(entry.get("route_refs") or [])
        for reach in self.reaches:
            ids.add(reach.get("reach_ref"))
        return {i for i in ids if isinstance(i, str) and FEATURE_REF.fullmatch(i)}

    def render(self) -> str:
        """A compact, citable plain-text view for the prompt.

        Every line leads with the feature reference so the model can cite it verbatim,
        and carries only Contract 2 scalars.
        """
        lines: list[str] = []
        header = f"Current flood facts (run {self.run_id}, knowledge cutoff p={self.p}, target t={self.t}):"
        lines.append(header)

        if not (self.facts or self.egress or self.reaches):
            lines.append("  (no impacted features at this target time)")
            return "\n".join(lines)

        for fact in self.facts:
            ref = fact.get("feature_ref")
            if not ref:
                continue
            state = "impacted now" if fact.get("impacted_now") else "not yet impacted"
            first = fact.get("first_impacted_t")
            bits = [
                f"[{ref}] {fact.get('kind')}, {state}",
                f"depth_max={fact.get('depth_max_m')} m",
                f"hazard_dv_max={fact.get('hazard_dv_max_m2_per_s')} m2/s",
            ]
            if first:
                bits.append(f"first impacted {first}")
            projections = fact.get("projections") or []
            if projections:
                shown = ", ".join(
                    f"{p.get('t')}={'impacted' if p.get('impacted') else 'clear'}" for p in projections
                )
                bits.append(f"projections: {shown}")
            attributes = fact.get("attributes") or {}
            if attributes:
                bits.append(
                    "attributes: " + ", ".join(f"{k}={v}" for k, v in sorted(attributes.items()))
                )
            lines.append("  " + "; ".join(bits))

        for entry in self.egress:
            site = entry.get("site_ref")
            if not site:
                continue
            # Bracketed, because a route reference is citable and the prompt tells the
            # model to cite bracketed IDs; printing it bare would hide a valid citation.
            refs = entry.get("route_refs") or []
            routes = ", ".join(f"[{r}]" for r in refs) if refs else "no configured route"
            blocked = entry.get("first_blocked_t")
            line = f"  [{site}] egress {entry.get('status')} via {routes}"
            if blocked:
                line += f"; first blocked {blocked}"
            lines.append(line)

        for reach in self.reaches:
            ref = reach.get("reach_ref")
            if not ref:
                continue
            lines.append(
                f"  [{ref}] stage={reach.get('stage_mid_m')} m; "
                f"rate_of_rise={reach.get('rate_of_rise_m_per_h')} m/h; "
                f"velocity={reach.get('velocity_ms')} m/s (proxy); "
                f"source={reach.get('source')}"
            )
        return "\n".join(lines)
