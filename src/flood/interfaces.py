"""Frozen shared types for the physics engine. Do not edit after cycle C01."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol
import numpy as np
import pandas as pd

MEMBERS: tuple[str, str, str] = ("low", "mid", "high")
MEMBER_INDEX: dict[str, int] = {"low": 0, "mid": 1, "high": 2}
STEP_MINUTES: int = 5
MIN_DEPTH_M: float = 0.03
NODATA: float = -9999.0
TTE_THRESHOLDS_M: tuple[float, float, float] = (0.15, 0.30, 0.60)
RASTER_BANDS: tuple[str, ...] = ("depth_mid", "depth_low", "depth_high", "velocity_ms", "hazard_dv", "prob_inundated")
SOURCE_CODES: dict[int, str] = {
    0: "observed", 1: "nwm_analysis_scaled", 2: "mass_balance", 3: "nwm_analysis",
    4: "routed", 5: "forecast_trend", 6: "forecast_nwm_sr",
}
SOURCE_INDEX: dict[str, int] = {v: k for k, v in SOURCE_CODES.items()}

@dataclass(frozen=True)
class Grid:
    crs: str
    resolution_m: float
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]  # GDAL order a b c d e f
    bounds: tuple[float, float, float, float]  # xmin ymin xmax ymax

    @staticmethod
    def from_bounds(bounds: tuple[float, float, float, float], resolution_m: float = 10.0, crs: str = "EPSG:5070") -> "Grid":
        xmin, ymin, xmax, ymax = bounds
        w = round((xmax - xmin) / resolution_m); h = round((ymax - ymin) / resolution_m)
        return Grid(crs, resolution_m, w, h, (resolution_m, 0.0, xmin, 0.0, -resolution_m, ymax), bounds)

@dataclass(frozen=True)
class RatingTable:
    """Per-catchment rating arrays for one branch. Row i is catchment index cidx == i."""
    hydro_id: np.ndarray      # int64 [n]
    feature_id: np.ndarray    # int64 [n]
    lake_id: np.ndarray       # int64 [n], -999 means not a lake
    stream_order: np.ndarray  # int16 [n]
    length_km: np.ndarray     # float32 [n]
    slope: np.ndarray         # float32 [n]
    manning_n: np.ndarray     # float32 [n]
    stage_m: np.ndarray       # float32 [n, k]
    q_cms: np.ndarray         # float32 [n, k]
    wet_area_m2: np.ndarray   # float32 [n, k]
    hyd_radius_m: np.ndarray  # float32 [n, k]
    top_width_m: np.ndarray   # float32 [n, k]

@dataclass(frozen=True)
class BranchArrays:
    branch_id: int
    rem: np.ndarray    # float32 [height, width], metres, NaN nodata
    catch: np.ndarray  # int32 [height, width], cidx, -1 nodata
    rating: RatingTable

NETWORK_COLUMNS: tuple[str, ...] = (
    "feature_id", "to_feature_id", "stream_order", "levelpath_id", "length_m", "slope",
    "gauge_site", "in_aoi", "preferred_branch", "representative_cidx", "flowline_wkb",
)
GAUGE_COLUMNS: tuple[str, ...] = (
    "site", "feature_id", "role", "dem_adj_elevation_m", "gauge_altitude_m", "altitude_datum",
)

class ForcingView(Protocol):
    """Everything known at cutoff p. Series are indexed by tz-aware UTC DatetimeIndex, sorted."""
    p: datetime
    def obs_q(self, site: str) -> pd.Series: ...
    def obs_wse(self, site: str) -> pd.Series: ...
    def nwm_analysis(self, feature_id: int) -> pd.Series: ...
    def latest_short_range(self, feature_id: int) -> pd.Series: ...
    def qlat(self, feature_id: int, tau: datetime) -> float: ...
    def ratio(self, feature_id: int) -> float: ...

@dataclass
class RoutedSeries:
    p: datetime
    taus: np.ndarray        # datetime64[s] [T], ascending, includes p
    feature_ids: np.ndarray # int64 [R], same order as network rows
    q: np.ndarray           # float32 [3, R, T], member order MEMBERS
    source: np.ndarray      # int8 [R, T], SOURCE_CODES
    def index_of(self, t: datetime) -> int:
        arr = np.datetime64(t.replace(tzinfo=None), "s")
        i = int(np.searchsorted(self.taus, arr))
        if i >= len(self.taus) or self.taus[i] != arr:
            raise KeyError(f"{t} not in routed series")
        return i
    def at(self, t: datetime) -> np.ndarray:  # [3, R]
        return self.q[:, :, self.index_of(t)]

@dataclass
class MemberFields:
    depth: np.ndarray                 # float32 [H, W], 0 = dry, NaN = no branch coverage
    velocity: np.ndarray | None       # float32 [H, W] or None for non-mid members
    clipped: dict[int, bool] = field(default_factory=dict)  # feature_id -> clipped to top of rating

@dataclass
class StateArrays:
    p: datetime | None
    t: datetime
    depth_mid: np.ndarray
    depth_low: np.ndarray
    depth_high: np.ndarray
    velocity_ms: np.ndarray
    hazard_dv: np.ndarray
    prob_inundated: np.ndarray
    compute_ms: dict[str, int]

class TimeGridError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code
