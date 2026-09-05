from pathlib import Path
"""Tests for COG and PNG raster product writers."""
from datetime import datetime, timezone
import io
import numpy as np
from PIL import Image
import pytest
import rasterio
from rio_cogeo.cogeo import cog_validate

from flood.engine.cube import HandCube
from flood.interfaces import Grid, NODATA, RASTER_BANDS, StateArrays
from flood.products.raster import (
    DEPTH_RAMP,
    render_overlay_png,
    write_depth_cog,
    write_tte_cog,
)


def _sample_state_arrays(h: int = 20, w: int = 40) -> StateArrays:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    d_mid = np.full((h, w), 1.0, dtype=np.float32)
    d_low = np.full((h, w), 0.5, dtype=np.float32)
    d_high = np.full((h, w), 2.0, dtype=np.float32)
    v_mid = np.full((h, w), 1.2, dtype=np.float32)
    h_dv = d_mid * v_mid
    prob = np.full((h, w), 0.8, dtype=np.float32)

    # Some nodata/NaN values
    d_mid[0, 0] = np.nan
    d_low[0, 0] = np.nan
    d_high[0, 0] = np.nan
    v_mid[0, 0] = np.nan
    h_dv[0, 0] = np.nan
    prob[0, 0] = np.nan

    return StateArrays(
        p=now,
        t=now,
        depth_mid=d_mid,
        depth_low=d_low,
        depth_high=d_high,
        velocity_ms=v_mid,
        hazard_dv=h_dv,
        prob_inundated=prob,
        compute_ms={},
    )


def test_write_depth_cog(tmp_path: Path, mini_cube: HandCube):
    grid = mini_cube.grid
    arrays = _sample_state_arrays(grid.height, grid.width)
    out_tif = tmp_path / "depth.tif"

    write_depth_cog(out_tif, grid, arrays)
    assert out_tif.exists()

    # Valid COG
    is_valid, errors, warnings = cog_validate(out_tif)
    assert is_valid, f"COG validation failed: {errors}"

    with rasterio.open(out_tif) as src:
        assert src.count == 6
        assert src.descriptions == tuple(RASTER_BANDS)
        assert src.tags(1)["units"] == "m"
        assert src.tags(2)["units"] == "m"
        assert src.tags(3)["units"] == "m"
        assert src.tags(4)["units"] == "m/s"
        assert src.tags(5)["units"] == "m2/s"
        assert src.tags(6)["units"] == "fraction"
        assert tuple(src.transform)[:6] == grid.transform

        # Data reproduction
        d_mid_read = src.read(1)
        d_mid_expected = np.where(np.isnan(arrays.depth_mid), NODATA, arrays.depth_mid)
        np.testing.assert_allclose(d_mid_read, d_mid_expected)
        assert d_mid_read[0, 0] == NODATA


def test_write_tte_cog(tmp_path: Path, mini_cube: HandCube):
    grid = mini_cube.grid
    tte = np.full((3, grid.height, grid.width), 15.0, dtype=np.float32)
    tte[:, 0, 0] = np.nan
    tte[0, 1, 1] = 0.0
    tte[2, 2, 2] = -1.0

    out_tif = tmp_path / "time_to_exceedance.tif"
    write_tte_cog(out_tif, grid, tte)
    assert out_tif.exists()

    is_valid, errors, warnings = cog_validate(out_tif)
    assert is_valid, f"COG validation failed: {errors}"

    with rasterio.open(out_tif) as src:
        assert src.count == 3
        assert src.descriptions == ("tte_015", "tte_030", "tte_060")
        assert src.tags(1)["units"] == "min"
        assert src.tags(2)["units"] == "min"
        assert src.tags(3)["units"] == "min"
        assert tuple(src.transform)[:6] == grid.transform

        band1 = src.read(1)
        expected_b1 = np.where(np.isnan(tte[0]), NODATA, tte[0])
        np.testing.assert_allclose(band1, expected_b1)


def test_render_overlay_png(mini_cube: HandCube):
    grid = mini_cube.grid
    depth = np.full((grid.height, grid.width), 1.5, dtype=np.float32)
    png_bytes, bounds = render_overlay_png(depth, grid, max_px=512)

    assert isinstance(png_bytes, bytes)
    assert len(bounds) == 4
    xmin, ymin, xmax, ymax = bounds
    assert xmin < xmax and ymin < ymax

    # Decodes with Pillow
    img = Image.open(io.BytesIO(png_bytes))
    assert img.mode == "RGBA"
    w, h = img.size
    assert max(w, h) == 512

    # Pixels in domain should be non-transparent (alpha > 0)
    arr = np.array(img)
    assert np.any(arr[:, :, 3] > 0)


def test_render_overlay_png_dry_array(mini_cube: HandCube):
    grid = mini_cube.grid
    dry_depth = np.zeros((grid.height, grid.width), dtype=np.float32)
    png_bytes, bounds = render_overlay_png(dry_depth, grid, max_px=256)

    img = Image.open(io.BytesIO(png_bytes))
    arr = np.array(img)
    # Dry-only array yields fully transparent pixels
    assert np.all(arr[:, :, 3] == 0)


def test_cli_map(tmp_path: Path, mini_data_dir: Path):
    from flood.cli import main

    cube_dir = mini_data_dir / "cube" / "mini-huc"
    q_csv = tmp_path / "q.csv"
    q_csv.write_text("feature_id,q_mid_cms\n101,5.0\n102,5.0\n103,20.0\n104,20.0\n105,20.0\n106,20.0\n")
    out_tif = tmp_path / "out.tif"

    code = main(["map", "--cube", str(cube_dir), "--q", str(q_csv), "--out", str(out_tif)])
    assert code == 0
    assert out_tif.exists()
    assert cog_validate(out_tif)[0]

    with rasterio.open(out_tif) as src:
        assert src.count == 6
        d_mid = src.read(1)
        d_low = src.read(2)
        d_high = src.read(3)
        # with only q_mid_cms present, low and high equal mid
        np.testing.assert_allclose(d_low, d_mid)
        np.testing.assert_allclose(d_high, d_mid)
