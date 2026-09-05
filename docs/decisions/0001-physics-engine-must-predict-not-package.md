# 0001. The physics engine must predict, not package

Status: accepted, 2026-09-05.

## Context

The architecture document describes the engine as "flow to stage via the synthetic rating curve, stage minus HAND per cell." Taken literally, that is a transformation of whatever flow series it is handed. If the flow series is the archived NWM analysis or the observed gauge record, the engine only re-renders data that already existed at the time. That is packaging, and it does not meet the product's purpose.

The requirement is stronger. Given the information a responder actually had at some moment, the engine must produce a plausible three-dimensional map of what the landscape will look like at a later moment, so responders can anticipate the degraded conditions they will meet: which roads and crossings will be under, how deep, how fast the water is moving, which structures are threatened, and how confident we are. The extrapolation from known state to future state is the product. HAND is only the last step that turns a predicted flow into a predicted surface.

Two facts from [0000](0000-verified-data-findings.md) make this hard in the reference scenario. The South Fork, where the camps sit, has no gauge, so its flow at any moment must be inferred. And NWM underpredicted this event, so leaning on NWM alone reproduces the failure we are trying to train against.

## Decision

The engine is a forecasting pipeline with HAND as its final stage. Every run is defined by a knowledge cutoff `p` and a target time `t` (see [0002](0002-information-horizon-p-and-target-t.md)). The pipeline has five stages.

**1. State estimation at `p`.** Estimate flow on every reach in the corridor using only records whose availability time is at or before `p`.

- Gauged reaches: observed discharge, or observed stage inverted through the gauge's rating.
- Ungauged reaches on a gauged levelpath: NWM analysis scaled by the observed-to-modelled ratio at the nearest gauge on that levelpath.
- Ungauged tributaries at a gauged confluence: mass balance. The South Fork at Hunt is the Hunt observation minus the North Fork observation, lagged by travel time. This is an inference from real data and is labelled as one in every output.

**2. Boundary forecasting beyond `p`.** Flow entering the network after `p` is unknown and must be extrapolated. Produce at least three members: low, middle, and high.

- Trend continuation of the observed rate of rise at each headwater and tributary input, with a relaxation toward a plateau so it does not grow without bound.
- NWM short-range lateral inflow (`qSfcLatRunoff` plus `qBucket`) from the latest cycle issued at or before `p`, scaled by the same bias ratio as stage 1.
- Stretch: rainfall-runoff from radar-estimated precipitation (MRMS QPE, archived at Iowa State's mesonet, to verify) aggregated over the NWM catchment polygons, through a simple unit hydrograph or curve-number model. This is the only path to a real forecast for an ungauged tributary before its water reaches a gauge.

**3. Channel routing from `p` to `t`.** Route the estimated and forecast inflows downstream through the NWM reach network with a Muskingum-Cunge scheme at a one to five minute step. Every parameter comes from the hydrotable already in hand: reach length, slope, and wetted area and top width as functions of discharge give wave celerity and the attenuation coefficient per reach. This is the same routing family NWM itself uses, so the routing is consistent with the rating curves. Routing is what carries water observed at Hunt to Kerrville about two hours later and to Comfort five to six hours later. That travel time is the honest lead time for downstream communities, and it matches the limitation the architecture document already states.

**4. HAND mapping of each member.** Convert routed flow per reach at `t` to depth and velocity rasters exactly as the reference algorithm does, then reduce across members to a median depth, a probability-of-inundation raster, and a first-time-exceedance raster. Velocity is the proxy described in the architecture document, with reach velocity taken as discharge over wetted area from the hydrotable and cross-checked against NWM's own velocity variable. Also emit depth times velocity as a hazard band, the standard stability metric for people and vehicles.

**5. Validation as a first-class feature.** Hindcast skill is computed and displayed, not assumed. For each cutoff `p` in the replay and each horizon, compare predicted stage at every gauge with the observed stage, and compare predicted extent with the extent HAND produces from the flows observed at `t` and with USGS high-water marks where available. The verifier frontend ([0005](0005-thin-physics-verifier-frontend.md)) shows this table. If the engine cannot beat persistence at a two-hour horizon, it is not predicting, and we say so.

### Tiers

| Tier | Content | Standing |
|---|---|---|
| 0 | HAND of flows known at `t` | Required as the mapping step and as hindsight truth. Does not satisfy this decision on its own. |
| 1 | Stages 1 to 5 above with trend and NWM-based boundary forecasts | MVP. Must ship. |
| 2 | Rainfall-driven inflow for ungauged tributaries from radar QPE | Stretch. Extends lead time upstream of the first gauge. |
| 2 | Nested two-dimensional inertial shallow-water solver on a small domain around the Hunt forks and the camps, on the lidar DEM, driven by routed hydrographs as boundary inflow, implemented in PyTorch on GPU | Stretch. Gives real velocity vectors and floodplain filling dynamics where HAND is weakest. |
| 3 | Residual correction model from the PRD | Stretch, unchanged. |

## Consequences

- The engine owner's work is dominated by stages 1 to 3, not by raster math. The raster math is a day-one deliverable; the forecasting layer is the week.
- Every data record carries two timestamps, valid time and availability time. NWM analysis for hour H is only available about an hour later, and a short-range cycle about ninety minutes after its cycle time. Replay honours these latencies so `p` means what a responder would actually have had.
- Outputs are ensembles, so the contract to the impact extractor carries a probability or a member index, not a single depth.
- We can demonstrate the value directly: set `p` to 2:00 am, show what the engine predicts for 4:00 am, then show what happened. That comparison is the product.
- Things this engine still cannot predict, to be stated in the demo: debris dams and bridge backwater, which mattered at the camps; channel avulsion; structure failure; anything on streams too small for HAND. The rating curves use a uniform Manning n of 0.06 and only 15 of 1964 catchments are calibrated, so depth uncertainty from roughness alone is material and belongs in the ensemble spread.

## Open questions

- How wide should the boundary ensemble be? Start with trend continuation at 50, 100, and 150 percent of the observed rate of rise and widen until the hindcast at 4:00 am from a `p` of 2:00 am covers the observed Hunt peak.
- Is MRMS QPE for 4 July 2025 retrievable without credentials? Verify before promising Tier 2.
- Does the two-dimensional solver fit in hackathon time? Decide only after Tier 1 hindcast skill is measured.
