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

- Command: select/search/filter areas; select map features; pan, zoom and toggle layers on one terrain map; inspect evidence/access; review a proposed plan against mock facts; approve an assignment; inspect resource status and changes; export the full JSON decision log.
- Layout: desktop Command uses a viewport-filling regional terrain map, a right queue showing all five priority areas, and a timeline below. Map layers live outside the canvas. One Review & assign popup contains evidence, access, plan review, and team assignment tabs. Field always renders inside a 390 × 844 phone with 75–150% preview zoom.
- Layers: flood extent, priority areas, resources, hazard markers, potential people hotspots, navigation landmarks, and directional water-flow arrows toggle independently.
- Assignment objectives: editable presets follow the selected team specialty and selected area.
- Field: select a team; read its assignment and approach; update status; enter and review an observation; start with Approach & hazards on the left, then switch to Current assignment; open a separate read-only map popup with current shared exercise data and independent area selection. The Field map never navigates to or changes the Command workspace. Team report history has its own popup; quick observation presets remain editable before submission.
- Reports: a phone-contained three-step form selects an editable observation, its specific map feature or new group, coordinates, count, and confidence. Submitted reports immediately update the shared session map as **reported**; review changes them to **verified**. Hazard-not-found replaces only the selected predicted hazard. Group sightings have independent IDs, relocations move the selected group, and evacuation closes only that group. No-people-visible preserves occupancy uncertainty. The map starts 100% predicted. Its coverage meter measures current predicted/reported/verified map features, not record count or calibrated confidence. The newest observation for each feature wins; later verification of an older report cannot overwrite it. Offline reports enter the map only at their receipt time. State remains session-only, without a live agency feed or multi-device backend.
- Proposed tactics: editable reconnaissance, occupant-assessment, and report-reconciliation presets reflect the selected area's current observations.
- Timeline: scrub, replay, reset. The estimate/scenario selectors are removed; the timeline uses the fixed baseline mock scenario. New field reports are excluded before their knowledge cutoff.

## Data boundaries

`data/scenario.json` copies contract 0's scenario fixture. `data/mock.json` holds all geographic and incident-specific UI fixtures. Operational estimates, flood geometry, teams, reports, occupancy, access, and citations are synthetic. The single map follows the dark Esri basemap, cyan water, and translucent navy panel aesthetics of `origin/feature/terrain-view` (reference commit `6aabcf5`). It retains the product frontend's Cesium renderer and archived USGS DEM rather than connecting the reference branch's Python engine endpoints. The terrain is a pinned subset of historical USGS 3DEP 1/3 arc-second DEMs published **2021-11-03**, with NAVD88 heights and roughly 10 m sampling. The flood overlay is draped on that terrain, using an illustrative terrain-constrained extent; contours and the 2D/3D selector are removed.

The committed 18.24 MB grid covers -99.46…-99.08 longitude and 29.90…30.14 latitude. Map navigation and rendering remain bounded to this regional extent inside Texas. Both Command and the phone map load the same historical elevation grid. Missing terrain produces an explicit unavailable state.

Source identifiers, URLs, grid dimensions, datums, and SHA-256 are in `data/terrain.json`. `scripts/extract-terrain.py` reproduces the subset from those pinned public USGS GeoTIFFs (requires Python rasterio/numpy). Terrain source: [USGS n30w100 2021](https://www.sciencebase.gov/catalog/item/6184ba6fd34ec04fc9c0814a), [USGS n31w100 2021](https://www.sciencebase.gov/catalog/item/6184ba6dd34ec04fc9c08144). Boundary: [Census TIGERweb 2020 states](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/54). Both are US government public data.

Ground elevation is fixed historical data. Flood extent, flow direction, area footprints, and depth trends remain illustrative; they are not a calibrated flood model. The coverage percentages describe **current map feature provenance**, excluding the real basemap and DEM. No actual flood simulation, verified rescue routing, AI, or AAR corpus is connected.

`lib/operations.ts` is the shared state transition layer; `lib/live-map.ts` projects received observations into current map features at the selected cutoff. The impact, overlay, and session-state contracts remain provisional, so these UI-only types are not presented as final backend contracts. The future integration points are the documented `/clock`, `/clock/ws`, scenario, run/state, and product endpoints. Do not replace the physics verifier under `src/flood/verifier` with this product interface.

## Checks

```sh
pnpm test
pnpm typecheck
pnpm build
```

Tests cover Command-to-Field assignment/state sharing, double-assignment prevention, offline report delivery without duplication, report cutoff filtering, timeline/scenario changes, report verification/cutoff/queue behavior, and specialty-specific objective presets. Additional checks cover historical DEM size/hash/range, bilinear sampling, out-of-coverage rejection, Texas boundary containment, and observation presets. Browser interaction testing has not been performed. The global Command/Field switch is a demo role selector, not production authentication or authorization.
