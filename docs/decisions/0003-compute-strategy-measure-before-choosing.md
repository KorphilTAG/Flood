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
