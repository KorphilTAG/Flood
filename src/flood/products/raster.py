"""Cloud-Optimized GeoTIFF and PNG overlay raster writers."""
from __future__ import annotations

import io
from pathlib import Path
from affine import Affine
import numpy as np
from PIL import Image
import rasterio
import rasterio.warp

from flood.interfaces import Grid, MIN_DEPTH_M, NODATA, RASTER_BANDS, StateArrays

DEPTH_RAMP: list[tuple[float, str]] = [
    (0.03, "#bfe3ff"),
    (0.5, "#6fb3ff"),
    (1.0, "#2a7fff"),
    (2.0, "#0a4fc0"),
    (4.0, "#052a66"),
]


def _write_cog(path: Path | str, grid: Grid, data: np.ndarray, descriptions: tuple[str, ...], units: tuple[str, ...]) -> Path:
    """Write a valid Cloud-Optimized GeoTIFF with GDAL's COG driver in one pass.

    DEFLATE level 1 with the floating-point predictor, 256 blocks, no overviews: about
    3x faster than writing a GeoTIFF and re-encoding it through cog_translate, and still
    a valid COG (cog_validate warns about missing overviews only). Overviews can be added
    in a batch step for the product UI if tiles at low zoom ever need them.
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.where(np.isnan(data), NODATA, data).astype(np.float32)
    with rasterio.open(
        out_path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=arr.shape[0],
        dtype="float32",
        crs=grid.crs,
        transform=Affine(*grid.transform),
        nodata=NODATA,
        compress="DEFLATE",
        level=1,
        predictor="YES",
        overviews="NONE",
        blocksize=256,
        bigtiff="IF_SAFER",
    ) as dst:
        dst.write(arr)
        dst.descriptions = tuple(descriptions)
        for idx, u in enumerate(units, 1):
            dst.set_band_unit(idx, u)
            dst.update_tags(idx, units=u)
    return out_path


def write_depth_cog(path: Path | str, grid: Grid, arrays: StateArrays) -> Path:
    """Write the contract 1 multi-band COG: depth_mid, depth_low, depth_high, velocity_ms, hazard_dv, prob_inundated."""
    data = np.stack(
        [arrays.depth_mid, arrays.depth_low, arrays.depth_high, arrays.velocity_ms, arrays.hazard_dv, arrays.prob_inundated],
        axis=0,
    )
    return _write_cog(path, grid, data, tuple(RASTER_BANDS), ("m", "m", "m", "m/s", "m2/s", "fraction"))


def write_tte_cog(path: Path | str, grid: Grid, tte: np.ndarray) -> Path:
    """Write the time-to-exceedance COG: tte_015, tte_030, tte_060 in minutes."""
    return _write_cog(path, grid, np.asarray(tte), ("tte_015", "tte_030", "tte_060"), ("min", "min", "min"))


def render_overlay_png(
    array: np.ndarray,
    grid: Grid,
    max_px: int = 2048,
    ramp: list[tuple[float, str]] = DEPTH_RAMP,
    smooth: bool = False,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """Render depth/hazard array to RGBA PNG reprojected to EPSG:3857.

    Default mode is the verifier's: cell-crisp, and when the output pixel is coarser than the
    grid it keeps the per-pixel maximum and dilates wet pixels by one so a one-cell river
    stays visible at corridor zoom.

    ``smooth=True`` is for draping on 3D terrain, where those choices read as blocks: it
    resamples bilinearly at every scale, never dilates, and anti-aliases the wet edge by
    blurring the wet mask into the alpha channel (interior stays opaque, the boundary is a
    one to two pixel ramp). Which cells are wet is unchanged: depth >= MIN_DEPTH_M.
    """
    dst_transform, dst_w, dst_h = rasterio.warp.calculate_default_transform(
        grid.crs, "EPSG:3857", grid.width, grid.height, *grid.bounds
    )
    longer = max(dst_w, dst_h)
    scale = max_px / longer if longer > 0 else 1.0
    out_w = max(1, round(dst_w * scale))
    out_h = max(1, round(dst_h * scale))

    scaled_transform = dst_transform @ Affine.scale(dst_w / out_w, dst_h / out_h)

    xmin = scaled_transform.c
    ymax = scaled_transform.f
    xmax = xmin + out_w * scaled_transform.a
    ymin = ymax + out_h * scaled_transform.e
    bounds_3857 = (float(xmin), float(ymin), float(xmax), float(ymax))

    src_arr = np.where(array == NODATA, np.nan, array).astype(np.float32)
    dst_arr = np.full((out_h, out_w), np.nan, dtype=np.float32)

    # When the output pixel is coarser than the grid, keep the maximum depth inside each
    # output pixel instead of averaging: bilinear resampling of a river one or two cells
    # wide onto 30 m pixels blurs it below MIN_DEPTH_M and it vanishes at corridor zoom.
    out_px_m = abs(scaled_transform.a)
    coarse = (out_px_m > grid.resolution_m * 1.5) and not smooth
    rasterio.warp.reproject(
        source=src_arr,
        destination=dst_arr,
        src_transform=Affine(*grid.transform),
        src_crs=grid.crs,
        dst_transform=scaled_transform,
        dst_crs="EPSG:3857",
        resampling=rasterio.warp.Resampling.max if coarse else rasterio.warp.Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    if coarse:
        # Dilate wet pixels by one so a one-pixel river stays legible; the legend still
        # shows the true maximum depth of the underlying cells.
        from scipy.ndimage import maximum_filter

        filled = np.where(np.isnan(dst_arr), -1.0, dst_arr).astype(np.float32)
        dilated = maximum_filter(filled, size=3)
        dst_arr = np.where(dilated >= MIN_DEPTH_M, dilated, dst_arr).astype(np.float32)

    # Colour mapping, done only on the pixels that get paint: wet cells are a few percent
    # of the corridor, and the full-grid float intermediates were the memory peak.
    thrs = np.asarray([t for t, _ in ramp], dtype=np.float32)
    rgbs = np.asarray(
        [[int(c.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)] for _, c in ramp], dtype=np.float32
    )

    valid = (dst_arr >= MIN_DEPTH_M) & (~np.isnan(dst_arr)) & (dst_arr > NODATA)
    rgba = np.zeros((out_h, out_w, 4), dtype=np.uint8)

    if smooth:
        from scipy.ndimage import gaussian_filter

        # Coverage-style anti-aliasing: blur the wet mask, then remap so pixels well inside
        # stay fully opaque, pixels well outside stay fully transparent, and only the
        # boundary carries partial alpha.
        blurred = gaussian_filter(valid.astype(np.float32), sigma=0.7, truncate=3.0)
        alpha = np.clip((blurred - 0.15) / 0.7, 0.0, 1.0)
        paint = alpha > 0.0
        # Exterior boundary pixels have no depth of their own: give them the shallowest colour.
        vals = np.where(valid, dst_arr, thrs[0])[paint]
    else:
        alpha = valid.astype(np.float32)
        paint = valid
        vals = dst_arr[paint]

    vals = np.clip(vals, thrs[0], thrs[-1])
    for ch in range(3):
        rgba[..., ch][paint] = np.rint(np.interp(vals, thrs, rgbs[:, ch])).astype(np.uint8)
    rgba[..., 3] = np.rint(alpha * 255.0).astype(np.uint8)

    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), bounds_3857
