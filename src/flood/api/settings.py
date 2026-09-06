"""Application settings."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass
class Settings:
    runs_dir: Path = field(default_factory=lambda: Path(os.environ.get("FLOOD_RUNS_DIR", "runs")))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FLOOD_DATA_DIR", "data")))
    scenarios_dir: Path = field(default_factory=lambda: Path(os.environ.get("FLOOD_SCENARIOS_DIR", "scenarios")))
    # Frozen Addendum 1 model output: static per-footprint vulnerability weights, unchanged
    # per tick. Not part of a run's own products -- same file for every run of the scenario.
    demographic_risk_geojson: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FLOOD_DEMOGRAPHIC_RISK_GEOJSON", "project/output/demographic_risk.geojson")
        )
    )
    # Browser origins allowed to call the API (map front ends run on another port).
    # Comma-separated in FLOOD_CORS_ORIGINS; "*" allows any origin without credentials.
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.environ.get("FLOOD_CORS_ORIGINS", "*").split(",") if o.strip()]
    )

    def __post_init__(self) -> None:
        if isinstance(self.runs_dir, str):
            self.runs_dir = Path(self.runs_dir)
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)
        if isinstance(self.scenarios_dir, str):
            self.scenarios_dir = Path(self.scenarios_dir)
        if isinstance(self.demographic_risk_geojson, str):
            self.demographic_risk_geojson = Path(self.demographic_risk_geojson)
