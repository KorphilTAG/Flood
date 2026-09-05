"""HAND mapping from reach discharge to depth and velocity rasters."""
from __future__ import annotations

import dataclasses
from typing import Mapping
import numpy as np

from flood.engine.cube import HandCube
from flood.engine.rating import apply_n_scale, hyd_radius, stage_from_q, wet_area
from flood.interfaces import MemberFields, MIN_DEPTH_M


def map_member(
    cube: HandCube,
    q_by_feature: Mapping[int, float],
    n_scale: float = 1.0,
    with_velocity: bool = True,
) -> MemberFields:
    """Map reach discharges to depth and proxy velocity fields on the cube grid."""
    grid = cube.grid
    h = grid.height
    w = grid.width

    total_depth = np.full((h, w), np.nan, dtype=np.float32)
    total_velocity = np.full((h, w), np.nan, dtype=np.float32) if with_velocity else None

    clipped_dict: dict[int, bool] = {int(fid): False for fid in q_by_feature.keys()}

    for branch in cube.branches:
        rt = branch.rating
        if n_scale != 1.0:
            rt = dataclasses.replace(rt, q_cms=apply_n_scale(rt.q_cms, n_scale))

        n_catch = len(rt.feature_id)
        stage_lut = np.full(n_catch, np.nan, dtype=np.float32)
        v_reach_lut = np.full(n_catch, np.nan, dtype=np.float32)
        r_lut = np.full(n_catch, np.nan, dtype=np.float32)

        modeled_mask = (rt.lake_id == -999) & np.isin(rt.feature_id, list(q_by_feature.keys()))
        cidx_modeled = np.where(modeled_mask)[0]

        if len(cidx_modeled) > 0:
            fids = rt.feature_id[cidx_modeled]
            q_vec = np.array([float(q_by_feature[fid]) for fid in fids], dtype=np.float32)

            stages, clips = stage_from_q(rt, cidx_modeled, q_vec)
            stage_lut[cidx_modeled] = stages

            for fid, c in zip(fids, clips):
                if bool(c):
                    clipped_dict[int(fid)] = True

            if with_velocity:
                wa = wet_area(rt, cidx_modeled, stages)
                hr = hyd_radius(rt, cidx_modeled, stages)
                safe_wa = np.where(wa > 0, wa, 1.0)
                v_reach = np.where(wa > 0, q_vec / safe_wa, 0.0).astype(np.float32)
                v_reach_lut[cidx_modeled] = v_reach
                r_lut[cidx_modeled] = hr

        catch = branch.catch
        rem = branch.rem
        covered = catch >= 0
        c_valid = np.clip(catch, 0, None)

        stage_grid = np.where(covered, stage_lut[c_valid], np.nan)

        raw_depth = stage_grid - rem
        valid_depth = (
            covered
            & (~np.isnan(stage_grid))
            & (~np.isnan(rem))
            & (rem >= 0)
            & (raw_depth >= MIN_DEPTH_M)
        )
        branch_depth = np.where(covered, np.where(valid_depth, raw_depth, 0.0), np.nan).astype(np.float32)
        total_depth = np.fmax(total_depth, branch_depth)

        if with_velocity:
            v_reach_grid = np.where(covered, v_reach_lut[c_valid], np.nan)
            r_grid = np.where(covered, r_lut[c_valid], np.nan)

            has_vel = (
                covered
                & valid_depth
                & (~np.isnan(v_reach_grid))
                & (~np.isnan(r_grid))
                & (r_grid > 0)
            )
            safe_r = np.where(has_vel, r_grid, 1.0)
            ratio = np.where(has_vel, branch_depth / safe_r, 0.0)
            v_cell_raw = np.where(has_vel, v_reach_grid * (ratio ** (2.0 / 3.0)), 0.0)
            v_max = 3.0 * np.where(~np.isnan(v_reach_grid), v_reach_grid, 0.0)
            v_cell = np.clip(v_cell_raw, 0.0, v_max).astype(np.float32)
            branch_velocity = np.where(covered, np.where(valid_depth, v_cell, 0.0), np.nan).astype(np.float32)
            total_velocity = np.fmax(total_velocity, branch_velocity)

    if total_velocity is not None:
        total_velocity = np.where(total_depth == 0.0, 0.0, total_velocity).astype(np.float32)

    return MemberFields(
        depth=total_depth,
        velocity=total_velocity,
        clipped=clipped_dict,
    )
