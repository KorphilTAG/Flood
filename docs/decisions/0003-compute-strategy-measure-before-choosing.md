# 0003. Measure compute cost before choosing pure-function, compute-then-cache, or precompute

Status: accepted, 2026-09-05.

## Context

Three ways to serve engine products:

1. Pure function. Every request runs the pipeline and returns the result. Simplest, always fresh, no storage, but latency is paid on every scrub of the timeline.
2. Compute-then-cache. Same as above with a cache keyed by `(run, forcing, p, t, member)`. The first request pays and repeats are free. Memory or disk grows with use.
3. Precompute. Batch-run the grid of `(p, t)` pairs ahead of the demo and serve files. Zero latency during the demo, but the grid must be chosen in advance and any change to forcing or parameters invalidates everything.

The right answer depends on numbers we have not measured yet. Decision [0002](0002-information-horizon-p-and-target-t.md) makes the grid two-dimensional, which changes the arithmetic materially.

## Decision

Instrument the engine from the first commit and decide from measurements, not from preference. Record wall time per stage per request: state estimation, boundary forecast, routing, HAND mapping per branch, ensemble reduction, and file write. Log them as structured lines so they can be tabulated.

Decision criteria:

- If a full `(p, t)` request for the corridor at 10 m completes under roughly 300 ms without the file write, serve as a pure function with an in-memory LRU cache. Timeline scrubbing feels immediate at that latency.
- If it is between 300 ms and a few seconds, use compute-then-cache on disk, and prewarm the cache with the demo's scripted `(p, t)` pairs and the hindsight series.
- If it is slower than that, precompute the demo grid and treat interactive what-if as a background job with a progress indicator.

Back-of-envelope figures, to be replaced by measurements:

| Quantity | Estimate |
|---|---|
| Corridor cells at 10 m, Hunt forks to Comfort | about 10 million |
| Branches intersecting the corridor | about 5 of 12 |
| HAND mapping, one member, numpy gather and subtract | 50 to 200 ms |
| Muskingum-Cunge over about 250 reaches, 4 hours at 1 minute | under 10 ms |
| COG write, 2 to 3 bands float32 | about 0.5 s |
| Demo grid: `p` every 5 min over 6 h (72) times horizons every 15 min to 4 h (16) times 3 members | about 3,500 mappings |
| Precompute time for that grid, single core | 5 to 10 minutes |
| Storage for that grid if every product is kept | 1 to 2 GB |

These figures suggest the pure function is probably fine for depth, and that the file write is the expensive part. That argues for serving arrays or PNG overlays directly from memory to the verifier frontend and writing COGs only for products the product UI needs.

## Consequences

- The engine is written as a pure function first regardless. Caching and precompute are wrappers added after measurement, never baked into the core.
- Precompute, if adopted, is limited to the hindsight series and the demo's scripted pairs. The rest stays on demand.
- Any change to forcing configuration or roughness parameters invalidates cached products, so the cache key includes a hash of that configuration.

## Open questions

- Whether to reduce the verifier's working resolution to 20 m to keep interactive latency low while the product UI reads 10 m COGs. Measure first.

## Measurements, 2026-09-05 (after wave 2 merged)

Reference corridor: 6600 by 2600 cells (17.2 Mcells), 9 HAND branches, 244 routed reaches, USGS-only forcing, this development laptop with no GPU.

| Stage | Before fix-up | After fix-up |
|---|---|---|
| `map_member`, one member, depth only | 3.3 s | 1.7 s |
| `map_member`, one member, with velocity | 11.1 s | 2.5 s |
| Routing, one cutoff, 12 h window at 1 min | 19 to 26 s | unchanged |
| Routing, hindsight, full 48 h record | 86 s | unchanged |
| Reduce three members | 1.2 s | 1.2 s |
| First `(p, t)` state request, cold | about 30 s | about 15 s expected; routing dominates |
| Fixture `(p, t)` through `Run` | 18 s (per-call DataFrame filtering in `qlat`) | 0.9 s |

Decision taken: the **compute-then-cache** branch. The routed series is cached per `p` in memory, so scrubbing `t` under a fixed `p` costs only the mapping; written products are reused from disk. The demo's scripted `(p, t)` pairs and the hindsight series are prewarmed before the demo.

Next optimisation targets, in order: vectorise routing across reaches at the same topological level (the Python loop over 244 reaches by 720 to 2880 steps by 3 members is the 19 to 86 s); use a 5-minute routing step for the demo scenario if that is not enough; store cube branches as int16 millimetres inside their covered window to cut the 1.2 GB in-memory footprint.
