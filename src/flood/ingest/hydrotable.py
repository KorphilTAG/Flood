"""Hydrotable parsing, rating curve table creation, and catchment remapping."""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from flood.interfaces import RatingTable

logger = logging.getLogger("flood.ingest.hand")


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"None of columns {candidates} found in hydrotable")


def build_rating(
    hydrotable_df: pd.DataFrame,
    branch_id: int,
) -> tuple[RatingTable, dict[int, int]]:
    """Build RatingTable and HydroID-to-cidx map for a single branch.

    Args:
        hydrotable_df: Hydrotable DataFrame containing all branches or filtered.
        branch_id: Branch ID to extract.

    Returns:
        (RatingTable, hydroid_to_cidx dict)
    """
    b_df = hydrotable_df[hydrotable_df["branch_id"] == branch_id]
    if "HydroID" not in b_df.columns and "HydroID" in b_df.index.names:
        b_df = b_df.reset_index()

    if b_df.empty:
        raise ValueError(f"No records found for branch {branch_id}")

    # Check for duplicate (branch_id, HydroID, stage) pairs
    if b_df.duplicated(subset=["HydroID", "stage"]).any():
        raise ValueError(f"Duplicate (branch_id, HydroID) pairs found in branch {branch_id}")

    # Check that each HydroID has exactly 84 stages
    counts = b_df.groupby("HydroID").size()
    if (counts != 84).any():
        bad_hids = counts[counts != 84].index.tolist()
        raise ValueError(
            f"Expected 84 stage rows per HydroID in branch {branch_id}, but found unexpected counts for HydroIDs: {bad_hids}"
        )

    # Resolve column names
    wet_area_col = _find_column(b_df, ("WetArea (m2)", "WetArea", "wet_area_m2"))
    hyd_radius_col = _find_column(b_df, ("HydraulicRadius (m)", "HydraulicRadius", "hyd_radius_m"))
    top_width_col = _find_column(b_df, ("TopWidth (m)", "TopWidth", "top_width_m"))
    order_col = _find_column(b_df, ("order_", "order", "stream_order"))
    lake_col = "LakeID" if "LakeID" in b_df.columns else None

    # Sort HydroIDs to assign cidx = 0..n-1
    unique_hydroids = np.sort(b_df["HydroID"].unique())
    n = len(unique_hydroids)
    hydroid_to_cidx = {int(hid): idx for idx, hid in enumerate(unique_hydroids)}

    expected_stages = (0.3048 * np.arange(84)).astype(np.float32)

    hydro_id_arr = unique_hydroids.astype(np.int64)
    feature_id_arr = np.empty(n, dtype=np.int64)
    lake_id_arr = np.full(n, -999, dtype=np.int64)
    stream_order_arr = np.empty(n, dtype=np.int16)
    length_km_arr = np.empty(n, dtype=np.float32)
    slope_arr = np.empty(n, dtype=np.float32)
    manning_n_arr = np.empty(n, dtype=np.float32)

    stage_m_arr = np.empty((n, 84), dtype=np.float32)
    q_cms_arr = np.empty((n, 84), dtype=np.float32)
    wet_area_m2_arr = np.empty((n, 84), dtype=np.float32)
    hyd_radius_m_arr = np.empty((n, 84), dtype=np.float32)
    top_width_m_arr = np.empty((n, 84), dtype=np.float32)

    for idx, hid in enumerate(unique_hydroids):
        group = b_df[b_df["HydroID"] == hid].sort_values("stage")
        stages = group["stage"].to_numpy(dtype=np.float32)

        if not np.allclose(stages, expected_stages, atol=1e-6):
            raise ValueError(
                f"Stage values for HydroID {hid} do not equal 0.3048 * arange(84) within 1e-6"
            )

        first_row = group.iloc[0]
        feature_id_arr[idx] = int(first_row["feature_id"])
        if lake_col and pd.notna(first_row[lake_col]):
            lake_id_arr[idx] = int(first_row[lake_col])
        else:
            lake_id_arr[idx] = -999
        stream_order_arr[idx] = int(first_row[order_col])
        length_km_arr[idx] = float(first_row["LENGTHKM"])
        slope_arr[idx] = float(first_row["SLOPE"])
        manning_n_arr[idx] = float(first_row["ManningN"])

        stage_m_arr[idx, :] = stages
        q_cms_arr[idx, :] = group["discharge_cms"].to_numpy(dtype=np.float32)
        wet_area_m2_arr[idx, :] = group[wet_area_col].to_numpy(dtype=np.float32)
        hyd_radius_m_arr[idx, :] = group[hyd_radius_col].to_numpy(dtype=np.float32)
        top_width_m_arr[idx, :] = group[top_width_col].to_numpy(dtype=np.float32)

    rating_table = RatingTable(
        hydro_id=hydro_id_arr,
        feature_id=feature_id_arr,
        lake_id=lake_id_arr,
        stream_order=stream_order_arr,
        length_km=length_km_arr,
        slope=slope_arr,
        manning_n=manning_n_arr,
        stage_m=stage_m_arr,
        q_cms=q_cms_arr,
        wet_area_m2=wet_area_m2_arr,
        hyd_radius_m=hyd_radius_m_arr,
        top_width_m=top_width_m_arr,
    )

    return rating_table, hydroid_to_cidx


def remap_catchments(
    catch_hydroid: np.ndarray,
    hydroid_to_cidx: dict[int, int],
) -> np.ndarray:
    """Remap catchment raster from HydroIDs to 0-based catchment indices (cidx).

    Maps unknown HydroIDs (and source nodata -1) to -1. Logs a count of unknown HydroID pixels.
    """
    out = np.full(catch_hydroid.shape, -1, dtype=np.int32)
    unique_vals = np.unique(catch_hydroid)
    unknown_pixels = 0

    for val in unique_vals:
        if val == -1:
            continue
        cidx = hydroid_to_cidx.get(int(val))
        if cidx is not None:
            out[catch_hydroid == val] = cidx
        else:
            unknown_pixels += int(np.count_nonzero(catch_hydroid == val))

    if unknown_pixels > 0:
        logger.info("Remapped %d pixels with unknown HydroIDs to -1", unknown_pixels)

    return out
