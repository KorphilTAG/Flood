# 0010. Calibrate rating-curve conveyance to gauge observations with one Manning n scale

Status: Accepted, 2026-09-05

## Context

The engine maps discharge to depth with FIM's synthetic rating curves and routes with the kinematic celerity dQ/dA of the same curves. In HUC8 12100201 those curves are uncalibrated at every gauge we use (`calb_applied` false on the Hunt, North Fork and Kerrville catchments; 29 of 1964 catchments carry a USGS calibration). Measured on 4 July 2025 (decision 0000):

- Stage at Hunt: HAND 24.4 m at 8920 cms against a 9.0 m observed rise; Kerrville 13.5 m against 11.1 m; North Fork 4.8 m at 374 cms against 2.9 m.
- Wave speed: the hindsight flood front (first 1000 cms) reached the reach above Kerrville at 12:35Z against 11:00Z observed at the Kerrville gauge, and the 3000 cms front at 13:30Z against 11:15Z. The national model shows the same slow arrival (its Kerrville peak is at 16Z).

Both errors are one error: too little conveyance in the tables. The scenario already carried a `roughness.manning_n_scale` knob, but it reached only the mapping step, so scaling it fixed depth while leaving the wave slow and the reach table's stage unscaled.

## Decision

1. The Manning n scale divides the rating-table discharge everywhere it is used: HAND mapping, the reach and gauge tables, and the routing celerity and top width. One knob, one physical meaning (conveyance), consistent products.
2. The reference scenario sets `manning_n_scale: 0.5`, chosen from a sweep of 1.0, 0.7, 0.5 and 0.4 against the observed gauge-height rise and the observed front arrival at Kerrville:

| Scale | Front (1000 cms) above Kerrville, observed 11:00Z | Front (3000 cms), observed 11:15Z | Stage / observed rise at Kerrville, North Fork, Hunt |
|---|---|---|---|
| 1.0 | 12:35Z | 13:30Z | 1.2, 1.7, 2.6 |
| 0.5 | 11:35Z | 12:15Z | 0.85, 1.19, 1.90 (measured after the change) |
| 0.4 | 11:20Z | 11:55Z | about 0.75, 1.1, 1.7 |

0.5 brings the stage rise within 15 to 20 percent at the two gauges whose curves are not otherwise suspect (Kerrville now slightly under, North Fork slightly over) and moves the Kerrville arrival from 95 minutes late to 35. 0.4 buys another 15 minutes of arrival at the cost of understating Kerrville stage by about a quarter. Hunt stays about twice too deep at either value: its catchment has `SLOPE` exactly 0.001, a floor value, and needs a per-reach fix that this decision does not attempt.
3. The scale is scenario data, recorded in the run manifest's forcing config and in a limitation line, and changes the `config_hash`, so calibrated and uncalibrated runs are distinct run IDs.

## Consequences

- Kerrville and downstream reaches flood at roughly the observed time in hindsight and in forecasts issued once the Hunt rise is under way; the map upstream of Hunt is less over-inundated but still about twice too deep at the Hunt gauge.
- The calibration uses the same event the demo replays. A second event in the record, or a second scenario, must be checked before treating 0.5 as a regional value.
- The uncalibrated products remain available under the previous run ID for comparison.
