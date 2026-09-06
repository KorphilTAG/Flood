"""Pydantic v2 models mirroring JSON Schema contracts."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

UTC_TIMESTAMP_REGEX = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
SLUG_REGEX = r"^[a-z0-9][a-z0-9-]{2,63}$"
LAYER_ID_REGEX = r"^[a-z][a-z0-9_]{0,31}$"
FEATURE_REF_REGEX = r"^[a-z][a-z0-9_]{0,31}:[A-Za-z0-9_.-]{1,64}$"
REACH_REF_REGEX = r"^reach:[0-9]{1,12}$"
GAUGE_REF_REGEX = r"^gauge:[0-9]{8,15}$"
USGS_SITE_REGEX = r"^[0-9]{8,15}$"
HUC8_REGEX = r"^[0-9]{8}$"
FIM_VERSION_REGEX = r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$"
SEMVER_REGEX = r"^[0-9]+\.[0-9]+\.[0-9]+$"
SHA256_REGEX = r"^sha256:[0-9a-f]{64}$"
ID_32_REGEX = r"^[a-z0-9_-]{1,32}$"

MemberType = Literal["low", "mid", "high"]
SourceKindType = Literal[
    "observed",
    "nwm_analysis_scaled",
    "mass_balance",
    "nwm_analysis",
    "routed",
    "forecast_trend",
    "forecast_nwm_sr",
]


class BaseContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UsgsContinuousSource(BaseContractModel):
    type: Literal["usgs_continuous"] = "usgs_continuous"
    availability_latency_min: int = Field(ge=0)
    sites: list[Annotated[str, Field(pattern=USGS_SITE_REGEX)]] = Field(min_length=1)
    parameters: list[Literal["00060", "00065"]] = Field(default=["00060", "00065"])


class NwmAnalysisAssimSource(BaseContractModel):
    type: Literal["nwm_analysis_assim"] = "nwm_analysis_assim"
    availability_latency_min: int = Field(ge=0)


class NwmShortRangeSource(BaseContractModel):
    type: Literal["nwm_short_range"] = "nwm_short_range"
    availability_latency_min: int = Field(ge=0)
    max_lead_hours: int = Field(ge=1, le=18)


class ScriptedSource(BaseContractModel):
    type: Literal["scripted"] = "scripted"
    path: str
    availability_latency_min: int = Field(default=0, ge=0)


ForcingSource = Annotated[
    Union[UsgsContinuousSource, NwmAnalysisAssimSource, NwmShortRangeSource, ScriptedSource],
    Field(discriminator="type"),
]


class StateEstimationConfig(BaseContractModel):
    bias_correction: Literal["none", "nearest_gauge_ratio"]
    use_junction_inferences: bool
    ratio_clamp: list[float] = Field(default=[0.2, 10.0], min_length=2, max_length=2)


class BoundaryMembers(BaseContractModel):
    low: float = Field(ge=0)
    mid: float = Field(ge=0)
    high: float = Field(ge=0)


class BoundaryForecastConfig(BaseContractModel):
    method: Literal["persistence", "trend_relax", "nwm_short_range", "blend"]
    members: BoundaryMembers
    relax_minutes: int = Field(default=60, ge=1)
    trend_window_minutes: int = Field(default=30, ge=5)


class RoutingConfig(BaseContractModel):
    method: Literal["none", "muskingum_cunge"]
    dt_minutes: float = Field(default=1.0, gt=0, le=5)


class RoughnessConfig(BaseContractModel):
    manning_n_scale: float = Field(default=1.0, gt=0)
    # Fit a scale per scenario gauge from observed discharge and gauge height and propagate
    # it along the network; manning_n_scale remains the default for uncalibrated stretches.
    gauge_calibration: bool = False


class GaugeOutageOverride(BaseContractModel):
    type: Literal["gauge_outage"] = "gauge_outage"
    gauge_ref: Annotated[str, Field(pattern=GAUGE_REF_REGEX)]
    from_: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX, alias="from")]
    to: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)] | None = None


class ReachScaleOverride(BaseContractModel):
    type: Literal["reach_scale"] = "reach_scale"
    reach_ref: Annotated[str, Field(pattern=REACH_REF_REGEX)]
    factor: float = Field(ge=0)
    from_: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX, alias="from")]
    to: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)] | None = None


ScenarioOverride = Annotated[
    Union[GaugeOutageOverride, ReachScaleOverride],
    Field(discriminator="type"),
]


class ForcingConfig(BaseContractModel):
    sources: list[ForcingSource] = Field(min_length=1)
    state_estimation: StateEstimationConfig
    boundary_forecast: BoundaryForecastConfig
    routing: RoutingConfig
    roughness: RoughnessConfig | None = None
    scenario_overrides: list[ScenarioOverride] = Field(default_factory=list)


class AoiConfig(BaseContractModel):
    crs: Literal["EPSG:5070"] = "EPSG:5070"
    bounds: list[float] = Field(min_length=4, max_length=4)


class RecordConfig(BaseContractModel):
    start: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    end: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]


class GaugeConfig(BaseContractModel):
    site: Annotated[str, Field(pattern=USGS_SITE_REGEX)]
    name: str | None = None
    feature_id: int = Field(ge=1)
    role: Literal["boundary", "interior", "validation_only"]


class JunctionInference(BaseContractModel):
    label: str
    inferred_reach: int = Field(ge=1)
    downstream_gauge: Annotated[str, Field(pattern=USGS_SITE_REGEX)]
    subtract_gauges: list[Annotated[str, Field(pattern=USGS_SITE_REGEX)]] = Field(default_factory=list)
    travel_time_minutes: int = Field(ge=0)


class HydrologyConfig(BaseContractModel):
    huc8: list[Annotated[str, Field(pattern=HUC8_REGEX)]] = Field(min_length=1)
    fim_version: Annotated[str, Field(pattern=FIM_VERSION_REGEX)]
    aoi: AoiConfig
    record: RecordConfig
    gauges: list[GaugeConfig] = Field(min_length=1)
    junction_inferences: list[JunctionInference] = Field(default_factory=list)


class ImpactConfig(BaseContractModel):
    impassable_depth_m: float | None = Field(default=None, ge=0)
    threatened_depth_m: float | None = Field(default=None, ge=0)
    hazard_dv_limit: float | None = Field(default=None, ge=0)


class EgressConfig(BaseContractModel):
    routes_layer: Annotated[str, Field(pattern=LAYER_ID_REGEX)]
    join_field: str = Field(min_length=1)


class ExposureLayer(BaseContractModel):
    layer_id: Annotated[str, Field(pattern=LAYER_ID_REGEX)]
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    id_field: str = Field(min_length=1)
    geometry: Literal["point", "line", "polygon"]
    attributes: list[str] = Field(default_factory=list)
    impact: ImpactConfig | None = None
    egress: EgressConfig | None = None

    @field_validator("layer_id")
    @classmethod
    def check_layer_id_not_reserved(cls, v: str) -> str:
        if v in ("reach", "gauge", "aar"):
            raise ValueError(f"layer_id '{v}' is reserved")
        return v


class DecisionPoint(BaseContractModel):
    id: Annotated[str, Field(pattern=ID_32_REGEX)]
    t: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    label: str = Field(min_length=1)
    prompt: str | None = None
    reference_ids: list[Annotated[str, Field(pattern=FEATURE_REF_REGEX)]] = Field(default_factory=list)


class LastKnownPosition(BaseContractModel):
    id: Annotated[str, Field(pattern=ID_32_REGEX)]
    t: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    note: str | None = None


class Scenario(BaseContractModel):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: Annotated[str, Field(pattern=SLUG_REGEX)]
    name: str = Field(min_length=1)
    description: str | None = None
    timezone: str
    hydrology: HydrologyConfig
    forcing_defaults: ForcingConfig
    exposure_layers: list[ExposureLayer] = Field(default_factory=list)
    decision_points: list[DecisionPoint] = Field(default_factory=list)
    last_known_positions: list[LastKnownPosition] = Field(default_factory=list)

    # Runtime metadata attached by load_scenario
    path: Path | None = Field(default=None, exclude=True)
    base_dir: Path | None = Field(default=None, exclude=True)

    def exposure_layer_sources(self) -> list[Path]:
        base = self.base_dir if self.base_dir is not None else Path.cwd()
        return [(base / layer.source).resolve() for layer in self.exposure_layers]


# Run Manifest models
class ManifestScenario(BaseContractModel):
    scenario_id: Annotated[str, Field(pattern=SLUG_REGEX)]
    name: str
    huc8: list[Annotated[str, Field(pattern=HUC8_REGEX)]] = Field(min_length=1)
    fim_version: Annotated[str, Field(pattern=FIM_VERSION_REGEX)]
    record_start: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    record_end: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    timezone: str


class ManifestGrid(BaseContractModel):
    crs: Literal["EPSG:5070"] = "EPSG:5070"
    resolution_m: float = Field(gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    transform: list[float] = Field(min_length=6, max_length=6)
    bounds: list[float] = Field(min_length=4, max_length=4)


class ManifestTime(BaseContractModel):
    step_minutes: int = Field(ge=1)
    max_horizon_minutes: int = Field(ge=0)


class ManifestForcing(BaseContractModel):
    config: ForcingConfig
    config_hash: Annotated[str, Field(pattern=SHA256_REGEX)]


class ManifestProducts(BaseContractModel):
    raster: str
    reaches: str
    time_to_exceedance: str
    gauges: str
    hindsight_raster: str
    hindsight_reaches: str


class RunManifest(BaseContractModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Annotated[str, Field(pattern=SLUG_REGEX)]
    created_at: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    engine_version: Annotated[str, Field(pattern=SEMVER_REGEX)]
    mode: Literal["replay", "live"]
    scenario: ManifestScenario
    grid: ManifestGrid
    time: ManifestTime
    members: list[MemberType] = Field(min_length=3, max_length=3)
    forcing: ManifestForcing
    products: ManifestProducts
    limitations: list[str] = Field(min_length=1)


# Reach row model
class ReachRow(BaseContractModel):
    reach_ref: Annotated[str, Field(pattern=REACH_REF_REGEX)]
    feature_id: int = Field(ge=1)
    levelpath_id: int = Field(ge=0)
    stream_order: int = Field(ge=1, le=12)
    gauge_ref: Annotated[str, Field(pattern=GAUGE_REF_REGEX)] | None = None
    p: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    t: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    is_forecast: bool
    q_mid_cms: float = Field(ge=0)
    q_low_cms: float = Field(ge=0)
    q_high_cms: float = Field(ge=0)
    stage_mid_m: float = Field(ge=0)
    stage_low_m: float = Field(ge=0)
    stage_high_m: float = Field(ge=0)
    rate_of_rise_m_per_h: float
    velocity_ms: float = Field(ge=0)
    source: SourceKindType
    clipped_to_src: bool


# Gauge row model
class GaugeRow(BaseContractModel):
    gauge_ref: Annotated[str, Field(pattern=GAUGE_REF_REGEX)]
    site: Annotated[str, Field(pattern=USGS_SITE_REGEX)]
    feature_id: int = Field(ge=1)
    p: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    t: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    is_forecast: bool
    observed_q_cms: float | None = Field(default=None, ge=0)
    observed_wse_m: float | None = None
    predicted_q_mid_cms: float = Field(ge=0)
    predicted_q_low_cms: float = Field(ge=0)
    predicted_q_high_cms: float = Field(ge=0)
    predicted_wse_mid_m: float
    wse_datum: Literal["NAVD88"] = "NAVD88"


# State response model
class StateRequested(BaseContractModel):
    p: str
    t: str


class StateProducts(BaseContractModel):
    raster: str
    reaches_parquet: str | None = None
    reaches_json: str
    time_to_exceedance: str | None = None
    gauges_json: str | None = None
    overlay_png: str | None = None


class StateComputeMs(BaseContractModel):
    state_estimation: int | None = None
    boundary_forecast: int | None = None
    routing: int | None = None
    hand_mapping: int | None = None
    reduce: int | None = None
    write: int | None = None
    total: int = Field(ge=0)


class StateResponse(BaseContractModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Annotated[str, Field(pattern=SLUG_REGEX)]
    mode: Literal["nowcast", "forecast", "hindsight"]
    p: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)] | None = None
    t: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    requested: StateRequested
    horizon_minutes: int = Field(ge=0)
    members: list[MemberType] = Field(min_length=3, max_length=3)
    products: StateProducts
    computed_at: Annotated[str, Field(pattern=UTC_TIMESTAMP_REGEX)]
    compute_ms: StateComputeMs
    cache: Literal["hit", "miss", "precomputed"]
