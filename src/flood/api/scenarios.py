"""Scenarios API router."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from flood.api.errors import APIError
from flood.scenario import load_scenario

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios(request: Request) -> list[dict[str, str]]:
    """List scenario IDs and names for every valid scenario in scenarios_dir."""
    scenarios_dir: Path = request.app.state.settings.scenarios_dir
    results: list[dict[str, str]] = []

    if not scenarios_dir.is_dir():
        logger.warning("Scenarios directory does not exist: %s", scenarios_dir)
        return results

    for file_path in sorted(scenarios_dir.glob("*.json")):
        try:
            scenario = load_scenario(file_path)
            results.append({"scenario_id": scenario.scenario_id, "name": scenario.name})
        except Exception as exc:
            logger.warning("Skipping invalid scenario file %s: %s", file_path, exc)

    return results


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str, request: Request) -> JSONResponse:
    """Return scenario JSON file if valid and found, else 404 unknown_scenario."""
    scenarios_dir: Path = request.app.state.settings.scenarios_dir
    if not scenarios_dir.is_dir():
        raise APIError(status_code=404, code="unknown_scenario", message=f"Scenario '{scenario_id}' not found")

    target_file = scenarios_dir / f"{scenario_id}.json"
    if not target_file.is_file():
        # Fallback: scan for matching scenario_id inside files
        found_file: Path | None = None
        for file_path in scenarios_dir.glob("*.json"):
            try:
                sc = load_scenario(file_path)
                if sc.scenario_id == scenario_id:
                    found_file = file_path
                    break
            except Exception:
                continue
        if found_file is not None:
            target_file = found_file
        else:
            raise APIError(status_code=404, code="unknown_scenario", message=f"Scenario '{scenario_id}' not found")

    try:
        load_scenario(target_file)
        data = json.loads(target_file.read_text(encoding="utf-8"))
        return JSONResponse(status_code=200, content=data)
    except Exception as exc:
        raise APIError(status_code=404, code="unknown_scenario", message=f"Scenario '{scenario_id}' invalid: {exc}")
