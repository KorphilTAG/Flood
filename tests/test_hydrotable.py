"""Tests for hydrotable rating curve construction and catchment remapping."""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
import pytest
from flood.ingest.hydrotable import build_rating, remap_catchments


def _make_catchment_rows(
    hydro_id: int,
    branch_id: int,
    feature_id: int,
    order: int,
    lake_id: int,
    length_km: float,
    slope: float,
    manning_n: float,
    q_scale: float,
) -> pd.DataFrame:
    k = 84
    stages = (0.3048 * np.arange(k)).astype(np.float32)
    return pd.DataFrame(
        {
            "HydroID": [hydro_id] * k,
            "branch_id": [branch_id] * k,
            "feature_id": [feature_id] * k,
            "order_": [order] * k,
            "LakeID": [lake_id] * k,
            "LENGTHKM": [length_km] * k,
            "SLOPE": [slope] * k,
            "ManningN": [manning_n] * k,
            "stage": stages,
            "discharge_cms": q_scale * stages,
            "WetArea (m2)": 15.0 * stages,
            "HydraulicRadius (m)": 2.0 * stages,
            "TopWidth (m)": 10.0 + stages,
        }
    )


def test_build_rating_two_catchments() -> None:
    # Build two catchments: 200 and 100 (deliberately out of order)
    df_200 = _make_catchment_rows(
        hydro_id=200,
        branch_id=1,
        feature_id=502,
        order=2,
        lake_id=-999,
        length_km=1.5,
        slope=0.001,
        manning_n=0.06,
        q_scale=10.0,
    )
    df_100 = _make_catchment_rows(
        hydro_id=100,
        branch_id=1,
        feature_id=501,
        order=3,
        lake_id=-999,
        length_km=2.5,
        slope=0.002,
        manning_n=0.05,
        q_scale=20.0,
    )
    # Also add a row for a different branch to ensure filtering works
    df_other = _make_catchment_rows(
        hydro_id=300,
        branch_id=2,
        feature_id=503,
        order=1,
        lake_id=-999,
        length_km=3.0,
        slope=0.003,
        manning_n=0.04,
        q_scale=5.0,
    )

    combined_df = pd.concat([df_200, df_100, df_other], ignore_index=True)

    rating, hydroid_to_cidx = build_rating(combined_df, branch_id=1)

    # Sorted by HydroID: 100 is index 0, 200 is index 1
    assert hydroid_to_cidx == {100: 0, 200: 1}

    # Verify 1D arrays
    np.testing.assert_array_equal(rating.hydro_id, np.array([100, 200], dtype=np.int64))
    np.testing.assert_array_equal(rating.feature_id, np.array([501, 502], dtype=np.int64))
    np.testing.assert_array_equal(rating.lake_id, np.array([-999, -999], dtype=np.int64))
    np.testing.assert_array_equal(rating.stream_order, np.array([3, 2], dtype=np.int16))
    np.testing.assert_allclose(rating.length_km, np.array([2.5, 1.5], dtype=np.float32))
    np.testing.assert_allclose(rating.slope, np.array([0.002, 0.001], dtype=np.float32))
    np.testing.assert_allclose(rating.manning_n, np.array([0.05, 0.06], dtype=np.float32))

    # Verify 2D arrays: shape [2, 84]
    assert rating.stage_m.shape == (2, 84)
    assert rating.q_cms.shape == (2, 84)
    assert rating.wet_area_m2.shape == (2, 84)
    assert rating.hyd_radius_m.shape == (2, 84)
    assert rating.top_width_m.shape == (2, 84)

    expected_stages = (0.3048 * np.arange(84)).astype(np.float32)
    np.testing.assert_allclose(rating.stage_m[0], expected_stages, atol=1e-6)
    np.testing.assert_allclose(rating.stage_m[1], expected_stages, atol=1e-6)

    np.testing.assert_allclose(rating.q_cms[0], 20.0 * expected_stages)
    np.testing.assert_allclose(rating.q_cms[1], 10.0 * expected_stages)


def test_build_rating_duplicate_raises() -> None:
    df_100 = _make_catchment_rows(
        hydro_id=100,
        branch_id=1,
        feature_id=501,
        order=3,
        lake_id=-999,
        length_km=2.5,
        slope=0.002,
        manning_n=0.05,
        q_scale=20.0,
    )
    # Duplicate one row so (HydroID, stage) is duplicated
    duplicate_row = df_100.iloc[[0]]
    bad_df = pd.concat([df_100, duplicate_row], ignore_index=True)

    with pytest.raises(ValueError, match="Duplicate"):
        build_rating(bad_df, branch_id=1)


def test_remap_catchments(caplog: pytest.LogCaptureFixture) -> None:
    hydroid_to_cidx = {100: 0, 200: 1}
    catch_hydroid = np.array(
        [
            [100, 200],
            [999, -1],
        ],
        dtype=np.int32,
    )

    with caplog.at_level(logging.INFO):
        remapped = remap_catchments(catch_hydroid, hydroid_to_cidx)

    expected = np.array(
        [
            [0, 1],
            [-1, -1],
        ],
        dtype=np.int32,
    )
    np.testing.assert_array_equal(remapped, expected)
    assert remapped.dtype == np.int32
    # Check that unknown HydroID count was logged
    assert "Remapped 1 pixels with unknown HydroIDs to -1" in caplog.text
