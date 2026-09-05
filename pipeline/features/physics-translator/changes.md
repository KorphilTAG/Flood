# Changes

- Slug: physics-translator
- Spec: `pipeline/features/physics-translator/spec.md`
- Status: complete (documentation/contract portion; application foundation unavailable)

## Summary

Defined the Contract 2 impact JSON documentation, schema, and safe canned response. Extended the Contract 0 exposure registry and Kerr example with explicit PostGIS mappings.

## Files touched

| Path | Change | Why |
|---|---|---|
| `docs/contracts/README.md` | Edited | Marks Contract 2 as defined and identifies the extractor, LLM, and UI boundary. |
| `docs/contracts/contract-2-impact-products.md` | Added | Defines Contract 2 storage, query/projection semantics, thresholds, egress, reach rows, and coordinate prohibition. |
| `docs/contracts/schemas/impact-json.schema.json` | Added | Provides the machine-validatable Contract 2 document schema. |
| `docs/contracts/examples/impact-response.sample.json` | Added | Supplies a coordinate-free Contract 2 response fixture. |
| `docs/contracts/scenario.md` | Edited | Documents the PostGIS mapping and preserves `source` as raw-ingest metadata. |
| `docs/contracts/schemas/scenario.schema.json` | Edited | Adds safe lower-case `postgis` schema/table/geometry-column mapping validation. |
| `docs/contracts/examples/scenario.kerr-2025-07-04.json` | Edited | Configures every Kerr exposure layer's explicit PostGIS relation. |
| `pipeline/features/physics-translator/changes.md` | Edited | Records this implementation and its foundation dependency. |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| Contract 2 schema/sample validate; README identifies producer and consumers; schema rejects coordinate/geometry and fixed-object unknown keys | done | `docs/contracts/README.md`, `docs/contracts/schemas/impact-json.schema.json`, `docs/contracts/examples/impact-response.sample.json` |
| Contract 0 accepts safe PostGIS mapping; Kerr documentation example has every mapping | done | `docs/contracts/scenario.md`, `docs/contracts/schemas/scenario.schema.json`, `docs/contracts/examples/scenario.kerr-2025-07-04.json` |
| `PostGISExposureStore` performs bounded, quoted, validated reads | blocked | C01's `src/flood` package and package dependencies do not exist in this worktree; the spec prohibits creating a parallel application structure. |
| Contract 1 COG extraction resolves named bands and validates grids/products | blocked | C01's `src/flood` package and C03/C06 Contract 1 resolver/products are unavailable. |
| Offline extraction fixtures cover registry-only classifications, stable refs, and coordinate-free serialization | blocked | Test/package foundation is unavailable. |
| Same-`p` projection facts and earliest egress-blocked time are recorded | blocked | Test/package foundation and engine resolver are unavailable. |
| Reach sidecar is reduced to Contract 2 reach rows and velocity is labeled proxy | done | `docs/contracts/contract-2-impact-products.md`, `docs/contracts/schemas/impact-json.schema.json`, `docs/contracts/examples/impact-response.sample.json` |
| `flood impacts extract` resolves/writes/validates canonical output | blocked | C01 CLI registration and C03/C06 resolver are unavailable. |
| Offline and opt-in PostGIS tests run | blocked | No Python package, dependency manifest, or test harness exists in this worktree. |

## How to verify

- `python3 -m json.tool docs/contracts/schemas/impact-json.schema.json`
- `python3 -m json.tool docs/contracts/examples/impact-response.sample.json`
- Validate the added example against `impact-json.schema.json` with the C01 contract validator once it is merged.
- `git diff --check`

## Residual risk

- This worktree predates the C01 application foundation. The spec explicitly forbids a parallel package structure, so extractor, CLI, dependency, and test changes are blocked until C01/C03/C06 are available.
- No active `scenarios/kerr-2025-07-04.json` copy or `pyproject.toml` exists here. Per the spec's conditional file instructions, neither was created.

## Not done

- The blocked application, CLI, dependency, and test criteria listed above must be implemented after the named foundations merge.
