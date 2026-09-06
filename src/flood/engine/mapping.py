"""HAND mapping from reach discharge to depth and velocity rasters.

Performance notes (fix-up after wave 2 measurements on the reference corridor, 17.2 Mcells):
- Every branch is processed only inside the bounding box of its covered cells
  (cells where the REM is not NaN). Levelpath branches cover a few percent of the
  grid each, so this removes most of the full-grid passes.
- Velocity is computed only on wet cells (typically 1 to 5 percent of the grid)
  with gather/scatter instead of full-grid power operations.
- Coverage means "the branch has terrain here" (REM not NaN). A covered cell whose
  catchment is unknown or unmodelled is dry (0), not nodata; nodata (NaN) is
  reserved for cells no branch covers at all, matching contract 1.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping
import numpy as np

from flood.engine.cube import HandCube
from flood.engine.rating import apply_n_scale, hyd_radius, stage_from_q, wet_area
from flood.interfaces import BranchArrays, MemberFields, MIN_DEPTH_M

# Keyed by the REM array's identity and storing the array itself, so a recycled id()
# after garbage collection cannot return another branch's window.
_WINDOW_CACHE: dict[int, tuple[np.ndarray, tuple[slice, slice] | None]] = {}


def branch_window(branch: BranchArrays) -> tuple[slice, slice] | None:
    """Row and column slices bounding the branch's covered cells, or None if it covers nothing.

    Cached by the identity of the REM array, which is stable for a loaded cube.
    """
    key = id(branch.rem)
    entry = _WINDOW_CACHE.get(key)
    if entry is not None and entry[0] is branch.rem:
        return entry[1]
    covered = ~np.isnan(branch.rem)
    rows = np.flatnonzero(covered.any(axis=1))
    cols = np.flatnonzero(covered.any(axis=0))
    win = None if rows.size == 0 else (slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1))
    _WINDOW_CACHE[key] = (branch.rem, win)
    return win


def branch_scale(n_scale: Any, branch_id: int) -> float | np.ndarray:
    """Resolve a scalar scale or a per-branch field (anything with scale_for_branch) for one branch."""
    if hasattr(n_scale, "scale_for_branch"):
        return n_scale.scale_for_branch(branch_id)
    if isinstance(n_scale, Mapping):
        return n_scale.get(int(branch_id), 1.0)
    return float(n_scale)


def _is_unit_scale(s: float | np.ndarray) -> bool:
    return np.ndim(s) == 0 and float(s) == 1.0


def map_member(
    cube: HandCube,
    q_by_feature: Mapping[int, float],
    n_scale: Any = 1.0,
    with_velocity: bool = True,
) -> MemberFields:
    """Map reach discharges to depth and proxy velocity fields on the cube grid.

    depth = stage(Q) - REM per catchment, zero where REM < 0 or depth < MIN_DEPTH_M,
    lake catchments excluded, branches mosaicked by per-cell maximum. Velocity is the
    contract 1 section 7 proxy on the mid member.
    """
    grid = cube.grid
    h, w = grid.height, grid.width

    total_depth = np.full((h, w), np.nan, dtype=np.float32)
    total_velocity = np.full((h, w), np.nan, dtype=np.float32) if with_velocity else None
    clipped_dict: dict[int, bool] = {int(fid): False for fid in q_by_feature.keys()}
    q_fids = np.fromiter((int(f) for f in q_by_feature.keys()), dtype=np.int64, count=len(q_by_feature))

    for branch in cube.branches:
        win = branch_window(branch)
        if win is None:
            continue
        rs, cs = win

        rt = branch.rating
        s = branch_scale(n_scale, branch.branch_id)
        if not _is_unit_scale(s):
            rt = dataclasses.replace(rt, q_cms=apply_n_scale(rt.q_cms, s))

        n_catch = len(rt.feature_id)
        stage_lut = np.full(n_catch, np.nan, dtype=np.float32)
        v_reach_lut = np.zeros(n_catch, dtype=np.float32)
        r_lut = np.zeros(n_catch, dtype=np.float32)

        modeled = (rt.lake_id == -999) & np.isin(rt.feature_id, q_fids)
        cidx_modeled = np.flatnonzero(modeled)
        if cidx_modeled.size:
            fids = rt.feature_id[cidx_modeled]
            q_vec = np.fromiter((float(q_by_feature[int(f)]) for f in fids), dtype=np.float32, count=fids.size)
            stages, clips = stage_from_q(rt, cidx_modeled, q_vec)
            stage_lut[cidx_modeled] = stages
            for fid in fids[np.asarray(clips, dtype=bool)]:
                clipped_dict[int(fid)] = True
            if with_velocity:
                wa = wet_area(rt, cidx_modeled, stages)
                r_lut[cidx_modeled] = hyd_radius(rt, cidx_modeled, stages)
                v_reach_lut[cidx_modeled] = np.where(wa > 0, q_vec / np.where(wa > 0, wa, 1.0), 0.0).astype(np.float32)

        rem_w = branch.rem[rs, cs]
        catch_w = branch.catch[rs, cs]
        covered = ~np.isnan(rem_w)

        # In-place arithmetic: on the full-grid branch these arrays are tens of MB each.
        depth_w = stage_lut[np.maximum(catch_w, 0)]          # stage per cell (NaN if unmodelled)
        depth_w[catch_w < 0] = np.nan
        np.subtract(depth_w, rem_w, out=depth_w)              # depth = stage - REM
        wet = depth_w >= MIN_DEPTH_M                          # NaN compares False
        wet &= rem_w >= 0

        branch_depth = depth_w                                 # reuse buffer
        branch_depth[~wet] = 0.0
        branch_depth[~covered] = np.nan
        np.fmax(total_depth[rs, cs], branch_depth, out=total_depth[rs, cs])

        if with_velocity:
            branch_vel = np.zeros(depth_w.shape, dtype=np.float32)
            wet_idx = np.flatnonzero(wet)
            if wet_idx.size:
                c_flat = catch_w.ravel()[wet_idx]
                v_reach = v_reach_lut[c_flat]
                r_val = r_lut[c_flat]
                d_val = branch_depth.ravel()[wet_idx]
                ok = r_val > 0
                v = np.zeros(wet_idx.size, dtype=np.float32)
                v[ok] = v_reach[ok] * np.power(d_val[ok] / r_val[ok], 2.0 / 3.0)
                v = np.minimum(np.maximum(v, 0.0), 3.0 * v_reach)
                branch_vel.ravel()[wet_idx] = v
            branch_vel[~covered] = np.nan
            np.fmax(total_velocity[rs, cs], branch_vel, out=total_velocity[rs, cs])

    if total_velocity is not None:
        total_velocity = np.where(total_depth == 0.0, 0.0, total_velocity).astype(np.float32)

    return MemberFields(depth=total_depth, velocity=total_velocity, clipped=clipped_dict)
