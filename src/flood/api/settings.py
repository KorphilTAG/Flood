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
