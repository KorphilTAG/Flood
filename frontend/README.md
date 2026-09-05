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
- Field: select a team; read its assignment and approach; update status; enter and review an observation; return to the selected area on Command's map.
- Reports: submitted observations appear as unverified reported evidence in Command. Simulated offline mode queues reports until simulated connectivity is restored. State is session-only and is lost on reload. No real offline package, sync server, navigation, dispatch, or emergency signaling exists.
- Timeline: scrub, replay, reset; switch current estimate, forecast, or stale-information mode; select low/mid/high illustrative scenarios. New field reports are excluded before their knowledge cutoff.

## Data boundaries

`data/scenario.json` copies contract 0's scenario fixture. `data/mock.json` holds all geographic and incident-specific UI fixtures. Operational estimates, flood geometry, teams, reports, occupancy, access, and citations are synthetic. The OpenStreetMap basemap is geographic, with its attribution retained. 3D uses an ellipsoid, not elevation terrain. No actual flood simulation, verified rescue routing, AI, or AAR corpus is connected.

`lib/operations.ts` is the shared state transition layer. The impact, overlay, and session-state contracts remain provisional, so these UI-only types are not presented as final backend contracts. The future integration points are the documented `/clock`, `/clock/ws`, scenario, run/state, and product endpoints. Do not replace the physics verifier under `src/flood/verifier` with this product interface.

## Checks

```sh
pnpm test
pnpm typecheck
pnpm build
```

Tests cover Command-to-Field assignment/state sharing, double-assignment prevention, offline report delivery without duplication, report cutoff filtering, and timeline/scenario changes. Browser interaction testing has not been performed.
