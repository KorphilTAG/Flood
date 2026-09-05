"""Tests for HAND mapping and velocity proxy."""
import numpy as np
import pytest
from flood.engine.cube import HandCube
from flood.engine.mapping import map_member
from flood.engine.rating import hyd_radius, stage_from_q, wet_area
from flood.interfaces import MIN_DEPTH_M


NODE_STAGE = 0.3048 * 5  # 1.524 m, a node of the 1-ft rating table, so interpolation is exact


def test_exact_depth_at_table_node(mini_cube: HandCube):
    q = {103: 20.0 * (NODE_STAGE ** 1.5), 101: 0.0, 102: 0.0, 104: 0.0, 105: 0.0, 106: 0.0}
    mf = map_member(mini_cube, q, with_velocity=True)
    depth = mf.depth

    # Branch 0 depth in cols 14..19 is s - 0.4 * |row - 10|; branch 9 is 0.1 m less.
    # The fmax mosaic is max(0, s - 0.4 * |row - 10|) with s = NODE_STAGE.
    expected = np.zeros_like(depth)
    for r in range(20):
        val = NODE_STAGE - 0.4 * abs(r - 10)
        expected[r, 14:20] = val if val >= MIN_DEPTH_M else 0.0

    np.testing.assert_allclose(depth, expected, atol=1e-4)
    assert np.all(depth[7:14, 14:20] > 0.0)
    assert np.all(depth[:7, 14:20] == 0.0) and np.all(depth[14:, 14:20] == 0.0)
    assert np.all(depth[:, :14] == 0.0) and np.all(depth[:, 20:] == 0.0)


def test_exact_depth_fixture(mini_cube: HandCube):
    q = {103: 20.0 * (1.5 ** 1.5), 101: 0.0, 102: 0.0, 104: 0.0, 105: 0.0, 106: 0.0}
    mf = map_member(mini_cube, q, with_velocity=True)
    depth = mf.depth

    expected = np.zeros_like(depth)
    for r in range(20):
        val = 1.5 - 0.4 * abs(r - 10)
        expected[r, 14:20] = val if val >= MIN_DEPTH_M else 0.0

    # Within table discretization tolerance of 2 mm
    np.testing.assert_allclose(depth, expected, atol=2e-3)

    # Rows 7 to 13 are wet (> 0)
    assert np.all(depth[7:14, 14:20] > 0.0)

    # Every other row in cols 14..19 is exactly 0
    assert np.all(depth[:7, 14:20] == 0.0)
    assert np.all(depth[14:, 14:20] == 0.0)

    # Every other column is exactly 0
    assert np.all(depth[:, :14] == 0.0)
    assert np.all(depth[:, 20:] == 0.0)


def test_velocity_channel_row_at_table_node(mini_cube: HandCube):
    q_val = 20.0 * (NODE_STAGE ** 1.5)
    q = {103: q_val, 101: 0.0, 102: 0.0, 104: 0.0, 105: 0.0, 106: 0.0}
    mf = map_member(mini_cube, q, with_velocity=True)
    assert mf.velocity is not None

    b0 = mini_cube.branch(0)
    rt = b0.rating
    s, _ = stage_from_q(rt, 2, q_val)
    wa = wet_area(rt, 2, s)
    hr = hyd_radius(rt, 2, s)
    v_reach = q_val / wa

    # Channel-row cell of block 103 equals v_reach * (depth / R) ** (2/3) within 1e-3
    expected_v = v_reach * ((NODE_STAGE / hr) ** (2.0 / 3.0))
    actual_v = mf.velocity[10, 15]
    np.testing.assert_allclose(actual_v, expected_v, atol=1e-3)


def test_velocity_channel_row(mini_cube: HandCube):
    q_val = 20.0 * (1.5 ** 1.5)
    q = {103: q_val, 101: 0.0, 102: 0.0, 104: 0.0, 105: 0.0, 106: 0.0}
    mf = map_member(mini_cube, q, with_velocity=True)
    assert mf.velocity is not None

    b0 = mini_cube.branch(0)
    rt = b0.rating
    s, _ = stage_from_q(rt, 2, q_val)
    wa = wet_area(rt, 2, s)
    hr = hyd_radius(rt, 2, s)
    v_reach = q_val / wa

    # At row 10, cell depth is s (1.4988 m)
    depth_10 = mf.depth[10, 15]
    expected_v_looked_up = v_reach * ((depth_10 / hr) ** (2.0 / 3.0))
    actual_v = mf.velocity[10, 15]
    np.testing.assert_allclose(actual_v, expected_v_looked_up, atol=1e-5)

    # And within 2e-3 of formula using 1.5
    expected_v_formula = v_reach * ((1.5 / hr) ** (2.0 / 3.0))
    np.testing.assert_allclose(actual_v, expected_v_formula, atol=2e-3)

    # 0 where depth is 0
    assert np.all(mf.velocity[mf.depth == 0.0] == 0.0)


def test_without_velocity(mini_cube: HandCube):
    q = {103: 10.0}
    mf = map_member(mini_cube, q, with_velocity=False)
    assert mf.velocity is None


def test_clipping_flag(mini_cube: HandCube):
    b0 = mini_cube.branch(0)
    q_top = float(b0.rating.q_cms[2, -1])

    # Not clipped
    mf_normal = map_member(mini_cube, {103: q_top - 10.0})
    assert not mf_normal.clipped[103]

    # Clipped
    mf_clipped = map_member(mini_cube, {103: q_top + 500.0})
    assert mf_clipped.clipped[103]
