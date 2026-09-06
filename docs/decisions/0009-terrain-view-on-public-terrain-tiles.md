# 0009. Drape the engine's overlay on public terrain tiles for the 3D view

Status: accepted, 2026-09-05.

## Context

The product UI calls for a 3D map ([architecture](../architecture.md) section 5.9), and the cut list drops it first because it was expected to need Cesium, a quantized-mesh terrain build from 1 m lidar, and a tile server. Meanwhile the verifier ([0005](0005-thin-physics-verifier-frontend.md)) already renders every engine product as a single Web Mercator PNG per `(p, t)`, and the engine already emits everything a "how far did the water rise" view needs: depth low, mid and high, probability of inundation, reach stage and rate of rise, and predicted against observed gauge discharge.

The only missing input for a 3D view was ground elevation. The HAND REM raster is height above the nearest drainage, not elevation, and no DEM had been ingested.

## Decision

Build the 3D view as a second static page served by the same API process, `/verifier/terrain.html`, with MapLibre GL JS:

- Terrain comes from the public Terrain Tiles dataset on AWS Open Data (terrarium encoding, built from USGS 3DEP over Texas, about 10 m at the maximum zoom). No DEM is downloaded, processed, or served by us.
- The engine's `overlay.png` is draped on the terrain as an image source, positioned from the `X-Bounds-4326` header. The flooded extent is therefore exactly what the engine computed; the water is painted on the ground rather than modelled as a surface.
- The overlay is requested with `smooth=1` at 6144 px (about 12 m per pixel over the corridor): bilinear resampling at every scale, no one-pixel dilation, and an anti-aliased wet edge. The verifier's cell-crisp rendering, which keeps one-cell rivers visible at corridor zoom in 2D, reads as blocks and square rims once draped on relief. Wet cells are identical in both modes.
- Reach flowlines and gauge points come from a new read-only endpoint, `GET /runs/{run_id}/network.geojson`, built in process from the cube's network table. Reaches are coloured by rate of rise from the reach table; gauges show predicted against observed discharge from the gauge table.
- The page reads and drives the same `/clock` service as the 2D verifier, so the two pages always show the same moment.
- Basemaps are free raster tiles (CARTO dark, Esri imagery, OpenStreetMap) with attribution; no API keys.

## Consequences

- The 3D view costs no engine or product changes and no new infrastructure. It lives alongside the verifier and shares its endpoints, so it is also an integration test of contract 1 from a second client.
- Precision is bounded by the public terrain tiles, not by our 10 m grid: the valley shape and bank positions read correctly, but a 1 m lidar terrain would need the 3DEP ingest this decision deliberately avoids.
- Because water is draped rather than extruded, the view cannot show a water surface with vertical banks. Doing that needs a water-surface-elevation product (DEM plus depth) and exposes HAND's per-catchment flat surface as visible steps. That remains a stretch item, not a foundation.
- The `network.geojson` endpoint is part of contract 1 section 9 and is cached per run; the network is static for a run's lifetime.

## Open questions

- Whether to add a 3DEP 1/3 arc-second ingest so the terrain matches the engine grid exactly and a water-surface-elevation band becomes possible.
- Whether the product UI adopts this page directly or reimplements it inside the React application. The page is plain JavaScript and every data path is an API call, so either is a small step.
