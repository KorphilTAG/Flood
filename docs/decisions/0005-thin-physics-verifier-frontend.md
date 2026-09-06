# 0005. Build a thin frontend to verify engine output

Status: accepted, 2026-09-05.

## Context

We need to look at engine output early and often to know whether it is plausible, and the product's 3D map is a large piece of work that lands late. A thin, plain, fast viewer built for correctness checking removes that dependency and doubles as the place where hindcast skill ([0001](0001-physics-engine-must-predict-not-package.md), stage 5) is displayed.

## Decision

Build a single-page verifier served by the API process. It is a development tool, not the product UI, and it is allowed to be plain.

What it shows:

- A 2D map with the depth raster for the selected `(p, t)` as an image overlay, colour-ramped, with a probability-of-inundation toggle. Basemap from any free tile source; terrain shading optional.
- A timeline control bound to the clock, plus a horizon or lag control implementing the three modes in [0002](0002-information-horizon-p-and-target-t.md).
- A side-by-side or difference view against the hindsight run for the same `t`.
- A gauge panel: for each USGS site, observed stage over time with the engine's predicted stage from the selected `p` overlaid. This is the fastest way to see whether routing and boundary extrapolation are behaving.
- A hindcast skill table: error at each gauge by cutoff and horizon, and extent overlap against hindsight.
- A reach table for the selected `(p, t)`: flow, stage, rate of rise, velocity, forcing source, member spread.

How it is built:

- Static HTML plus a small amount of JavaScript. Leaflet or MapLibre GL JS for the map. Image overlays are PNGs in Web Mercator rendered by the engine from the depth array with fixed bounds, so no tile server is involved. A chart library for the gauge panel.
- The engine exposes a `render_png(depth_array, bounds)` helper. At 20 m working resolution a corridor PNG is a few hundred kilobytes and renders in well under a second.
- All data comes from the same API endpoints the product UI will consume, so the verifier is also the first integration test of the API.

## Consequences

- Cesium, terrain tiles, and 3D draping are not needed to make progress on physics. They remain the product UI's concern.
- The verifier will expose grid, unit, and orientation bugs early, which is its purpose. Expect to catch the millimetre-versus-metre and branch-collision mistakes from [0000](0000-verified-data-findings.md) here.
- When the product UI is ready, the verifier stays as the engine owner's debugging surface.

## Open questions

- Resolved 2026-09-05 by [0009](0009-terrain-view-on-public-terrain-tiles.md): a 3D view exists at `/verifier/terrain.html`, built with MapLibre GL JS over public terrain tiles rather than deck.gl over a local DEM.
