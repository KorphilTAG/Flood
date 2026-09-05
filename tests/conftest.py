"""Pytest shared fixtures."""
from __future__ import annotations

from pathlib import Path
import pytest
from flood.contracts.models import Scenario
from flood.engine.cube import HandCube
from flood.scenario import load_scenario
from tests.fixtures.mini_huc.build import build


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def mini_huc_dir(repo_root: Path) -> Path:
    out_dir = repo_root / "tests" / "fixtures" / "mini_huc" / "out"
    return build(out_dir)


@pytest.fixture(scope="session")
def mini_data_dir(mini_huc_dir: Path) -> Path:
    """A data_dir in the production layout: cube/<id>, usgs/<id>, nwm/<id>."""
    return mini_huc_dir / "data"


@pytest.fixture
def mini_cube(mini_data_dir: Path) -> HandCube:
    return HandCube.load(mini_data_dir / "cube" / "mini-huc")


@pytest.fixture
def mini_scenario(mini_huc_dir: Path) -> Scenario:
    return load_scenario(mini_huc_dir / "scenario.json")


@pytest.fixture
def kerr_scenario(repo_root: Path) -> Scenario:
    return load_scenario(repo_root / "scenarios" / "kerr-2025-07-04.json")
