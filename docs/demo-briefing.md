# Physics engine: demo briefing

What to say, what to show, what the numbers are, and where to look when someone asks a hard question.

## The one-line pitch

Given everything that was actually known at a cutoff time `p`, the engine predicts what the river corridor looks like at a later time `t`: discharge on every reach, water depth and velocity on every 10 m cell, the probability a cell is under water, and how many minutes until it is. Hindsight (the full record) is the truth it is scored against. It is a forecaster, not a replay: decision 0001 in `docs/decisions`.

## How it works, in six steps

1. **Inputs, with their real latencies.** USGS gauges (discharge and gauge height, 5 minutes, usable 5 minutes after the fact), the National Water Model analysis (hourly, 60 minutes late) and its short-range forecasts (6 leads, 90 minutes late), and NOAA's FIM HAND terrain tables for HUC8 12100201. The scenario file `scenarios/kerr-2025-07-04.json` declares all of it; nothing about Kerr County is in code (decision 0008, enforced by a test).
2. **State at the cutoff.** Gauged reaches take the observation; the ungauged South Fork is inferred by mass balance at the Hunt confluence (Hunt minus North Fork, 20 minute travel time); every other reach gets NWM lateral inflow scaled by the nearest gauge's observed-to-model ratio. Gauges declared as outages in the scenario are ignored from the moment they stalled.
3. **Boundaries beyond the cutoff.** Each headwater trend is extrapolated over its last 30 minutes and relaxed to persistence over 60. Three members, low, mid and high, scale the trend by 0.5, 1.0 and 1.5. That spread is the engine's uncertainty.
4. **Routing.** Muskingum-Cunge along the 244-reach network at a 5-minute step (checked within 2.3 percent of a 1-minute step). Wave speed is the larger of the rating table's dQ/dA and the wide-channel kinematic value (5/3)·Q/A, with the kinematic shock speed on rising limbs. Reaches with no HAND catchment borrow their neighbour's hydraulics.
5. **Mapping.** For each reach, stage comes from the FIM synthetic rating curve at the routed discharge; depth on each cell is stage minus that cell's height above its nearest drainage; branches are mosaicked by maximum. Three members give depth low/mid/high, probability of inundation, and time to exceed 0.15, 0.30 and 0.60 m. Grid: 6600 by 2600 cells, 17 million, 66 by 26 km.
6. **Products.** Cloud-optimised GeoTIFFs and Parquet tables per `(p, t)` under `runs/<run_id>/`, one JSON state API (`GET /runs/{id}/state?p=&t=`), overlay PNGs for maps, and two verifier pages (2D and 3D).

## Calibration, the part that makes it credible

Out of the box the products were wrong in three visible ways, and the causes were found reach by reach (decision 0010):

| Symptom | Cause | Fix |
|---|---|---|
| Hunt mapped 2.7 times too deep | FIM's rating curves are uncalibrated on every gauged catchment here | Conveyance scale fitted per gauge from observed discharge and gauge height, interpolated along the river, the same adjustment-factor approach NOAA uses |
| Flood wave reached Kerrville four hours late, a third too small | Two 400 m connector reaches with no HAND catchment routed at 0.1 m/s; FIM's lumped sections give a wave speed below the mean velocity | Connectors borrow neighbour hydraulics; kinematic celerity floor |
| Kerrville forecast dry while it flooded | Both of the above, plus two gauges that stalled mid-event acting as controls | Outages declared in the scenario |

The national model has the same slow wave: its Kerrville peak is at 16Z against 11:45Z observed.

## The numbers to have ready

Times are UTC; Texas in July is UTC minus 5, so 09:45Z is 4:45 am CDT.

| | Observed | Engine, hindsight |
|---|---|---|
| Hunt first 1000 cms / peak | 08:55Z / 10:05Z, 8920 cms | control gauge (matches by construction) |
| Kerrville first 1000 cms / peak | 11:00Z / 11:45Z, 8438 cms | above Kerrville: 10:05Z / 11:25Z, 8237 cms |
| Comfort at 16:00Z (validation gauge, never used as a control) | 5012 cms | 4831 cms, stage within 7 percent |
| Stage over observed rise at Hunt, Kerrville, North Fork | 1 | 1.33, 1.09, 1.02 |

Forecast skill by cutoff, for Kerrville:

| Cutoff | What Hunt was doing | Kerrville forecast for +2 h | Observed |
|---|---|---|---|
| 09:00Z | 1274 cms, rising | 121 cms at 11:00Z | 1028 |
| 09:45Z | 4061 cms, rising fast | 6352 cms at 11:45Z | 8438 |
| 10:00Z | at peak | trend keeps rising, overshoots Hunt itself | 6938 at 11:00Z |

Say the limits before anyone asks: before about 08:30Z nothing the engine ingests carries the flood (every NWM short-range cycle forecast zero at Hunt), so early forecasts show a quiet river; the wave now runs 20 minutes early at the peak; Hunt stays a third too deep because its FIM curve has the wrong shape and its gauge-height record died at 3511 cms; the linear trend has no peak detection.

## Demo script that works

All of it is prewarmed, so every step serves in one to three seconds. Keep the clock between 06:00 and 10:00Z, any horizon from 0 to 240 minutes, hindsight 06:00 to 12:00Z.

1. **Hindsight at 10:00Z**, depth band, camera on Hunt: the valley at peak. Then 11:45Z on Kerrville.
2. **Forecast from 09:00Z, +120**: almost nothing at Kerrville. Say why: the rise had barely started and no input had the rain.
3. **Forecast from 09:45Z, +120**: Kerrville flooding at the right time. Toggle the probability band to show the spread between members, then time-to-exceedance.
4. **Stale mode, 60 minutes**: same clock, data one hour old. This is what a responder with delayed feeds would have seen.
5. **3D view**, reaches coloured by rate of rise, gauge readouts. Untick "Prewarmed only" only if you want to show a cold compute (about 17 seconds).

## Compute story, if asked

Prewarmed state from disk 1.5 to 2.5 s; cold state 17 s (routing 6, mapping 7, raster write 9); a whole demo window prewarms in about 30 minutes; the incremental cost of one new cutoff in a live setting is about a minute. Pages request `precomputed=1` so a playing clock never triggers a computation.

## Where to look

- `docs/decisions/README.md`: index. 0000 data facts, 0001 predict-not-package, 0002 the information horizon p and target t, 0003 compute measurements, 0008 scenario is data, 0010 calibration and celerity.
- `docs/contracts/contract-1-physics-products.md`: products, API, error codes. `docs/specs/physics-engine-master.md`: the design.
- `docs/running-the-engine.md`: fresh-clone setup.
- Code: `src/flood/engine/forcing.py` (inputs and latency), `boundary.py` (trend), `routing.py` (Muskingum-Cunge, celerity), `calibration.py` (gauge fits), `mapping.py` (HAND), `run.py` (products, caching, prewarmed snapping), `products/tables.py` (reach and gauge tables).
- `runs/kerr-2025-07-04-replay-fe0f78/calibration.json`: the fitted scales and why two gauges were rejected.

## Questions you will get

- **Is this just replaying the data?** No. Every number at `(p, t)` uses only what was available at `p` with real latencies; Comfort was never a control and still comes out within 4 percent.
- **Why calibrate on the event you demo?** It is a rating-curve property, the same thing NOAA calibrates from historical ratings; the fits are disclosed in the run manifest and the next scenario must re-check them.
- **What would live operation need?** The ingests already use the live USGS and NWM APIs; a scheduler that prewarms each new cutoff (about a minute) and radar rainfall for the pre-onset blind spot.
- **How is the LLM meant to use it?** The `reaches` and `gauges` JSON at a prewarmed `(p, t)`: 150 rows with flow, stage, rate of rise, velocity and source, under a second.
