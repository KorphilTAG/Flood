"""Cloud-Optimized GeoTIFF and PNG overlay raster writers."""
from __future__ import annotations

import io
from pathlib import Path
import tempfile
from affine import Affine
import numpy as np
from PIL import Image
import rasterio
import rasterio.warp
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

from flood.interfaces import Grid, MIN_DEPTH_M, NODATA, RASTER_BANDS, StateArrays

DEPTH_RAMP: list[tuple[float, str]] = [
    (0.03, "#bfe3ff"),
    (0.5, "#6fb3ff"),
    (1.0, "#2a7fff"),
    (2.0, "#0a4fc0"),
    (4.0, "#052a66"),
]


def write_depth_cog(path: Path | str, grid: Grid, arrays: StateArrays) -> Path:
    """Write multi-band Cloud-Optimized GeoTIFF with contract 1 bands and metadata.

    Bands in RASTER_BANDS order:
    1: depth_mid (m)
    2: depth_low (m)
    3: depth_high (m)
    4: velocity_ms (m/s)
    5: hazard_dv (m2/s)
    6: prob_inundated (fraction)
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    band_arrays = [
        arrays.depth_mid,
        arrays.depth_low,
        arrays.depth_high,
        arrays.velocity_ms,
        arrays.hazard_dv,
        arrays.prob_inundated,
    ]
    band_units = ["m", "m", "m", "m/s", "m2/s", "fraction"]

    data = np.stack(band_arrays, axis=0).astype(np.float32)
    data = np.where(np.isnan(data), NODATA, data)

    transform = Affine(*grid.transform)

    with tempfile.TemporaryDirectory() as td:
        tmp_tif = Path(td) / "temp_depth.tif"
        with rasterio.open(
            tmp_tif,
            "w",
            driver="GTiff",
            height=grid.height,
            width=grid.width,
            count=len(band_arrays),
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=NODATA,
        ) as dst:
            dst.write(data)
            dst.descriptions = tuple(RASTER_BANDS)
            for idx, u in enumerate(band_units, 1):
                dst.set_band_unit(idx, u)
                dst.update_tags(idx, units=u)

        profile = dict(cog_profiles.get("deflate"))
        profile["blockxsize"] = 256
        profile["blockysize"] = 256
        cog_translate(tmp_tif, out_path, profile, forward_band_tags=True, quiet=True)

    return out_path


def write_tte_cog(path: Path | str, grid: Grid, tte: np.ndarray) -> Path:
    """Write time-to-exceedance Cloud-Optimized GeoTIFF.

    Bands: tte_015, tte_030, tte_060 (units: min).
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    band_descriptions = ("tte_015", "tte_030", "tte_060")
    data = np.where(np.isnan(tte), NODATA, tte).astype(np.float32)
    transform = Affine(*grid.transform)

    with tempfile.TemporaryDirectory() as td:
        tmp_tif = Path(td) / "temp_tte.tif"
        with rasterio.open(
            tmp_tif,
            "w",
            driver="GTiff",
            height=grid.height,
            width=grid.width,
            count=3,
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=NODATA,
        ) as dst:
            dst.write(data)
            dst.descriptions = band_descriptions
            for idx in range(1, 4):
                dst.set_band_unit(idx, "min")
                dst.update_tags(idx, units="min")

        profile = dict(cog_profiles.get("deflate"))
        profile["blockxsize"] = 256
        profile["blockysize"] = 256
        cog_translate(tmp_tif, out_path, profile, forward_band_tags=True, quiet=True)

    return out_path


def render_overlay_png(
    array: np.ndarray,
    grid: Grid,
    max_px: int = 2048,
    ramp: list[tuple[float, str]] = DEPTH_RAMP,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """Render depth/hazard array to RGBA PNG reprojected to EPSG:3857."""
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

    rasterio.warp.reproject(
        source=src_arr,
        destination=dst_arr,
        src_transform=Affine(*grid.transform),
        src_crs=grid.crs,
        dst_transform=scaled_transform,
        dst_crs="EPSG:3857",
        resampling=rasterio.warp.Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )

    # Colour mapping
    thrs = [t for t, _ in ramp]
    rgbs = [tuple(int(c.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) for _, c in ramp]
    rs = [float(c[0]) for c in rgbs]
    gs = [float(c[1]) for c in rgbs]
    bs = [float(c[2]) for c in rgbs]

    valid = (dst_arr >= MIN_DEPTH_M) & (~np.isnan(dst_arr)) & (dst_arr > NODATA)
    v_safe = np.where(valid, dst_arr, thrs[0])
    v_clipped = np.clip(v_safe, thrs[0], thrs[-1])

    r = np.where(valid, np.interp(v_clipped, thrs, rs), 0.0)
    g = np.where(valid, np.interp(v_clipped, thrs, gs), 0.0)
    b = np.where(valid, np.interp(v_clipped, thrs, bs), 0.0)
    a = np.where(valid, 255.0, 0.0)

    rgba = np.stack([r, g, b, a], axis=-1).astype(np.uint8)

    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), bounds_3857
