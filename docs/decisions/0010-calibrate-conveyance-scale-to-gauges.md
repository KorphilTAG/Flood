# 0010. Calibrate conveyance to the gauges and route the flood front at kinematic speed

Status: Accepted, 2026-09-06 (supersedes the single-scale version of 2026-09-05)

## Context

The engine maps discharge to depth with FIM's synthetic rating curves and routes with the celerity of the same curves. On the reference corridor the first products were wrong in three ways that all looked like "the physics is broken": Hunt was mapped 2.7 times too deep, the flood wave reached Kerrville hours late and a third smaller than observed, and forecasts issued while Hunt was already flooding showed Kerrville dry. Tracing them reach by reach (decision 0000 holds the data facts) found four separate causes.

1. **Uncalibrated rating curves.** `calb_applied` is false on every gauged catchment we use. Against the observed gauge-height rise on 4 July 2025: Hunt 24.4 m of HAND stage for 9.0 m observed, North Fork 4.8 for 2.9, Kerrville 13.5 for 11.1.
2. **Lumped-section celerity.** FIM's tables merge channel and floodplain into one section, so above bankfull their tangent dQ/dA drops to the mean velocity or below (1 to 2 m/s at 4000 cms) while the observed front moved at 2.5 to 3 m/s.
3. **Unrated connector reaches.** Two reaches in the middle of the corridor (412 m and 185 m) have no HAND catchment and a recorded slope of zero. The slope-only fallback gave them a celerity clipped at 0.1 m/s, turning them into 69 and 31 minute reservoirs. The peak arrived above them at 10:50Z almost intact (8166 cms) and left them at 13:10Z as 6140 cms. This, not hydraulics, was most of the late, flattened wave.
4. **Stalled gauges used as controls.** The gauge above Bear Creek stopped reporting discharge at 09:45Z at 2 cms and Center Point at 10:30Z at 15 cms while their gauge heights kept rising. As interior controls they pin routed flow to the stale value.

A first attempt used one global Manning n scale of 0.5, which reached only the mapping step, and the routing's shock term made no difference because on these tables the secant speed equals the tangent.

## Decision

1. **One conveyance knob, applied everywhere.** The Manning n scale divides rating-table discharge in HAND mapping, in the reach and gauge tables, and in routing (celerity and top width). It may be a scalar or a per-catchment field.
2. **Per-gauge calibration, as FIM does it** (`roughness.gauge_calibration: true`). For each scenario gauge, observed discharge and gauge height are paired, the rise above base flow is compared with the table's stage at the same discharge, and the scale minimising the weighted squared stage error over the flood range is fitted on a grid from 0.2 to 2.0. Reaches on a gauged levelpath interpolate by distance between gauges; ungauged levelpaths inherit the first calibrated reach downstream; the rest keep the scalar. A gauge is trusted only if its paired record covers a flood (at least 50 cms, at least 1 m of rise, at least 12 flood-range samples); otherwise it is left unfitted. Fits are written to `calibration.json` in the run directory and disclosed in the manifest limitations.
3. **Kinematic celerity floor.** Celerity is the larger of the table's dQ/dA and the wide-channel Manning value (5/3) Q/A (Lighthill and Whitham 1955; Ponce). The kinematic shock speed (Q_in − Q_out)/(A_in − A_out) is also applied on rising limbs; it is physically right and cheap, and inert on these tables.
4. **Connector reaches borrow hydraulics.** A reach without a rating row uses the table and slope of the nearest rated reach, upstream first, then downstream.
5. **Stalled gauges are declared as outages in the scenario** (`scenario_overrides` of type `gauge_outage`), which is scenario data as decision 0008 requires. Automatic flat-line detection is the product follow-up.

## Evidence on the reference corridor (hindsight, 4 July 2025)

| Quantity | Before | Global scale 0.5 | This decision | Observed |
|---|---|---|---|---|
| First 1000 cms above Kerrville | 12:35Z | 11:35Z | 10:05Z | 11:00Z at the Kerrville gauge |
| First 3000 cms above Kerrville | 13:30Z | 12:15Z | 10:30Z | 11:15Z |
| Peak above Kerrville | 16:15Z, 5894 cms | 14:30Z, 6018 | 11:25Z, 8237 | 11:45Z, 8438 |
| Comfort at 16:00Z (validation gauge, not a control) | 4 cms | 1209 | 4831 | 5012 |
| Stage / observed rise: Hunt, Kerrville, North Fork, Comfort | 2.6, 1.2, 1.7, 0.01 | 1.9, 0.85, 1.2, 0.6 | 1.33, 1.09, 1.02, 1.07 | 1 |
| Kerrville forecast issued 09:45Z for 11:45Z | 3 cms | 734 | 6352 | 8438 |

Fitted scales: North Fork 0.37, Hunt 0.20 (at the grid edge; its gauge-height record ends at 3511 cms), Johnson Creek 0.72, Kerrville 0.80, Comfort 0.58. Above Bear Creek and Center Point are unfitted (records cover no flood). The wave now runs 20 minutes early at the peak and about 50 minutes early on the leading edge, the safe side for a warning product; raising the fit floor to 0.3 costs 0.2 m of Hunt fit error and buys 5 minutes, so it was not taken.

## Consequences

- The calibration uses the event the demo replays. It is a rating-curve property, the same thing FIM calibrates from historical ratings, but a second event or scenario must be checked before treating the fitted scales as regional values.
- Routing is about 30 percent slower (two extra table interpolations per rising cell); a hindsight route of the 48 h record takes 50 s.
- Calibrated and uncalibrated runs have different config hashes and coexist as separate run IDs.
- Not addressed: the Hunt catchment's slope floor of 0.001, the linear trend's overshoot through a peak, and automatic detection of stalled gauges.
