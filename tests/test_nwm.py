"""Tests for NWM ingest: name generators, NetCDF subsetting, manifest skip logic, and GCS listing."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import httpx
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from flood.ingest.nwm import (
    GCS_OBJECT_URL,
    analysis_names,
    append_to_parquet,
    load_manifest,
    save_manifest,
    short_range_names,
    subset_file,
)


def test_analysis_names() -> None:
    # Exact hour boundaries
    names = analysis_names("2025-01-01T00:00:00Z", "2025-01-01T03:00:00Z")
    assert len(names) == 4
    assert names[0] == "nwm.20250101/analysis_assim/nwm.t00z.analysis_assim.channel_rt.tm00.conus.nc"
    assert names[1] == "nwm.20250101/analysis_assim/nwm.t01z.analysis_assim.channel_rt.tm00.conus.nc"
    assert names[2] == "nwm.20250101/analysis_assim/nwm.t02z.analysis_assim.channel_rt.tm00.conus.nc"
    assert names[3] == "nwm.20250101/analysis_assim/nwm.t03z.analysis_assim.channel_rt.tm00.conus.nc"

    # Non-round boundary (start at 00:30, end at 02:45)
    names_sub = analysis_names("2025-01-01T00:30:00Z", "2025-01-01T02:45:00Z")
    assert len(names_sub) == 2
    assert names_sub[0] == "nwm.20250101/analysis_assim/nwm.t01z.analysis_assim.channel_rt.tm00.conus.nc"
    assert names_sub[1] == "nwm.20250101/analysis_assim/nwm.t02z.analysis_assim.channel_rt.tm00.conus.nc"


def test_short_range_names() -> None:
    # 2 cycles (00:00 and 01:00), max_lead_hours=3
    names = short_range_names("2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z", max_lead_hours=3)
    assert len(names) == 6
    assert names[0] == "nwm.20250101/short_range/nwm.t00z.short_range.channel_rt.f001.conus.nc"
    assert names[1] == "nwm.20250101/short_range/nwm.t00z.short_range.channel_rt.f002.conus.nc"
    assert names[2] == "nwm.20250101/short_range/nwm.t00z.short_range.channel_rt.f003.conus.nc"
    assert names[3] == "nwm.20250101/short_range/nwm.t01z.short_range.channel_rt.f001.conus.nc"
    assert names[4] == "nwm.20250101/short_range/nwm.t01z.short_range.channel_rt.f002.conus.nc"
    assert names[5] == "nwm.20250101/short_range/nwm.t01z.short_range.channel_rt.f003.conus.nc"


def _create_synthetic_netcdf(
    path: Path,
    time_str: str = "2025-01-01T00:00:00",
    ref_time_str: str = "2025-01-01T00:00:00",
    scale_factor: float = 0.01,
) -> None:
    """Create a 5-feature synthetic channel_rt netCDF file at test time."""
    feature_ids = np.array([101, 102, 103, 104, 105], dtype=np.int64)
    # Stored unscaled streamflow in int32: [1000, 2500, 3000, 4500, 5000] -> decoded [10.0, 25.0, 30.0, 45.0, 50.0]
    streamflow_raw = np.array([1000, 2500, 3000, 4500, 5000], dtype=np.int32)
    velocity = np.array([1.1, 1.2, 1.3, 1.4, 1.5], dtype=np.float32)
    q_sfc = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
    q_bkt = np.array([0.05, 0.05, 0.05, 0.05, 0.05], dtype=np.float32)

    ds = xr.Dataset(
        data_vars={
            "streamflow": (("feature_id",), (streamflow_raw * scale_factor).astype(np.float32)),
            "velocity": (("feature_id",), velocity),
            "qSfcLatRunoff": (("feature_id",), q_sfc),
            "qBucket": (("feature_id",), q_bkt),
        },
        coords={
            "feature_id": feature_ids,
            "time": (("time",), np.array([time_str], dtype="datetime64[s]")),
            "reference_time": (("reference_time",), np.array([ref_time_str], dtype="datetime64[s]")),
        },
    )
    encoding = {
        "streamflow": {
            "dtype": "int32",
            "scale_factor": scale_factor,
            "_FillValue": -999900,
        }
    }
    ds.to_netcdf(path, engine="h5netcdf", encoding=encoding)


def test_subset_file(tmp_path: Path) -> None:
    nc_path = tmp_path / "nwm.t00z.analysis_assim.channel_rt.tm00.conus.nc"
    _create_synthetic_netcdf(nc_path)

    # Subset 3 of the 5 features
    fids = [101, 103, 105]
    df = subset_file(nc_path, fids)

    expected_cols = ["valid_time", "feature_id", "q_cms", "v_ms", "qlat_cms"]
    assert list(df.columns) == expected_cols
    assert len(df) == 3
    assert list(df["feature_id"]) == [101, 103, 105]

    # Check decoded streamflow values: 1000 * 0.01 = 10.0, 3000 * 0.01 = 30.0, 5000 * 0.01 = 50.0
    np.testing.assert_allclose(df["q_cms"], [10.0, 30.0, 50.0], rtol=1e-5)
    np.testing.assert_allclose(df["v_ms"], [1.1, 1.3, 1.5], rtol=1e-5)
    # qlat_cms = qSfcLatRunoff + qBucket: 0.1 + 0.05 = 0.15, 0.3 + 0.05 = 0.35, 0.5 + 0.05 = 0.55
    np.testing.assert_allclose(df["qlat_cms"], [0.15, 0.35, 0.55], rtol=1e-5)

    assert df["valid_time"].dt.tz is not None
    assert df["valid_time"].iloc[0] == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_subset_file_short_range(tmp_path: Path) -> None:
    nc_path = tmp_path / "nwm.t00z.short_range.channel_rt.f001.conus.nc"
    _create_synthetic_netcdf(
        nc_path,
        time_str="2025-01-01T01:00:00",
        ref_time_str="2025-01-01T00:00:00",
    )

    fids = [102, 104]
    df = subset_file(nc_path, fids)

    assert "issue_time" in df.columns
    assert "valid_time" in df.columns
    assert list(df["feature_id"]) == [102, 104]
    np.testing.assert_allclose(df["q_cms"], [25.0, 45.0], rtol=1e-5)
    assert df["issue_time"].iloc[0] == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert df["valid_time"].iloc[0] == datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_manifest_and_parquet_append(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    assert load_manifest(manifest_path) == set()

    save_manifest(manifest_path, ["file_a.nc", "file_b.nc"])
    loaded = load_manifest(manifest_path)
    assert loaded == {"file_a.nc", "file_b.nc"}

    # Test parquet append
    parquet_path = tmp_path / "analysis.parquet"
    df1 = pd.DataFrame({
        "valid_time": pd.to_datetime(["2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"], utc=True),
        "feature_id": [101, 102],
        "q_cms": [10.0, 20.0],
        "v_ms": [1.0, 1.0],
        "qlat_cms": [0.5, 0.5],
    })
    append_to_parquet(df1, parquet_path, ["valid_time", "feature_id"])

    # Append second batch with one duplicate and one new
    df2 = pd.DataFrame({
        "valid_time": pd.to_datetime(["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"], utc=True),
        "feature_id": [102, 102],
        "q_cms": [20.0, 22.0],
        "v_ms": [1.0, 1.1],
        "qlat_cms": [0.5, 0.6],
    })
    append_to_parquet(df2, parquet_path, ["valid_time", "feature_id"])

    result = pd.read_parquet(parquet_path)
    assert len(result) == 3
    assert list(result["feature_id"]) == [101, 102, 102]


@pytest.mark.network
def test_list_kerr_day() -> None:
    """List 24 analysis names for a single day and confirm the first exists with a HEAD request."""
    # Kerr record starts on 2025-07-03T12:00:00Z; let's list 24 hours of 2025-07-04
    day_start = "2025-07-04T00:00:00Z"
    day_end = "2025-07-04T23:00:00Z"
    names = analysis_names(day_start, day_end)
    assert len(names) == 24

    first_name = names[0]
    first_url = GCS_OBJECT_URL.format(name=first_name)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.head(first_url)
        assert resp.status_code == 200, f"HEAD {first_url} returned {resp.status_code}"
