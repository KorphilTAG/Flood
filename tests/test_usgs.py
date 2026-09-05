"""Tests for USGS continuous ingest: paging via MockTransport and unit conversions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import httpx
import numpy as np
import pytest

from flood.ingest.usgs import (
    CFS_TO_CMS,
    FT_TO_M,
    USGS_CONTINUOUS_URL,
    fetch_continuous,
)


def test_unit_conversions() -> None:
    # 00060: cfs to cms
    cfs = 100.0
    expected_cms = cfs * 0.028316846592
    assert np.isclose(expected_cms, 2.8316846592)
    assert CFS_TO_CMS == 0.028316846592

    # 00065: ft to m
    ft = 10.0
    expected_m = ft * 0.3048
    assert np.isclose(expected_m, 3.048)
    assert FT_TO_M == 0.3048


def test_fetch_continuous_mock_paging(repo_root: Path) -> None:
    fixtures_dir = repo_root / "tests" / "fixtures" / "forcing"
    page1_text = (fixtures_dir / "usgs_page1.json").read_text(encoding="utf-8")
    page2_text = (fixtures_dir / "usgs_page2.json").read_text(encoding="utf-8")

    requests_received: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requests_received.append(url_str)
        if "offset=5" in url_str:
            return httpx.Response(200, text=page2_text, headers={"content-type": "application/json"})
        return httpx.Response(200, text=page1_text, headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        df = fetch_continuous(
            site="08165300",
            parameter="00060",
            start="2025-07-03T12:00:00Z",
            end="2025-07-03T13:00:00Z",
            client=client,
            limit=5,
        )

    # Both page 1 and page 2 should have been requested
    assert len(requests_received) == 2
    assert "offset=5" in requests_received[1]

    expected_cols = ["site", "valid_time", "parameter", "value_si", "approval"]
    assert list(df.columns) == expected_cols
    assert len(df) == 5

    assert (df["site"] == "08165300").all()
    assert (df["parameter"] == "00060").all()
    assert df["valid_time"].dt.tz is not None

    # First value in page 1 is 9.66 cfs
    first_cfs = 9.66
    expected_si = np.float32(first_cfs * CFS_TO_CMS)
    assert np.isclose(df["value_si"].iloc[0], expected_si, rtol=1e-5)
    assert df["approval"].iloc[0] == "Approved"


def test_fetch_continuous_stage_conversion(repo_root: Path) -> None:
    # Test 00065 ft to m conversion
    mock_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "time": "2025-07-03T12:00:00+00:00",
                    "value": "10.0",
                    "parameter_code": "00065",
                    "approval_status": "Approved",
                },
            }
        ],
        "links": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        df = fetch_continuous(
            site="08165300",
            parameter="00065",
            start="2025-07-03T12:00:00Z",
            end="2025-07-03T13:00:00Z",
            client=client,
        )

    assert len(df) == 1
    assert df["parameter"].iloc[0] == "00065"
    assert np.isclose(df["value_si"].iloc[0], 10.0 * 0.3048, rtol=1e-5)
