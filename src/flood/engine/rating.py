"""Rating table lookups and hydraulic geometry calculations."""
from __future__ import annotations

import dataclasses
import numpy as np
from flood.interfaces import RatingTable


def apply_n_scale(q: np.ndarray | float, s: float) -> np.ndarray | float:
    """Apply Manning's n roughness scale: returns q / s."""
    return q / s


def _interp_rowwise(
    x_table: np.ndarray,
    y_table: np.ndarray,
    cidx: np.ndarray,
    x_query: np.ndarray,
) -> np.ndarray:
    """Vectorised linear interpolation of y from x for each row specified by cidx."""
    x_mat = x_table[cidx]  # [M, K]
    y_mat = y_table[cidx]  # [M, K]
    x = x_query.astype(np.float32)  # [M]
    M, K = x_mat.shape

    idx = np.sum(x_mat <= x[:, None], axis=1) - 1
    idx = np.clip(idx, 0, K - 2)

    rows = np.arange(M)
    x0 = x_mat[rows, idx]
    x1 = x_mat[rows, idx + 1]
    y0 = y_mat[rows, idx]
    y1 = y_mat[rows, idx + 1]

    dx = x1 - x0
    frac = np.where(dx > 0, (x - x0) / dx, 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    y = y0 + frac * (y1 - y0)

    # Clamp bounds
    y = np.where(x <= x_mat[:, 0], y_mat[:, 0], y)
    y = np.where(x >= x_mat[:, -1], y_mat[:, -1], y)
    return y.astype(np.float32)


def stage_from_q(
    rt: RatingTable,
    cidx: np.ndarray,
    q: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised linear interpolation of stage from discharge per catchment row.

    q above the top row returns top stage and clipped=True.
    q <= 0 returns stage 0 and clipped=False.
    """
    cidx_arr = np.asarray(cidx)
    q_arr = np.asarray(q, dtype=np.float32)

    cidx_1d = np.atleast_1d(cidx_arr).astype(np.int64)
    q_1d = np.atleast_1d(q_arr)

    q_mat = rt.q_cms[cidx_1d]
    stage_mat = rt.stage_m[cidx_1d]
    q_top = q_mat[:, -1]

    stage_interp = _interp_rowwise(rt.q_cms, rt.stage_m, cidx_1d, q_1d)

    clipped_1d = q_1d > q_top
    stage_1d = np.where(clipped_1d, stage_mat[:, -1], stage_interp)

    stage_1d = np.where(q_1d <= 0, 0.0, stage_1d)
    clipped_1d = np.where(q_1d <= 0, False, clipped_1d)

    stage_out = stage_1d.reshape(cidx_arr.shape)
    clipped_out = clipped_1d.reshape(cidx_arr.shape)
    return stage_out, clipped_out


def wet_area(rt: RatingTable, cidx: np.ndarray, stage: np.ndarray) -> np.ndarray:
    """Interpolate wetted area (m2) from stage per catchment row."""
    cidx_arr = np.asarray(cidx)
    stage_arr = np.asarray(stage, dtype=np.float32)
    cidx_1d = np.atleast_1d(cidx_arr).astype(np.int64)
    stage_1d = np.atleast_1d(stage_arr)
    res_1d = _interp_rowwise(rt.stage_m, rt.wet_area_m2, cidx_1d, stage_1d)
    return res_1d.reshape(cidx_arr.shape)


def hyd_radius(rt: RatingTable, cidx: np.ndarray, stage: np.ndarray) -> np.ndarray:
    """Interpolate hydraulic radius (m) from stage per catchment row."""
    cidx_arr = np.asarray(cidx)
    stage_arr = np.asarray(stage, dtype=np.float32)
    cidx_1d = np.atleast_1d(cidx_arr).astype(np.int64)
    stage_1d = np.atleast_1d(stage_arr)
    res_1d = _interp_rowwise(rt.stage_m, rt.hyd_radius_m, cidx_1d, stage_1d)
    return res_1d.reshape(cidx_arr.shape)


def top_width(rt: RatingTable, cidx: np.ndarray, stage: np.ndarray) -> np.ndarray:
    """Interpolate top width (m) from stage per catchment row."""
    cidx_arr = np.asarray(cidx)
    stage_arr = np.asarray(stage, dtype=np.float32)
    cidx_1d = np.atleast_1d(cidx_arr).astype(np.int64)
    stage_1d = np.atleast_1d(stage_arr)
    res_1d = _interp_rowwise(rt.stage_m, rt.top_width_m, cidx_1d, stage_1d)
    return res_1d.reshape(cidx_arr.shape)


def celerity(rt: RatingTable, cidx: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Wave celerity dQ/dA by central differences evaluated at q, clipped to [0.1, 10.0]."""
    cidx_arr = np.asarray(cidx)
    q_arr = np.asarray(q, dtype=np.float32)
    cidx_1d = np.atleast_1d(cidx_arr).astype(np.int64)
    q_1d = np.atleast_1d(q_arr)

    q_mat = rt.q_cms[cidx_1d]
    area_mat = rt.wet_area_m2[cidx_1d]
    M, K = q_mat.shape

    dq = np.empty_like(q_mat)
    da = np.empty_like(area_mat)

    dq[:, 1:-1] = q_mat[:, 2:] - q_mat[:, :-2]
    da[:, 1:-1] = area_mat[:, 2:] - area_mat[:, :-2]

    dq[:, 0] = q_mat[:, 1] - q_mat[:, 0]
    da[:, 0] = area_mat[:, 1] - area_mat[:, 0]
    dq[:, -1] = q_mat[:, -1] - q_mat[:, -2]
    da[:, -1] = area_mat[:, -1] - area_mat[:, -2]

    c_table = np.where(da > 0, dq / da, 0.1).astype(np.float32)
    c_interp = _interp_rowwise(q_mat, c_table, np.arange(M), q_1d)
    c_clipped = np.clip(c_interp, 0.1, 10.0).astype(np.float32)
    return c_clipped.reshape(cidx_arr.shape)
