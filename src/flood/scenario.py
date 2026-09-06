"""Scenario loader and validator."""
from __future__ import annotations

import json
from pathlib import Path
from flood.contracts.models import Scenario
from flood.contracts.validate import ContractError, validate_json

DEFAULT_RESOLUTION_M = 10.0


def load_scenario(path: Path | str, resolution_m: float = DEFAULT_RESOLUTION_M) -> Scenario:
    """Load, validate against JSON Schema, parse Pydantic model, and check AOI alignment."""
    p = Path(path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_json("scenario", data)
    scenario = Scenario.model_validate(data)

    # Check AOI bounds alignment with grid resolution
    bounds = scenario.hydrology.aoi.bounds
    for coord in bounds:
        if abs(round(coord / resolution_m) * resolution_m - coord) > 1e-6:
            raise ContractError(
                f"AOI coordinate {coord} is not a multiple of resolution_m={resolution_m}",
                path=["hydrology", "aoi", "bounds"],
            )

    scenario.path = p
    scenario.base_dir = p.parent
    return scenario
