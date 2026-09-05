"""Network and gauge table assembly."""
from __future__ import annotations

import logging
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely.geometry
from flood.contracts.models import Scenario
from flood.interfaces import GAUGE_COLUMNS, Grid, NETWORK_COLUMNS

logger = logging.getLogger("flood.ingest.hand")


def build_network(
    streams_gdf: gpd.GeoDataFrame,
    hydrotable_df: pd.DataFrame,
    scenario: Scenario,
    grid: Grid,
) -> pd.DataFrame:
    """Build reach network table from streams layer and hydrotable.

    Returns DataFrame with columns exactly equal to NETWORK_COLUMNS.
    """
    all_feature_ids = set(streams_gdf["ID"].astype(int))

    order_col = "order_" if "order_" in streams_gdf.columns else (
        "order" if "order" in streams_gdf.columns else "stream_order"
    )

    # Pre-map scenario gauges by feature_id
    scenario_gauges_by_fid = {g.feature_id: g.site for g in scenario.hydrology.gauges}

    # Bounding box for AOI intersection
    aoi_box = shapely.geometry.box(*grid.bounds)

    # Pre-process hydrotable for branch assignment and representative cidx
    catchment_df = hydrotable_df[["branch_id", "HydroID", "feature_id", "LENGTHKM"]].drop_duplicates()

    # Precompute cidx (sorted HydroID) per branch
    hid_to_cidx_by_branch: dict[int, dict[int, int]] = {}
    for b in catchment_df["branch_id"].unique():
        unique_hids = np.sort(catchment_df[catchment_df["branch_id"] == b]["HydroID"].unique())
        hid_to_cidx_by_branch[int(b)] = {int(hid): i for i, hid in enumerate(unique_hids)}

    feature_ids: list[int] = []
    to_feature_ids: list[int] = []
    stream_orders: list[int] = []
    levelpath_ids: list[int] = []
    length_ms: list[float] = []
    slopes: list[float] = []
    gauge_sites: list[str | None] = []
    in_aois: list[bool] = []
    preferred_branches: list[int] = []
    representative_cidxs: list[int] = []
    flowline_wkbs: list[bytes] = []

    for _, row in streams_gdf.iterrows():
        fid = int(row["ID"])
        feature_ids.append(fid)

        # to_feature_id is 0 where to reach is outside the HUC subset
        to_val = row["to"]
        if pd.notna(to_val) and int(to_val) in all_feature_ids:
            to_feature_ids.append(int(to_val))
        else:
            to_feature_ids.append(0)

        stream_orders.append(int(row[order_col]))

        levpa_id = int(row["levpa_id"])
        levelpath_ids.append(levpa_id)

        length_ms.append(float(row["Length"]))
        slopes.append(float(row["Slope"]))

        # Gauge site
        raw_gauge = row.get("gages")
        gauge_str: str | None = None
        if pd.notna(raw_gauge):
            s = str(raw_gauge).strip()
            if s:
                gauge_str = s
        if gauge_str is None and fid in scenario_gauges_by_fid:
            gauge_str = scenario_gauges_by_fid[fid]
        gauge_sites.append(gauge_str)

        # AOI intersection and geometry WKB
        geom = row.geometry
        in_aois.append(bool(geom.intersects(aoi_box)))
        flowline_wkbs.append(geom.wkb)

        # Preferred branch and representative cidx
        # Check if feature exists in branch levpa_id
        b_reaches = catchment_df[
            (catchment_df["branch_id"] == levpa_id) & (catchment_df["feature_id"] == fid)
        ]
        if not b_reaches.empty:
            pref_branch = levpa_id
        else:
            pref_branch = 0
            b_reaches = catchment_df[
                (catchment_df["branch_id"] == 0) & (catchment_df["feature_id"] == fid)
            ]

        if not b_reaches.empty:
            # Longest catchment in preferred branch
            best_row = b_reaches.sort_values(
                by=["LENGTHKM", "HydroID"], ascending=[False, True]
            ).iloc[0]
            best_hid = int(best_row["HydroID"])
            rep_cidx = hid_to_cidx_by_branch[pref_branch][best_hid]
        else:
            rep_cidx = -1

        preferred_branches.append(pref_branch)
        representative_cidxs.append(rep_cidx)

    network_df = pd.DataFrame(
        {
            "feature_id": feature_ids,
            "to_feature_id": to_feature_ids,
            "stream_order": stream_orders,
            "levelpath_id": levelpath_ids,
            "length_m": length_ms,
            "slope": slopes,
            "gauge_site": gauge_sites,
            "in_aoi": in_aois,
            "preferred_branch": preferred_branches,
            "representative_cidx": representative_cidxs,
            "flowline_wkb": flowline_wkbs,
        }
    )

    return network_df[list(NETWORK_COLUMNS)]


def build_gauges(usgs_elev_df: pd.DataFrame, scenario: Scenario) -> pd.DataFrame:
    """Build gauges table joined from usgs_elev_table and scenario gauge list.

    Returns DataFrame with columns exactly equal to GAUGE_COLUMNS.
    Raises ValueError naming any scenario site missing from usgs_elev_table.
    """
    elev_copy = usgs_elev_df.copy()
    elev_copy["location_id"] = elev_copy["location_id"].astype(str).str.strip()

    # Take first row per site if multiple rows exist (one per branch)
    elev_first = elev_copy.drop_duplicates(subset=["location_id"], keep="first")
    elev_by_site = {
        row["location_id"]: row for _, row in elev_first.iterrows()
    }

    missing_sites: list[str] = []
    sites: list[str] = []
    feature_ids: list[int] = []
    roles: list[str] = []
    dem_adj_elevations: list[float] = []
    gauge_altitudes: list[float] = []
    altitude_datums: list[str] = []

    for g in scenario.hydrology.gauges:
        site_str = str(g.site).strip()
        if site_str not in elev_by_site:
            missing_sites.append(site_str)
            continue

        row = elev_by_site[site_str]
        sites.append(site_str)
        feature_ids.append(int(g.feature_id))
        roles.append(str(g.role))
        dem_adj_elevations.append(float(row["dem_adj_elevation"]))
        # Convert altitude from feet to metres
        alt_ft = float(row["usgs_data_altitude"])
        gauge_altitudes.append(alt_ft * 0.3048)
        altitude_datums.append(str(row["usgs_data_alt_datum_code"]))

    if missing_sites:
        raise ValueError(f"Scenario sites missing from usgs_elev_table: {missing_sites}")

    gauges_df = pd.DataFrame(
        {
            "site": sites,
            "feature_id": feature_ids,
            "role": roles,
            "dem_adj_elevation_m": dem_adj_elevations,
            "gauge_altitude_m": gauge_altitudes,
            "altitude_datum": altitude_datums,
        }
    )

    return gauges_df[list(GAUGE_COLUMNS)]
