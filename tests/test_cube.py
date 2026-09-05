"""Acceptance tests for HandCube save and load round-trip."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
from flood.engine.cube import HandCube


def test_cube_save_load_round_trip(mini_cube: HandCube, tmp_path: Path) -> None:
    save_dir = tmp_path / "saved_cube"
    mini_cube.save(save_dir)

    loaded = HandCube.load(save_dir)

    # 1. Grid equality
    assert loaded.grid == mini_cube.grid

    # 2. Network & Gauges equality
    pd.testing.assert_frame_equal(loaded.network, mini_cube.network)
    pd.testing.assert_frame_equal(loaded.gauges, mini_cube.gauges)

    # 3. Branch count and IDs
    assert len(loaded.branches) == len(mini_cube.branches)
    for orig_b, load_b in zip(mini_cube.branches, loaded.branches):
        assert orig_b.branch_id == load_b.branch_id

        # Array equality (NaN-aware)
        np.testing.assert_allclose(load_b.rem, orig_b.rem, equal_nan=True)
        np.testing.assert_array_equal(load_b.catch, orig_b.catch)

        # Rating table arrays
        np.testing.assert_array_equal(load_b.rating.hydro_id, orig_b.rating.hydro_id)
        np.testing.assert_array_equal(load_b.rating.feature_id, orig_b.rating.feature_id)
        np.testing.assert_array_equal(load_b.rating.lake_id, orig_b.rating.lake_id)
        np.testing.assert_array_equal(load_b.rating.stream_order, orig_b.rating.stream_order)
        np.testing.assert_allclose(load_b.rating.length_km, orig_b.rating.length_km)
        np.testing.assert_allclose(load_b.rating.slope, orig_b.rating.slope)
        np.testing.assert_allclose(load_b.rating.manning_n, orig_b.rating.manning_n)
        np.testing.assert_allclose(load_b.rating.stage_m, orig_b.rating.stage_m)
        np.testing.assert_allclose(load_b.rating.q_cms, orig_b.rating.q_cms)
        np.testing.assert_allclose(load_b.rating.wet_area_m2, orig_b.rating.wet_area_m2)
        np.testing.assert_allclose(load_b.rating.hyd_radius_m, orig_b.rating.hyd_radius_m)
        np.testing.assert_allclose(load_b.rating.top_width_m, orig_b.rating.top_width_m)


def test_cube_helpers(mini_cube: HandCube) -> None:
    # Feature 103 exists in branch 0 (cidx 2) and branch 9 (cidx 0)
    catchments = mini_cube.catchments_for_feature(103)
    assert (0, 2) in catchments
    assert (9, 0) in catchments

    b0 = mini_cube.branch(0)
    assert b0.branch_id == 0
    b9 = mini_cube.branch(9)
    assert b9.branch_id == 9
