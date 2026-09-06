# Contract 0. Scenario file and exposure layer registry

Producer: humans. Consumers: every component. Schema: [scenario.schema.json](schemas/scenario.schema.json). Example: [examples/scenario.kerr-2025-07-04.json](examples/scenario.kerr-2025-07-04.json). Rationale: decision [0008](../decisions/0008-scenario-is-data-not-code.md).

One JSON file per scenario at `scenarios/<scenario_id>.json`. Everything specific to an incident, basin, or dataset lives here. Paths inside the file are relative to the file's directory.

## Sections

| Section | Who reads it | Content |
|---|---|---|
| `scenario_id`, `name`, `description`, `timezone` | All | Identity and the IANA timezone for display |
| `hydrology.huc8[]`, `hydrology.fim_version` | Engine prep | Which HAND FIM artifacts to fetch |
| `hydrology.aoi` | Engine prep | Corridor bounds in EPSG:5070. Fixes the run grid. |
| `hydrology.record` | Engine, clock | Replay window, UTC |
| `hydrology.gauges[]` | Engine | USGS sites with their NWM `feature_id` and a `role`: `boundary` (drives inflow), `interior` (bias correction and validation), `validation_only` |
| `hydrology.junction_inferences[]` | Engine | Ungauged tributary at a gauged confluence: inferred reach, downstream gauge, tributary gauges to subtract, travel time |
| `forcing_defaults` | Engine | A full forcing configuration (contract 1 section 8) |
| `exposure_layers[]` | Extractor, UI | The registry, below |
| `decision_points[]` | Training mode, AAR generator | `id`, `t`, `label`, `prompt`, optional `reference_ids` (feature or `aar` refs the critic should surface) |
| `last_known_positions[]` | Search-area tool | Scripted call data: `id`, `t`, `lon`, `lat`, `note` |

## Exposure layer registry

Each entry declares one layer. The extractor iterates the list and never names a layer in code.

| Field | Meaning |
|---|---|
| `layer_id` | Lowercase slug, becomes the prefix in `<layer_id>:<source_id>`. Must not be `reach`, `gauge`, or `aar`. |
| `name` | Display name |
| `source` | Path to a GeoPackage, GeoParquet, or GeoJSON, relative to the scenario file. This remains the raw-ingest source; the impact extractor does not query it. |
| `postgis` | Optional explicit PostGIS read mapping. The impact extractor requires it: `schema`, `table`, and `geometry_column` are lower-case SQL identifiers. It reads no convention derived from `source` or `layer_id`. |
| `id_field` | Attribute holding the stable source ID. IDs must be unique within the layer. |
| `geometry` | `point`, `line`, or `polygon` |
| `attributes[]` | Attribute names carried through to impact JSON unchanged |
| `impact.impassable_depth_m` | Points and lines: depth at which the feature is reported impassable |
| `impact.threatened_depth_m` | Polygons: depth at which the feature is reported threatened |
| `impact.hazard_dv_limit` | Optional: depth times velocity above which the feature is reported hazardous regardless of depth |
| `egress.routes_layer` | Optional, polygons: the line layer whose features are this site's egress routes, joined by `egress.join_field` on the route layer holding the site's source ID |

The Kerr County example declares `crossing`, `road`, `structure`, and `site`. Each maps to `flood_exposure.kerr_2025_07_04_<layer_id>` with geometry column `geometry`. A different scenario may declare entirely different layers.
