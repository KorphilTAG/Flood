"""Acceptance tests for scenario loading, path resolution, and CLI validation."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from flood.cli import main
from flood.contracts.validate import ContractError
from flood.scenario import load_scenario


def test_load_kerr_scenario(kerr_scenario) -> None:
    assert kerr_scenario.scenario_id == "kerr-2025-07-04"
    assert kerr_scenario.path is not None
    assert kerr_scenario.base_dir is not None

    sources = kerr_scenario.exposure_layer_sources()
    assert len(sources) == len(kerr_scenario.exposure_layers)
    for src_path in sources:
        assert isinstance(src_path, Path)
        assert src_path.is_absolute()


def test_aoi_bounds_alignment_check(tmp_path: Path, repo_root: Path) -> None:
    orig = repo_root / "scenarios" / "kerr-2025-07-04.json"
    data = json.loads(orig.read_text(encoding="utf-8"))

    # Modify one bound so it is not a multiple of 10.0
    data["hydrology"]["aoi"]["bounds"][0] = -316005.0
    bad_file = tmp_path / "bad_bounds.json"
    bad_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ContractError) as exc:
        load_scenario(bad_file, resolution_m=10.0)
    assert "multiple of resolution_m" in str(exc.value)
    assert exc.value.path == ["hydrology", "aoi", "bounds"]


def test_cli_scenario_validate_ok(capsys, repo_root: Path) -> None:
    kerr_path = str(repo_root / "scenarios" / "kerr-2025-07-04.json")
    code = main(["scenario", "validate", kerr_path])
    assert code == 0
    captured = capsys.readouterr()
    assert "OK kerr-2025-07-04" in captured.out


def test_cli_scenario_validate_invalid_crs(capsys, tmp_path: Path, repo_root: Path) -> None:
    orig = repo_root / "scenarios" / "kerr-2025-07-04.json"
    data = json.loads(orig.read_text(encoding="utf-8"))
    data["hydrology"]["aoi"]["crs"] = "EPSG:4326"

    bad_file = tmp_path / "bad_crs.json"
    bad_file.write_text(json.dumps(data), encoding="utf-8")

    code = main(["scenario", "validate", str(bad_file)])
    assert code == 2
    captured = capsys.readouterr()
    out = captured.out + captured.err
    # Verify the schema error path is printed
    assert "crs" in out
    assert "aoi" in out
