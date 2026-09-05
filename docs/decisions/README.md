# Decision records

One file per decision, numbered in the order they were made. Each record states the context, the decision, what it costs or rules out, and what is still open. Records are amended in place when a decision changes; the change is noted under Status with a date.

Format: `NNNN-short-title.md` with sections Status, Context, Decision, Consequences, Open questions.

| # | Decision | Status |
|---|---|---|
| [0000](0000-verified-data-findings.md) | Verified facts about the source data that constrain the design | Findings, 2026-09-05 |
| [0001](0001-physics-engine-must-predict-not-package.md) | The physics engine must extrapolate a plausible impact map from data available at a cutoff, not re-render inputs | Accepted |
| [0002](0002-information-horizon-p-and-target-t.md) | Every engine query carries two times: knowledge cutoff `p` and target `t` | Accepted |
| [0003](0003-compute-strategy-measure-before-choosing.md) | Measure pure-function, compute-then-cache, and precompute before committing | Accepted |
| [0004](0004-shared-backend-services-before-physics.md) | Shared backend services and contracts may be built before physics mode | Accepted |
| [0005](0005-thin-physics-verifier-frontend.md) | Build a thin frontend to visually and numerically verify engine output | Accepted |
| [0006](0006-simple-storage-before-postgis-titiler.md) | Start with files and in-process serving; adopt PostGIS or TiTiler only on stated triggers | Accepted |
| [0007](0007-aar-generator.md) | Add an after-action-report generator on the LLM endpoint | Accepted |
| [0008](0008-scenario-is-data-not-code.md) | Scenario is data, never code: scenario file, exposure registry, `<layer_id>:<source_id>` feature IDs | Accepted |
