"""Deterministic synthetic fixture generator for mini_huc."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from flood.contracts.models import Scenario
from flood.contracts.validate import validate_json
from flood.engine.cube import HandCube
from flood.interfaces import (
    BranchArrays,
    GAUGE_COLUMNS,
    Grid,
    NETWORK_COLUMNS,
    RatingTable,
)


def _build_cube() -> HandCube:
    grid = Grid.from_bounds((0.0, 0.0, 400.0, 200.0), resolution_m=10.0, crs="EPSG:5070")

    # Network topology:
    # 101 to 103, 102 to 103, 103 to 104, 104 to 105, 105 to 106, 106 to 0
    # Orders: 101 and 102 are 2, the rest 3
    # levelpath_id: 101, 103 to 106 are 9; 102 is 8
    # length_m: 1000.0, slope: 0.002
    # preferred_branch: 9 for 103 to 106, 0 for 101 and 102
    reaches = [
        {
            "feature_id": 101,
            "to_feature_id": 103,
            "stream_order": 2,
            "levelpath_id": 9,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": "90000001",
            "in_aoi": True,
            "preferred_branch": 0,
            "representative_cidx": 0,
            "flowline_wkb": LineString([(10.0, 100.0), (60.0, 100.0)]).wkb,
        },
        {
            "feature_id": 102,
            "to_feature_id": 103,
            "stream_order": 2,
            "levelpath_id": 8,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": None,
            "in_aoi": True,
            "preferred_branch": 0,
            "representative_cidx": 1,
            "flowline_wkb": LineString([(80.0, 100.0), (130.0, 100.0)]).wkb,
        },
        {
            "feature_id": 103,
            "to_feature_id": 104,
            "stream_order": 3,
            "levelpath_id": 9,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": "90000003",
            "in_aoi": True,
            "preferred_branch": 9,
            "representative_cidx": 0,
            "flowline_wkb": LineString([(150.0, 100.0), (190.0, 100.0)]).wkb,
        },
        {
            "feature_id": 104,
            "to_feature_id": 105,
            "stream_order": 3,
            "levelpath_id": 9,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": None,
            "in_aoi": True,
            "preferred_branch": 9,
            "representative_cidx": 1,
            "flowline_wkb": LineString([(210.0, 100.0), (260.0, 100.0)]).wkb,
        },
        {
            "feature_id": 105,
            "to_feature_id": 106,
            "stream_order": 3,
            "levelpath_id": 9,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": "90000005",
            "in_aoi": True,
            "preferred_branch": 9,
            "representative_cidx": 2,
            "flowline_wkb": LineString([(280.0, 100.0), (330.0, 100.0)]).wkb,
        },
        {
            "feature_id": 106,
            "to_feature_id": 0,
            "stream_order": 3,
            "levelpath_id": 9,
            "length_m": 1000.0,
            "slope": 0.002,
            "gauge_site": None,
            "in_aoi": True,
            "preferred_branch": 9,
            "representative_cidx": 3,
            "flowline_wkb": LineString([(350.0, 100.0), (390.0, 100.0)]).wkb,
        },
    ]
    network_df = pd.DataFrame(reaches)[list(NETWORK_COLUMNS)]

    # Gauges table: sites 90000001 (101, boundary), 90000003 (103, interior), 90000005 (105, interior)
    gauges = [
        {
            "site": "90000001",
            "feature_id": 101,
            "role": "boundary",
            "dem_adj_elevation_m": 500.0,
            "gauge_altitude_m": 500.0,
            "altitude_datum": "NAVD88",
        },
        {
            "site": "90000003",
            "feature_id": 103,
            "role": "interior",
            "dem_adj_elevation_m": 490.0,
            "gauge_altitude_m": 490.0,
            "altitude_datum": "NAVD88",
        },
        {
            "site": "90000005",
            "feature_id": 105,
            "role": "interior",
            "dem_adj_elevation_m": 480.0,
            "gauge_altitude_m": 480.0,
            "altitude_datum": "NAVD88",
        },
    ]
    gauges_df = pd.DataFrame(gauges)[list(GAUGE_COLUMNS)]

    # Rating tables: k=84 rows, stage_m = 0.3048 * arange(84)
    k = 84
    stage_m_base = (0.3048 * np.arange(k)).astype(np.float32)

    # Branch 0: 6 catchments
    stage_m_0 = np.tile(stage_m_base, (6, 1))
    a_0 = np.array([8.0, 8.0, 20.0, 20.0, 20.0, 20.0], dtype=np.float32)[:, None]
    q_cms_0 = a_0 * (stage_m_0 ** 1.5)
    top_width_m_0 = np.full((6, k), 10.0, dtype=np.float32)
    wet_area_m2_0 = 10.0 * stage_m_0
    hyd_radius_m_0 = wet_area_m2_0 / (10.0 + 2.0 * stage_m_0)

    rating_0 = RatingTable(
        hydro_id=np.array([25130101, 25130102, 25130103, 25130104, 25130105, 25130106], dtype=np.int64),
        feature_id=np.array([101, 102, 103, 104, 105, 106], dtype=np.int64),
        lake_id=np.full(6, -999, dtype=np.int64),
        stream_order=np.array([2, 2, 3, 3, 3, 3], dtype=np.int16),
        length_km=np.full(6, 1.0, dtype=np.float32),
        slope=np.full(6, 0.002, dtype=np.float32),
        manning_n=np.full(6, 0.06, dtype=np.float32),
        stage_m=stage_m_0,
        q_cms=q_cms_0,
        wet_area_m2=wet_area_m2_0,
        hyd_radius_m=hyd_radius_m_0,
        top_width_m=top_width_m_0,
    )

    # Branch 9: 4 catchments (103 to 106)
    stage_m_9 = np.tile(stage_m_base, (4, 1))
    a_9 = np.full((4, 1), 20.0, dtype=np.float32)
    q_cms_9 = a_9 * (stage_m_9 ** 1.5)
    top_width_m_9 = np.full((4, k), 10.0, dtype=np.float32)
    wet_area_m2_9 = 10.0 * stage_m_9
    hyd_radius_m_9 = wet_area_m2_9 / (10.0 + 2.0 * stage_m_9)

    rating_9 = RatingTable(
        hydro_id=np.array([25130103, 25130104, 25130105, 25130106], dtype=np.int64),
        feature_id=np.array([103, 104, 105, 106], dtype=np.int64),
        lake_id=np.full(4, -999, dtype=np.int64),
        stream_order=np.array([3, 3, 3, 3], dtype=np.int16),
        length_km=np.full(4, 1.0, dtype=np.float32),
        slope=np.full(4, 0.002, dtype=np.float32),
        manning_n=np.full(4, 0.06, dtype=np.float32),
        stage_m=stage_m_9,
        q_cms=q_cms_9,
        wet_area_m2=wet_area_m2_9,
        hyd_radius_m=hyd_radius_m_9,
        top_width_m=top_width_m_9,
    )

    # Branch 0 arrays: height 20, width 40
    rem_0 = np.zeros((20, 40), dtype=np.float32)
    catch_0 = np.full((20, 40), -1, dtype=np.int32)
    for r in range(20):
        rem_0[r, :] = 0.4 * abs(r - 10)

    catch_0[:, 0:7] = 0   # cols 0 to 6
    catch_0[:, 7:14] = 1  # cols 7 to 13
    catch_0[:, 14:20] = 2 # cols 14 to 19
    catch_0[:, 20:27] = 3 # cols 20 to 26
    catch_0[:, 27:34] = 4 # cols 27 to 33
    catch_0[:, 34:40] = 5 # cols 34 to 39

    # Branch 9 arrays: height 20, width 40
    rem_9 = np.full((20, 40), np.nan, dtype=np.float32)
    catch_9 = np.full((20, 40), -1, dtype=np.int32)
    for r in range(20):
        rem_9[r, 14:40] = 0.4 * abs(r - 10) + 0.1

    catch_9[:, 14:20] = 0 # reach 103
    catch_9[:, 20:27] = 1 # reach 104
    catch_9[:, 27:34] = 2 # reach 105
    catch_9[:, 34:40] = 3 # reach 106

    branch0 = BranchArrays(branch_id=0, rem=rem_0, catch=catch_0, rating=rating_0)
    branch9 = BranchArrays(branch_id=9, rem=rem_9, catch=catch_9, rating=rating_9)

    meta = {
        "created_at": "2025-01-01T00:00:00Z",
        "source": "synthetic",
        "fim_version": "4.9.9.0",
    }
    return HandCube(
        grid=grid,
        branches=[branch0, branch9],
        network=network_df,
        gauges=gauges_df,
        meta=meta,
    )


def _q_site1(minutes: float) -> float:
    """Discharge for site 90000001."""
    if 120.0 <= minutes <= 300.0:
        tri = (minutes - 120.0) / 180.0
    elif 300.0 < minutes <= 600.0:
        tri = (600.0 - minutes) / 300.0
    else:
        tri = 0.0
    return 5.0 + 45.0 * tri


def _q_site3(minutes: float) -> float:
    """Discharge for site 90000003."""
    return 2.0 * _q_site1(minutes - 10.0) + 3.0


def _q_site5(minutes: float) -> float:
    """Discharge for site 90000005."""
    return _q_site3(minutes - 20.0) * 0.98


def _build_forcing(data_dir: Path, scenario_id: str) -> None:
    """Write forcing Parquet files in the production data layout."""
    t0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. USGS continuous
    usgs_dir = data_dir / "usgs" / scenario_id
    usgs_dir.mkdir(parents=True, exist_ok=True)

    times_5m: list[datetime] = []
    cur = t0
    while cur <= t_end:
        times_5m.append(cur)
        cur += timedelta(minutes=5)

    usgs_rows: list[dict] = []
    for dt in times_5m:
        m = (dt - t0).total_seconds() / 60.0
        q1 = _q_site1(m)
        q3 = _q_site3(m)
        q5 = _q_site5(m)

        # 00060 parameter
        usgs_rows.append({"site": "90000001", "valid_time": dt, "parameter": "00060", "value_si": float(q1)})
        usgs_rows.append({"site": "90000003", "valid_time": dt, "parameter": "00060", "value_si": float(q3)})
        usgs_rows.append({"site": "90000005", "valid_time": dt, "parameter": "00060", "value_si": float(q5)})

        # 00065 parameter (for 90000001 and 90000003)
        h1 = (q1 / 20.0) ** (2.0 / 3.0)
        h3 = (q3 / 20.0) ** (2.0 / 3.0)
        usgs_rows.append({"site": "90000001", "valid_time": dt, "parameter": "00065", "value_si": float(h1)})
        usgs_rows.append({"site": "90000003", "valid_time": dt, "parameter": "00065", "value_si": float(h3)})

    usgs_df = pd.DataFrame(usgs_rows)
    usgs_df["valid_time"] = pd.to_datetime(usgs_df["valid_time"], utc=True)
    usgs_df.to_parquet(usgs_dir / "continuous.parquet", index=False)

    # 2. NWM analysis
    nwm_dir = data_dir / "nwm" / scenario_id
    nwm_dir.mkdir(parents=True, exist_ok=True)

    times_hourly: list[datetime] = []
    cur = t0
    while cur <= t_end:
        times_hourly.append(cur)
        cur += timedelta(hours=1)

    analysis_rows: list[dict] = []
    for dt in times_hourly:
        m = (dt - t0).total_seconds() / 60.0
        q1 = _q_site1(m)
        q3 = _q_site3(m)
        q5 = _q_site5(m)

        # All six features:
        # 101: 0.5 * q1
        # 102: 0.5 * q1
        # 103: 0.5 * q3
        # 104: 0.5 * q3
        # 105: 0.5 * q5
        # 106: 0.5 * q5
        features_q = [
            (101, 0.5 * q1),
            (102, 0.5 * q1),
            (103, 0.5 * q3),
            (104, 0.5 * q3),
            (105, 0.5 * q5),
            (106, 0.5 * q5),
        ]
        for fid, q_cms in features_q:
            analysis_rows.append({
                "valid_time": dt,
                "feature_id": fid,
                "q_cms": float(q_cms),
                "v_ms": 1.0,
                "qlat_cms": 0.5,
            })

    analysis_df = pd.DataFrame(analysis_rows)
    analysis_df["valid_time"] = pd.to_datetime(analysis_df["valid_time"], utc=True)
    analysis_df.to_parquet(nwm_dir / "analysis.parquet", index=False)

    # 3. NWM short range
    # Issue times: 00:00, 06:00; valid hourly for 6 hours
    short_range_rows: list[dict] = []
    issue_times = [t0, t0 + timedelta(hours=6)]
    for it in issue_times:
        for lead in range(1, 7):
            vt = it + timedelta(hours=lead)
            m = (vt - t0).total_seconds() / 60.0
            q1 = _q_site1(m)
            q3 = _q_site3(m)
            q5 = _q_site5(m)
            features_q = [
                (101, 0.5 * q1),
                (102, 0.5 * q1),
                (103, 0.5 * q3),
                (104, 0.5 * q3),
                (105, 0.5 * q5),
                (106, 0.5 * q5),
            ]
            for fid, a_q in features_q:
                short_range_rows.append({
                    "issue_time": it,
                    "valid_time": vt,
                    "feature_id": fid,
                    "q_cms": float(a_q * 0.9),
                    "qlat_cms": 0.45,
                })

    short_range_df = pd.DataFrame(short_range_rows)
    short_range_df["issue_time"] = pd.to_datetime(short_range_df["issue_time"], utc=True)
    short_range_df["valid_time"] = pd.to_datetime(short_range_df["valid_time"], utc=True)
    short_range_df.to_parquet(nwm_dir / "short_range.parquet", index=False)


def _build_scenario_json(out_dir: Path) -> None:
    scenario_dict = {
        "schema_version": "1.0",
        "scenario_id": "mini-huc",
        "name": "Mini HUC synthetic test scenario",
        "description": "Synthetic 2-branch 5-catchment test fixture",
        "timezone": "UTC",
        "hydrology": {
            "huc8": ["99999999"],
            "fim_version": "4.9.9.0",
            "aoi": {
                "crs": "EPSG:5070",
                "bounds": [0.0, 0.0, 400.0, 200.0],
            },
            "record": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-01T12:00:00Z",
            },
            "gauges": [
                {"site": "90000001", "name": "Gauge 101", "feature_id": 101, "role": "boundary"},
                {"site": "90000003", "name": "Gauge 103", "feature_id": 103, "role": "interior"},
                {"site": "90000005", "name": "Gauge 105", "feature_id": 105, "role": "interior"},
            ],
            "junction_inferences": [
                {
                    "label": "Tributary 102 inference at 103",
                    "inferred_reach": 102,
                    "downstream_gauge": "90000003",
                    "subtract_gauges": ["90000001"],
                    "travel_time_minutes": 10,
                }
            ],
        },
        "forcing_defaults": {
            "sources": [
                {
                    "type": "usgs_continuous",
                    "availability_latency_min": 5,
                    "sites": ["90000001", "90000003", "90000005"],
                    "parameters": ["00060", "00065"],
                },
                {"type": "nwm_analysis_assim", "availability_latency_min": 60},
                {"type": "nwm_short_range", "availability_latency_min": 90, "max_lead_hours": 6},
            ],
            "state_estimation": {
                "bias_correction": "nearest_gauge_ratio",
                "use_junction_inferences": True,
                "ratio_clamp": [0.2, 10.0],
            },
            "boundary_forecast": {
                "method": "trend_relax",
                "members": {"low": 0.5, "mid": 1.0, "high": 1.5},
                "relax_minutes": 60,
                "trend_window_minutes": 30,
            },
            "routing": {"method": "muskingum_cunge", "dt_minutes": 1},
            "roughness": {"manning_n_scale": 1.0},
            "scenario_overrides": [],
        },
        "exposure_layers": [],
        "decision_points": [],
        "last_known_positions": [],
    }
    # Validate against schema before saving
    validate_json("scenario", scenario_dict)
    (out_dir / "scenario.json").write_text(json.dumps(scenario_dict, indent=2), encoding="utf-8")


def build(out_dir: Path | str) -> Path:
    """Build the mini_huc fixture deterministically.

    Layout mirrors production so ``out_dir / "data"`` is a valid ``data_dir``:
      out_dir/scenario.json
      out_dir/data/cube/mini-huc/{meta.json, rem_*.npy, catch_*.npy, rating_*.npz, network.parquet, gauges.parquet}
      out_dir/data/usgs/mini-huc/continuous.parquet
      out_dir/data/nwm/mini-huc/{analysis.parquet, short_range.parquet}
    """
    p = Path(out_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    scenario_id = "mini-huc"
    data_dir = p / "data"

    cube = _build_cube()
    cube.save(data_dir / "cube" / scenario_id)

    _build_forcing(data_dir, scenario_id)
    _build_scenario_json(p)

    return p
