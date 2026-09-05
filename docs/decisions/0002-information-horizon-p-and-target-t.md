# 0002. Every engine query carries a knowledge cutoff `p` and a target time `t`

Status: accepted, 2026-09-05.

## Context

The product trains responders who act on stale and incomplete information. We want to see what the engine would have projected for a moment `t`, given only what was knowable at an earlier moment `p`. That lets a trainee experience the tool as a responder in the field would, working from information that is minutes or hours old, and lets a reviewer measure how much was foreseeable.

The architecture document has one clock. That remains true. This decision adds a second time to every engine query without adding a second clock: `p` is derived from the clock, and `t` is a horizon offset from it.

## Decision

Every engine request specifies:

- `p`, the knowledge cutoff. Only records with availability time at or before `p` may be used. Availability time, not valid time, is what counts (see [0001](0001-physics-engine-must-predict-not-package.md), Consequences).
- `t`, the target time, with `t >= p`. `t == p` is a nowcast: the best estimate of current conditions from what is known now. `t > p` is a forecast.
- Hindsight is a distinguished case, `p` at the end of the record, which produces the truth run used for after-action comparison and for the hindsight overlay.

Requests with `t < p` are rejected. There is no mode that predicts the past using future information; use hindsight for that.

Three ways the UI drives these:

1. Nowcast mode: the clock sets `p = t`. The map shows what the twin would have estimated as current conditions at that moment.
2. Forecast mode: the clock sets `p`, the user picks a horizon `h`, and `t = p + h`. Standard horizons are 30, 60, 120, and 240 minutes, which are the impact extractor's projection horizons.
3. Stale-information mode: the clock sets `t`, the user picks a lag `L`, and `p = t - L`. This simulates a responder acting at `t` on information that is `L` old. This is the mode the product owner asked for and it is the one most likely to land in a demo.

The cache key for any engine product is `(run, forcing configuration, p, t, member)`. Timestamps are stored in UTC and rendered in Central time. The 1:14 am CDT flash flood warning is 06:14Z.

## Consequences

- Precomputation is now over a two-dimensional grid of `(p, t)` rather than a line of `t`. See [0003](0003-compute-strategy-measure-before-choosing.md) for the cost.
- The session state schema gains `p` alongside the existing `t`, and the impact JSON records which pair it was computed from, so the critic can be told whether it is critiquing a plan made on stale information.
- The clock service is unchanged. It still owns one time. The engine API takes `p` and `t` explicitly and never reads the clock itself.
- The verifier frontend needs two controls, a timeline for the clock and a lag or horizon control, plus a side-by-side or difference view against hindsight.

## Open questions

- Should stale-information mode also degrade the gauge record, for instance by dropping the Hunt gauge after it failed? Probably yes, as a scenario option, since that is exactly what happened.
