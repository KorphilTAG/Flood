"""Tests for network and gauge table building."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString
from flood.contracts.models import Scenario
from flood.ingest.network import build_gauges, build_network
from flood.interfaces import GAUGE_COLUMNS, Grid, NETWORK_COLUMNS


def test_build_network(mini_scenario: Scenario) -> None:
    grid = Grid.from_bounds((0.0, 0.0, 400.0, 200.0), resolution_m=10.0, crs="EPSG:5070")

    # Synthetic streams GeoDataFrame with 4 reaches:
    # 101 inside AOI, to=103
    # 102 inside AOI, to=103
    # 103 inside AOI, to=9999 (outside HUC subset)
    # 104 outside AOI, to=0
    streams = [
        {
            "ID": 101,
            "to": 103,
            "order_": 2,
            "Slope": 0.002,
            "Length": 1000.0,
            "levpa_id": 9,
            "gages": " 90000001 ",
            "geometry": LineString([(10.0, 100.0), (60.0, 100.0)]),
        },
        {
            "ID": 102,
            "to": 103,
            "order_": 2,
            "Slope": 0.002,
            "Length": 1000.0,
            "levpa_id": 8,
            "gages": None,
            "geometry": LineString([(80.0, 100.0), (130.0, 100.0)]),
        },
        {
            "ID": 103,
            "to": 9999,  # Outside HUC subset
            "order_": 3,
            "Slope": 0.002,
            "Length": 1000.0,
            "levpa_id": 9,
            "gages": "90000003",
            "geometry": LineString([(150.0, 100.0), (190.0, 100.0)]),
        },
        {
            "ID": 104,
            "to": 0,
            "order_": 3,
            "Slope": 0.002,
            "Length": 1000.0,
            "levpa_id": 9,
            "gages": None,
            "geometry": LineString([(800.0, 800.0), (900.0, 800.0)]),  # Outside AOI
        },
    ]
    streams_gdf = gpd.GeoDataFrame(streams, crs="EPSG:5070")

    # Hydrotable with branch 9 (features 103, 104) and branch 0 (features 101, 102, 103)
    hydro_rows = [
        # Branch 0
        {"branch_id": 0, "HydroID": 25130101, "feature_id": 101, "LENGTHKM": 1.0},
        {"branch_id": 0, "HydroID": 25130102, "feature_id": 102, "LENGTHKM": 1.2},
        {"branch_id": 0, "HydroID": 25130100, "feature_id": 103, "LENGTHKM": 0.5},
        # Branch 9: HydroIDs 25130103 (feature 103), 25130104 (feature 104)
        {"branch_id": 9, "HydroID": 25130103, "feature_id": 103, "LENGTHKM": 1.5},
        {"branch_id": 9, "HydroID": 25130104, "feature_id": 104, "LENGTHKM": 2.0},
    ]
    hydrotable_df = pd.DataFrame(hydro_rows)

    net_df = build_network(streams_gdf, hydrotable_df, mini_scenario, grid)

    # 1. Exact columns
    assert tuple(net_df.columns) == NETWORK_COLUMNS

    # 2. to_feature_id
    row_101 = net_df[net_df["feature_id"] == 101].iloc[0]
    row_103 = net_df[net_df["feature_id"] == 103].iloc[0]
    row_104 = net_df[net_df["feature_id"] == 104].iloc[0]

    assert row_101["to_feature_id"] == 103
    # 9999 is outside HUC subset, so to_feature_id must be 0
    assert row_103["to_feature_id"] == 0

    # 3. preferred_branch
    # 101 has levpa_id 9, but branch 9 does not contain 101 -> preferred_branch == 0
    assert row_101["preferred_branch"] == 0
    # 103 has levpa_id 9, and branch 9 contains 103 -> preferred_branch == 9
    assert row_103["preferred_branch"] == 9

    # 4. representative_cidx
    # In branch 0: HydroIDs are 25130100 (cidx 0), 25130101 (cidx 1), 25130102 (cidx 2)
    # Feature 101 has HydroID 25130101 -> cidx 1
    assert row_101["representative_cidx"] == 1
    # In branch 9: HydroIDs are 25130103 (cidx 0), 25130104 (cidx 1)
    # Feature 103 has HydroID 25130103 -> cidx 0
    assert row_103["representative_cidx"] == 0

    # 5. in_aoi
    assert bool(row_101["in_aoi"]) is True
    assert bool(row_103["in_aoi"]) is True
    assert bool(row_104["in_aoi"]) is False

    # 6. flowline_wkb
    assert isinstance(row_101["flowline_wkb"], bytes)

    # 7. gauge_site
    assert row_101["gauge_site"] == "90000001"
    assert row_103["gauge_site"] == "90000003"
    assert pd.isna(row_104["gauge_site"]) or row_104["gauge_site"] is None


def test_build_gauges(mini_scenario: Scenario) -> None:
    # Scenario has gauges: 90000001, 90000003, 90000005
    usgs_elev = pd.DataFrame(
        [
            {
                "location_id": "90000001",
                "feature_id": 101,
                "dem_adj_elevation": 500.0,
                "usgs_data_altitude": 1000.0,  # feet
                "usgs_data_alt_datum_code": "NAVD88",
            },
            # Duplicate row for 90000001 (should take first)
            {
                "location_id": "90000001",
                "feature_id": 101,
                "dem_adj_elevation": 999.0,
                "usgs_data_altitude": 9999.0,
                "usgs_data_alt_datum_code": "NGVD29",
            },
            {
                "location_id": "90000003",
                "feature_id": 103,
                "dem_adj_elevation": 490.0,
                "usgs_data_altitude": 980.0,
                "usgs_data_alt_datum_code": "NAVD88",
            },
            {
                "location_id": "90000005",
                "feature_id": 105,
                "dem_adj_elevation": 480.0,
                "usgs_data_altitude": 960.0,
                "usgs_data_alt_datum_code": "NAVD88",
            },
        ]
    )

    gauges_df = build_gauges(usgs_elev, mini_scenario)

    assert tuple(gauges_df.columns) == GAUGE_COLUMNS
    assert len(gauges_df) == 3

    g1 = gauges_df[gauges_df["site"] == "90000001"].iloc[0]
    assert g1["dem_adj_elevation_m"] == 500.0
    assert g1["gauge_altitude_m"] == pytest.approx(1000.0 * 0.3048)
    assert g1["altitude_datum"] == "NAVD88"


def test_build_gauges_missing_raises(mini_scenario: Scenario) -> None:
    # Only site 90000001 provided; 90000003 and 90000005 missing
    usgs_elev = pd.DataFrame(
        [
            {
                "location_id": "90000001",
                "feature_id": 101,
                "dem_adj_elevation": 500.0,
                "usgs_data_altitude": 1000.0,
                "usgs_data_alt_datum_code": "NAVD88",
            }
        ]
    )

    with pytest.raises(ValueError, match="Scenario sites missing"):
        build_gauges(usgs_elev, mini_scenario)
