# 0004. Shared backend services and contracts may be built before physics mode

Status: accepted, 2026-09-05.

## Context

The architecture document says contracts come before code and suggests three parallel tracks. The physics engine's forecasting layer ([0001](0001-physics-engine-must-predict-not-package.md)) is the largest single item, and it is tempting to start there. But every other component reads from the clock, the session state store, and the run manifests, and none of them can be exercised end to end until those exist.

## Decision

It is acceptable, and probably preferable, to build the shared backend first: the four contracts stubbed with canned Kerr County data, the clock service, the session state store, a run store that holds manifests and products, and a thin API skeleton that serves them. Physics mode follows.

The engine's own development loop does not depend on the shared services. It is a pure function with a command-line entry point that reads local files and writes local products, so engine work can proceed in parallel against fixtures. Integration happens when both sides exist.

Order of shared work:

1. Contracts as JSON schemas with one canned example each, committed under `docs/contracts/` or a `schemas/` package.
2. Run manifest and product layout on disk ([0006](0006-simple-storage-before-postgis-titiler.md)).
3. Clock service with replay at adjustable speed and the `(p, t)` derivation from [0002](0002-information-horizon-p-and-target-t.md).
4. Session state store.
5. API skeleton returning canned products for every endpoint the UI and extractor need.
6. Verifier frontend ([0005](0005-thin-physics-verifier-frontend.md)) pointed at the canned products.

Then physics replaces the canned products behind the same endpoints.

## Consequences

- The first thing anyone sees on screen is canned data. That is intended and matches the PRD's instruction to validate the pipeline shape first.
- The engine's contract 1 output must be stable early, since the shared services are built against it. Grid, bands, sidecar table, and manifest fields are fixed in the contract before the forecasting layer is written.
- Team allocation from the architecture document still holds. The person on clock, session state, and UI starts here; the person on physics starts the engine core in parallel.

## Open questions

- None at this time.
