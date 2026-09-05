"""HAND FIM data ingest and cube preparation."""
from __future__ import annotations

import logging
from pathlib import Path
import uuid
import httpx
import numpy as np
import rasterio
import rasterio.windows
from flood.interfaces import Grid

logger = logging.getLogger("flood.ingest.hand")

HAND_BASE_URL = "https://ciroh-owp-hand-fim.s3.amazonaws.com"


def get_huc_base_url(fim_version: str, huc8: str) -> str:
    """Return base S3 URL for a given FIM version and HUC8."""
    return f"{HAND_BASE_URL}/hand_fim_{fim_version.replace('.', '_')}/{huc8}"


def get_huc_file_url(fim_version: str, huc8: str, filename: str) -> str:
    """Return download URL for a HUC-level file."""
    return f"{get_huc_base_url(fim_version, huc8)}/{filename}"


def get_branch_file_url(
    fim_version: str, huc8: str, branch_id: int | str, filename: str
) -> str:
    """Return download URL for a branch-level file."""
    return f"{get_huc_base_url(fim_version, huc8)}/branches/{branch_id}/{filename}"


def get_branch_rem_url(fim_version: str, huc8: str, branch_id: int | str) -> str:
    """Return download URL for branch REM raster."""
    return get_branch_file_url(
        fim_version, huc8, branch_id, f"rem_zeroed_masked_{branch_id}.tif"
    )


def get_branch_catch_url(fim_version: str, huc8: str, branch_id: int | str) -> str:
    """Return download URL for branch catchment raster."""
    return get_branch_file_url(
        fim_version,
        huc8,
        branch_id,
        f"gw_catchments_reaches_filtered_addedAttributes_{branch_id}.tif",
    )


def download(
    url: str,
    dest: Path | str,
    expected_size: int | None = None,
    force: bool = False,
) -> Path:
    """Download a file idempotently.

    Skips download if dest exists and its size matches expected_size or the
    Content-Length from a HEAD request. Otherwise streams to a temporary file
    and atomically renames.
    """
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        if dest_path.exists() and not force:
            file_size = dest_path.stat().st_size
            if expected_size is not None and file_size == expected_size:
                logger.info("Skipping download (matches expected size %d): %s", expected_size, dest_path.name)
                return dest_path

            try:
                head_resp = client.head(url)
                if head_resp.status_code == 200:
                    cl_header = head_resp.headers.get("content-length")
                    if cl_header is not None and file_size == int(cl_header):
                        logger.info(
                            "Skipping download (matches Content-Length %s): %s",
                            cl_header,
                            dest_path.name,
                        )
                        return dest_path
            except Exception as e:
                logger.debug("HEAD request failed for %s (%s); will attempt GET", url, e)

        # Download to temporary file and atomically rename
        temp_dest = dest_path.with_name(f"{dest_path.name}.tmp.{uuid.uuid4().hex[:8]}")
        try:
            with client.stream("GET", url) as stream_resp:
                stream_resp.raise_for_status()
                with open(temp_dest, "wb") as f:
                    for chunk in stream_resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
            temp_dest.replace(dest_path)
            logger.info("Downloaded %s (%d bytes)", dest_path.name, dest_path.stat().st_size)
        finally:
            if temp_dest.exists():
                temp_dest.unlink(missing_ok=True)

    return dest_path


def branch_intersects(
    branch_bounds: tuple[float, float, float, float],
    grid_bounds: tuple[float, float, float, float],
) -> bool:
    """Check if branch bounding box intersects grid bounding box (both xmin, ymin, xmax, ymax)."""
    b_minx, b_miny, b_maxx, b_maxy = branch_bounds
    g_minx, g_miny, g_maxx, g_maxy = grid_bounds
    return (b_maxx > g_minx) and (b_minx < g_maxx) and (b_maxy > g_miny) and (b_miny < g_maxy)


def _validate_raster(src: rasterio.DatasetReader, path_name: str) -> None:
    """Validate that raster is EPSG:5070, 10 m resolution, and 10 m aligned."""
    if src.crs is None or src.crs.to_epsg() != 5070:
        raise ValueError(f"Expected EPSG:5070 for {path_name}, got {src.crs}")

    res_x, res_y = src.res
    if abs(res_x - 10.0) > 1e-4 or abs(res_y - 10.0) > 1e-4:
        raise ValueError(f"Expected 10m resolution for {path_name}, got ({res_x}, {res_y})")

    left, bottom, right, top = src.bounds
    for coord in (left, bottom, right, top):
        if abs(round(coord / 10.0) * 10.0 - coord) > 1e-4:
            raise ValueError(f"Coordinate {coord} in {path_name} is not aligned to multiple of 10")


def clip_branch(
    rem_path: Path | str,
    catch_path: Path | str,
    grid: Grid,
) -> tuple[np.ndarray, np.ndarray]:
    """Clip branch REM and catchment rasters to the common grid.

    Returns:
        (rem_f32, catch_hydroid_i32) with shape (grid.height, grid.width).
        REM in metres (int16 mm / 1000), NaN where source nodata 32767 or outside.
        Catchments -1 where source nodata 0 or outside.
    """
    with rasterio.open(rem_path) as rem_src, rasterio.open(catch_path) as catch_src:
        _validate_raster(rem_src, str(rem_path))
        _validate_raster(catch_src, str(catch_path))

        win = rasterio.windows.from_bounds(*grid.bounds, transform=rem_src.transform)
        win = win.round_offsets()

        # Read REM
        rem_nodata = rem_src.nodata if rem_src.nodata is not None else 32767
        rem_raw = rem_src.read(
            1,
            window=win,
            boundless=True,
            fill_value=rem_nodata,
            out_shape=(grid.height, grid.width),
        )
        assert rem_raw.shape == (grid.height, grid.width), (
            f"REM shape {rem_raw.shape} does not match grid ({grid.height}, {grid.width})"
        )

        rem_f32 = rem_raw.astype(np.float32) / 1000.0
        rem_f32[(rem_raw == 32767) | (rem_raw == rem_nodata)] = np.nan

        # Read Catchment
        catch_nodata = catch_src.nodata if catch_src.nodata is not None else 0
        catch_raw = catch_src.read(
            1,
            window=win,
            boundless=True,
            fill_value=catch_nodata,
            out_shape=(grid.height, grid.width),
        )
        assert catch_raw.shape == (grid.height, grid.width), (
            f"Catchment shape {catch_raw.shape} does not match grid ({grid.height}, {grid.width})"
        )

        catch_hydroid_i32 = catch_raw.astype(np.int32)
        catch_hydroid_i32[(catch_raw == 0) | (catch_raw == catch_nodata)] = -1

    return rem_f32, catch_hydroid_i32


def prep_hand(
    scenario: Scenario,
    data_dir: Path | str = "data",
    force: bool = False,
) -> HandCube:
    """Download HAND FIM artifacts and build a HandCube for the scenario.

    Args:
        scenario: Scenario specification.
        data_dir: Path to base data directory.
        force: If True, re-download and re-process existing files.

    Returns:
        HandCube instance saved to {data_dir}/cube/{scenario_id}.
    """
    # Local imports of cycle C02 components
    import geopandas as gpd
    import pandas as pd
    from flood.contracts.models import Scenario
    from flood.engine.cube import HandCube
    from flood.ingest.hydrotable import build_rating, remap_catchments
    from flood.ingest.network import build_gauges, build_network
    from flood.interfaces import BranchArrays

    data_path = Path(data_dir)
    fim_version = scenario.hydrology.fim_version
    grid = Grid.from_bounds(
        tuple(scenario.hydrology.aoi.bounds),
        resolution_m=10.0,
        crs=scenario.hydrology.aoi.crs,
    )

    all_branches: list[BranchArrays] = []
    all_branch_specs: list[tuple[str, int]] = []
    all_hydrotables: list[pd.DataFrame] = []
    all_streams: list[gpd.GeoDataFrame] = []
    all_usgs_elev: list[pd.DataFrame] = []

    for huc8 in scenario.hydrology.huc8:
        huc_dir = data_path / "hand" / huc8
        huc_dir.mkdir(parents=True, exist_ok=True)

        # 1. branch_ids.csv
        branch_ids_url = get_huc_file_url(fim_version, huc8, "branch_ids.csv")
        branch_ids_path = download(branch_ids_url, huc_dir / "branch_ids.csv", force=force)
        branch_ids_df = pd.read_csv(
            branch_ids_path,
            header=None,
            names=["huc8", "branch_id"],
            dtype={"huc8": str, "branch_id": int},
        )
        logger.info("Loaded %s: %d branches", branch_ids_path.name, len(branch_ids_df))
        for bid in branch_ids_df["branch_id"].unique():
            all_branch_specs.append((huc8, int(bid)))

        # 2. hydrotable (prefer parquet, fallback to CSV)
        ht_parquet_url = get_huc_file_url(fim_version, huc8, "hydrotable.parquet")
        ht_parquet_path = huc_dir / "hydrotable.parquet"
        ht_csv_url = get_huc_file_url(fim_version, huc8, "hydrotable.csv")
        ht_csv_path = huc_dir / "hydrotable.csv"
        ht_df = None

        try:
            download(ht_parquet_url, ht_parquet_path, force=force)
            candidate_df = pd.read_parquet(ht_parquet_path)
            if isinstance(candidate_df.index, pd.MultiIndex) or "HydroID" in candidate_df.index.names:
                candidate_df = candidate_df.reset_index()
            required_cols = {"HydroID", "branch_id", "feature_id", "stage", "discharge_cms", "LENGTHKM"}
            if required_cols.issubset(candidate_df.columns):
                ht_df = candidate_df
                logger.info("Loaded %s: %d rows", ht_parquet_path.name, len(ht_df))
            else:
                logger.info(
                    "hydrotable.parquet missing required columns %s; falling back to hydrotable.csv",
                    required_cols - set(candidate_df.columns),
                )
        except Exception as e:
            logger.info("hydrotable.parquet not available (%s); trying hydrotable.csv", e)

        if ht_df is None:
            download(ht_csv_url, ht_csv_path, force=force)
            ht_df = pd.read_csv(
                ht_csv_path,
                dtype={"HydroID": "int64", "branch_id": "int64", "feature_id": "int64", "LakeID": "int64"},
                low_memory=False,
            )
            if isinstance(ht_df.index, pd.MultiIndex) or "HydroID" in ht_df.index.names:
                ht_df = ht_df.reset_index()
            logger.info("Loaded %s: %d rows", ht_csv_path.name, len(ht_df))

        all_hydrotables.append(ht_df)

        # 3. nwm_subset_streams_levelPaths.gpkg
        streams_url = get_huc_file_url(fim_version, huc8, "nwm_subset_streams_levelPaths.gpkg")
        streams_path = download(streams_url, huc_dir / "nwm_subset_streams_levelPaths.gpkg", force=force)
        streams_gdf = gpd.read_file(streams_path)
        logger.info("Loaded %s: %d reaches", streams_path.name, len(streams_gdf))
        all_streams.append(streams_gdf)

        # 4. usgs_elev_table.csv
        elev_url = get_huc_file_url(fim_version, huc8, "usgs_elev_table.csv")
        elev_path = download(elev_url, huc_dir / "usgs_elev_table.csv", force=force)
        elev_df = pd.read_csv(elev_path, dtype={"location_id": str})
        logger.info("Loaded %s: %d rows", elev_path.name, len(elev_df))
        all_usgs_elev.append(elev_df)

        # 5. nwm_lakes_proj_subset.gpkg (optional/per spec)
        lakes_url = get_huc_file_url(fim_version, huc8, "nwm_lakes_proj_subset.gpkg")
        try:
            download(lakes_url, huc_dir / "nwm_lakes_proj_subset.gpkg", force=force)
            logger.info("Loaded nwm_lakes_proj_subset.gpkg")
        except Exception as e:
            logger.warning("Could not download nwm_lakes_proj_subset.gpkg: %s", e)

    # Combine HUC dataframes
    combined_hydrotable = pd.concat(all_hydrotables, ignore_index=True)
    combined_streams = pd.concat(all_streams, ignore_index=True).drop_duplicates(subset=["ID"])
    combined_usgs_elev = pd.concat(all_usgs_elev, ignore_index=True)

    # Process branches
    for huc8, b in all_branch_specs:
        b_dir = data_path / "hand" / huc8 / "branches" / str(b)
        rem_dest = b_dir / f"rem_zeroed_masked_{b}.tif"
        catch_dest = b_dir / f"gw_catchments_reaches_filtered_addedAttributes_{b}.tif"

        rem_url = get_branch_rem_url(fim_version, huc8, b)
        catch_url = get_branch_catch_url(fim_version, huc8, b)

        download(rem_url, rem_dest, force=force)
        download(catch_url, catch_dest, force=force)

        # Check intersection
        with rasterio.open(rem_dest) as src:
            branch_bounds = src.bounds

        if not branch_intersects(branch_bounds, grid.bounds):
            logger.info("Branch %s is disjoint from AOI; omitting", b)
            continue

        rem_f32, catch_hydroid_i32 = clip_branch(rem_dest, catch_dest, grid)
        rating_table, hydroid_to_cidx = build_rating(combined_hydrotable, b)
        catch_cidx = remap_catchments(catch_hydroid_i32, hydroid_to_cidx)

        branch_arrays = BranchArrays(
            branch_id=b,
            rem=rem_f32,
            catch=catch_cidx,
            rating=rating_table,
        )
        all_branches.append(branch_arrays)
        logger.info(
            "Branch %s added to cube (REM shape %s, %d catchments)",
            b,
            rem_f32.shape,
            len(rating_table.hydro_id),
        )

    network_df = build_network(combined_streams, combined_hydrotable, scenario, grid)
    logger.info("Built network: %d reaches", len(network_df))

    gauges_df = build_gauges(combined_usgs_elev, scenario)
    logger.info("Built gauges: %d gauges", len(gauges_df))

    meta = {
        "source": "hand_fim",
        "fim_version": fim_version,
        "scenario_id": scenario.scenario_id,
        "huc8": scenario.hydrology.huc8,
    }
    cube = HandCube(
        grid=grid,
        branches=all_branches,
        network=network_df,
        gauges=gauges_df,
        meta=meta,
    )
    cube_dir = data_path / "cube" / scenario.scenario_id
    cube.save(cube_dir)
    logger.info("HandCube successfully saved to %s", cube_dir)
    return cube
