# Contract 2. Impact products

Producer: impact extractor. Consumers: LLM layer and UI. Schema: [impact-json.schema.json](schemas/impact-json.schema.json). Example: [impact-response.sample.json](examples/impact-response.sample.json).

The extractor translates resolved Contract 1 depth products and configured exposure features into deterministic, feature-ID-backed facts. It is the only input a later LLM layer receives from this process: it never contains a raster, geometry, bounds, longitude, or latitude.

## Storage and query identity

The extractor preserves the engine's snapped UTC query pair. A forecast or nowcast product is written atomically at:

```
runs/<run_id>/impacts/p=<P>/t=<T>/impact.json
```

Hindsight, which has no knowledge cutoff, is written at:

```
runs/<run_id>/impacts/hindsight/t=<T>/impact.json
```

`<P>` and `<T>` are compact UTC timestamps as defined by Contract 1. The document still uses second-precision UTC timestamps. `p` is `null` only for hindsight; otherwise it is the same fixed cutoff for the current raster and every projection.

## Facts and thresholds

Every fact identifies its configured exposure feature only as `<layer_id>:<source_id>`. The extractor samples points and calculates depth/hazard zonal summaries for lines and polygons. It considers depth at least `0.03 m` wet for `wet_fraction`; dry `0` is not an impact, and `-9999` is nodata rather than dry.

Points and lines become `impassable` when their registry `impact.impassable_depth_m` threshold or optional `impact.hazard_dv_limit` is met. Polygons become `threatened` when `impact.threatened_depth_m` or the optional hazard limit is met. A layer without the applicable configured threshold is invalid extractor configuration. `attributes` contains only the names allow-listed by that layer's registry entry.

The extractor evaluates the requested raster plus same-`p` targets at `t + 30`, `t + 60`, and `t + 120` minutes when Contract 1 permits them. Each included target appears in `projections`; `first_impacted_t` is the earliest impacted target. Features dry at every evaluated target are omitted. A missing engine product is an error, not evidence of dry ground.

## Egress and reaches

For a polygon layer with `egress`, the extractor joins route facts through the configured `routes_layer` and `join_field`. It reports each site as `open`, `blocked`, or `unknown`, along with route references and its first blocked time. `unknown` means the configured relationship cannot establish a route state; it is never inferred from an absent raster pixel.

`reaches` copies only `reach_ref`, mid-member stage, rate of rise, velocity proxy, and source from the Contract 1 reach sidecar. The parent-level `velocity_is_proxy` is always `true` and must be displayed as such by consumers.

## Coordinate and geometry rule

Contract 2 has no geometry or coordinate fields. The schema rejects unknown keys on all fixed objects and explicitly rejects `geometry`, `coordinates`, `lon`, and `lat`; dynamic attribute values are scalar only. Consumers must use a feature reference to obtain any spatial presentation through a separate authorized map-data path.
