"""Unit tests for HAND ingest: download, URL builders, clipping, and intersections."""
from __future__ import annotations

from pathlib import Path
import json
import httpx
import numpy as np
import pandas as pd
import pytest
import rasterio
import rasterio.transform
from flood.contracts.models import Scenario
from flood.ingest.hand import (
    HAND_BASE_URL,
    branch_intersects,
    clip_branch,
    download,
    get_branch_catch_url,
    get_branch_file_url,
    get_branch_rem_url,
    get_huc_base_url,
    get_huc_file_url,
    prep_hand,
)
from flood.interfaces import Grid


def test_url_builders() -> None:
    fim = "4.9.9.0"
    huc = "12345678"
    base = get_huc_base_url(fim, huc)
    assert base == f"{HAND_BASE_URL}/hand_fim_4_9_9_0/12345678"

    huc_file = get_huc_file_url(fim, huc, "branch_ids.csv")
    assert huc_file == f"{base}/branch_ids.csv"

    branch_file = get_branch_file_url(fim, huc, 100, "custom.tif")
    assert branch_file == f"{base}/branches/100/custom.tif"

    rem_url = get_branch_rem_url(fim, huc, 100)
    assert rem_url == f"{base}/branches/100/rem_zeroed_masked_100.tif"

    catch_url = get_branch_catch_url(fim, huc, 100)
    assert catch_url == f"{base}/branches/100/gw_catchments_reaches_filtered_addedAttributes_100.tif"


def test_download_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"sample-file-content-12345"
    content_len = len(content)

    get_count = 0
    head_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count, head_count
        if request.method == "HEAD":
            head_count += 1
            return httpx.Response(200, headers={"Content-Length": str(content_len)})
        elif request.method == "GET":
            get_count += 1
            return httpx.Response(200, content=content)
        return httpx.Response(405)

    transport = httpx.MockTransport(mock_handler)
    orig_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    dest = tmp_path / "test_file.bin"

    # 1. First download: file does not exist, should perform GET
    download("https://example.com/file.bin", dest)
    assert dest.exists()
    assert dest.read_bytes() == content
    assert get_count == 1

    # 2. Second download: file exists and size matches Content-Length from HEAD, should skip GET
    download("https://example.com/file.bin", dest)
    assert get_count == 1
    assert head_count >= 1

    # 3. Third download with force=True: should perform GET again
    download("https://example.com/file.bin", dest, force=True)
    assert get_count == 2


def test_branch_intersects() -> None:
    grid_bounds = (100.0, 100.0, 200.0, 200.0)

    # Completely inside
    assert branch_intersects((120.0, 120.0, 180.0, 180.0), grid_bounds) is True

    # Partially overlapping
    assert branch_intersects((50.0, 50.0, 150.0, 150.0), grid_bounds) is True

    # Completely enclosing
    assert branch_intersects((50.0, 50.0, 250.0, 250.0), grid_bounds) is True

    # Disjoint to the left
    assert branch_intersects((10.0, 100.0, 90.0, 200.0), grid_bounds) is False

    # Disjoint above
    assert branch_intersects((100.0, 210.0, 200.0, 300.0), grid_bounds) is False

    # Touching boundary only (zero-area)
    assert branch_intersects((0.0, 100.0, 100.0, 200.0), grid_bounds) is False


def test_clip_branch_tiny_geotiffs(tmp_path: Path) -> None:
    # 6 by 4 grid at resolution 10.0
    # Width = 6 (60m), Height = 4 (40m)
    grid_bounds = (100.0, 200.0, 160.0, 240.0)
    grid = Grid.from_bounds(grid_bounds, resolution_m=10.0, crs="EPSG:5070")
    assert grid.width == 6
    assert grid.height == 4

    # Tiny raster: 3 by 3 at resolution 10.0
    # Extent: x in [120, 150], y in [210, 240]
    # This overlaps columns 2, 3, 4 and rows 0, 1, 2 of the grid.
    raster_transform = rasterio.transform.from_origin(120.0, 240.0, 10.0, 10.0)

    # REM data (int16 mm): 3x3
    rem_data = np.array(
        [
            [1000, 2000, 32767],  # row 0 (32767 is nodata)
            [3000, 4000, 5000],   # row 1
            [6000, 7000, 8000],   # row 2
        ],
        dtype=np.int16,
    )

    # Catchment data (int32 HydroID): 3x3
    catch_data = np.array(
        [
            [10, 20, 0],         # row 0 (0 is nodata)
            [30, 40, 50],        # row 1
            [60, 70, 80],        # row 2
        ],
        dtype=np.int32,
    )

    rem_path = tmp_path / "rem.tif"
    catch_path = tmp_path / "catch.tif"

    profile_rem = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": "int16",
        "crs": "EPSG:5070",
        "transform": raster_transform,
        "nodata": 32767,
    }
    with rasterio.open(rem_path, "w", **profile_rem) as dst:
        dst.write(rem_data, 1)

    profile_catch = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": "int32",
        "crs": "EPSG:5070",
        "transform": raster_transform,
        "nodata": 0,
    }
    with rasterio.open(catch_path, "w", **profile_catch) as dst:
        dst.write(catch_data, 1)

    rem_f32, catch_hydroid = clip_branch(rem_path, catch_path, grid)

    assert rem_f32.shape == (4, 6)
    assert catch_hydroid.shape == (4, 6)

    # Expected REM (in metres):
    # Rows 0..2, cols 2..4 should have values; elsewhere NaN
    expected_rem = np.full((4, 6), np.nan, dtype=np.float32)
    expected_rem[0, 2] = 1.0
    expected_rem[0, 3] = 2.0
    expected_rem[0, 4] = np.nan  # from 32767 nodata
    expected_rem[1, 2] = 3.0
    expected_rem[1, 3] = 4.0
    expected_rem[1, 4] = 5.0
    expected_rem[2, 2] = 6.0
    expected_rem[2, 3] = 7.0
    expected_rem[2, 4] = 8.0

    np.testing.assert_allclose(rem_f32, expected_rem, equal_nan=True)

    # Expected Catchment (HydroIDs):
    # Rows 0..2, cols 2..4 should have HydroIDs; elsewhere -1
    expected_catch = np.full((4, 6), -1, dtype=np.int32)
    expected_catch[0, 2] = 10
    expected_catch[0, 3] = 20
    expected_catch[0, 4] = -1  # from 0 nodata
    expected_catch[1, 2] = 30
    expected_catch[1, 3] = 40
    expected_catch[1, 4] = 50
    expected_catch[2, 2] = 60
    expected_catch[2, 3] = 70
    expected_catch[2, 4] = 80

    np.testing.assert_array_equal(catch_hydroid, expected_catch)


@pytest.mark.network
def test_kerr_smoke(repo_root: Path, kerr_scenario: Scenario) -> None:
    data_dir = repo_root / "data"
    cube = prep_hand(kerr_scenario, data_dir=data_dir)

    cube_dir = data_dir / "cube" / kerr_scenario.scenario_id
    assert cube_dir.exists()

    meta_file = cube_dir / "meta.json"
    assert meta_file.exists()
    meta = json.loads(meta_file.read_text(encoding="utf-8"))

    expected_grid = Grid.from_bounds(tuple(kerr_scenario.hydrology.aoi.bounds))
    grid_meta = meta["grid"]
    actual_grid = Grid(
        crs=grid_meta["crs"],
        resolution_m=grid_meta["resolution_m"],
        width=grid_meta["width"],
        height=grid_meta["height"],
        transform=tuple(grid_meta["transform"]),
        bounds=tuple(grid_meta["bounds"]),
    )
    assert actual_grid == expected_grid

    # Assert at least branches 0 and 1619000006 are present
    assert 0 in meta["branches"]
    assert 1619000006 in meta["branches"]

    # Assert network contains feature 3586192 with gauge_site == "08165500"
    net_df = pd.read_parquet(cube_dir / "network.parquet")
    f_matches = net_df[net_df["feature_id"] == 3586192]
    assert not f_matches.empty
    assert f_matches.iloc[0]["gauge_site"] == "08165500"
