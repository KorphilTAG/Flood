# Flood command interface mock

An interactive product UI based on the updated PRD, frontend track, and the supplied operational-interface reference. Command and Field share one session state. The training interface is intentionally omitted at the user's request.

## Run

Use Node 22.13+ and pnpm 11:

```sh
pnpm install
pnpm dev
```

The app uses React, TypeScript, the Next.js App Router API through Vinext, and CesiumJS. `predev` and `prebuild` copy Cesium's runtime assets from the installed dependency. Generated assets are ignored by Git. The Site preview uses the same source.

## Interactions

- Command: select/search/filter areas; select map features; pan, zoom, switch 2D/3D, toggle layers; inspect evidence/access; review a proposed plan against mock facts; approve an assignment; inspect resource status and changes; export the full JSON decision log.
- Layout: desktop Command uses a square regional map, a right queue showing all five priority areas, and a timeline below. Map layers live outside the canvas. One Review & assign popup contains evidence, access, plan review, and team assignment tabs. Field always renders inside a 390 × 844 phone with 75–150% preview zoom.
- Layers: flood extent, priority areas, resources, hazard markers, potential people hotspots, navigation landmarks, and directional water-flow arrows toggle independently.
- Assignment objectives: editable presets follow the selected team specialty and selected area.
- Field: select a team; read its assignment and approach; update status; enter and review an observation; switch between Current assignment and Approach & hazards tabs; open a separate read-only map popup with current shared exercise data and independent area selection. The Field map never navigates to or changes the Command workspace. Team report history has its own popup; quick observation presets remain editable before submission.
- Reports: submitted observations appear as unverified reported evidence in Command. Command can verify an observation after reviewing it. The area percentage is verified exercise evidence records divided by all visible exercise evidence records; modeled/unverified is its complement, not a calibrated probability. New unreviewed reports change the denominator; verification changes the numerator. Queued and future reports never affect coverage. Live operational data remains 0%. Simulated offline mode queues reports until simulated connectivity is restored. State is session-only and is lost on reload. No real offline package, sync server, navigation, dispatch, or emergency signaling exists.
- Timeline: scrub, replay, reset. The estimate/scenario selectors are removed; the timeline uses the fixed baseline mock scenario. New field reports are excluded before their knowledge cutoff.

## Data boundaries

`data/scenario.json` copies contract 0's scenario fixture. `data/mock.json` holds all geographic and incident-specific UI fixtures. Operational estimates, flood geometry, teams, reports, occupancy, access, and citations are synthetic. The OpenStreetMap basemap is geographic, with its attribution retained. 3D uses a pinned regional subset of two historical USGS 3DEP 1/3 arc-second DEMs published **2021-11-03**; procedural terrain has been removed. Elevations are NAVD88 meters, reprojected from NAD83 to WGS84 and resampled to a 0.0001° grid (roughly 10 m spacing). The publication date is not a claim that every source measurement was acquired that day. Contours are computed from the actual grid at 20 m intervals and appear only in 3D. In 2D, OpenStreetMap roads and objects appear at full color without terrain contours.

Terrain is fetched only when opening 3D. The committed 18.24 MB grid covers -99.46…-99.08 longitude and 29.90…30.14 latitude. 3D navigation/rendering is restricted to this affected-area DEM extent; no elevation is invented outside it. 2D is clipped to Texas using the Census 2020 state boundary, with geographic/zoom bounds and region-limited imagery. Low-level tile requests and other world regions are excluded. Missing terrain produces an explicit unavailable state, never generated contours.

Source identifiers, URLs, grid dimensions, datums, and SHA-256 are in `data/terrain.json`. `scripts/extract-terrain.py` reproduces the subset from those pinned public USGS GeoTIFFs (requires Python rasterio/numpy). Terrain source: [USGS n30w100 2021](https://www.sciencebase.gov/catalog/item/6184ba6fd34ec04fc9c0814a), [USGS n31w100 2021](https://www.sciencebase.gov/catalog/item/6184ba6dd34ec04fc9c08144). Boundary: [Census TIGERweb 2020 states](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/54). Both are US government public data.

Ground elevation is fixed historical data. Flood extent, flow direction, area footprints, and depth trends remain illustrative; they are not a calibrated flood model. The verification percentage describes **incident evidence records only**, excluding the real basemap and DEM. No actual flood simulation, verified rescue routing, AI, or AAR corpus is connected.

`lib/operations.ts` is the shared state transition layer. The impact, overlay, and session-state contracts remain provisional, so these UI-only types are not presented as final backend contracts. The future integration points are the documented `/clock`, `/clock/ws`, scenario, run/state, and product endpoints. Do not replace the physics verifier under `src/flood/verifier` with this product interface.

## Checks

```sh
pnpm test
pnpm typecheck
pnpm build
```

Tests cover Command-to-Field assignment/state sharing, double-assignment prevention, offline report delivery without duplication, report cutoff filtering, timeline/scenario changes, report verification/cutoff/queue behavior, and specialty-specific objective presets. Additional checks cover historical DEM size/hash/range, bilinear sampling, out-of-coverage rejection, Texas boundary containment, and observation presets. Browser interaction testing has not been performed. The global Command/Field switch is a demo role selector, not production authentication or authorization.
