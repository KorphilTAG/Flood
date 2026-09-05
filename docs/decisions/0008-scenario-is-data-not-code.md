# 0008. Scenario is data, never code

Status: accepted, 2026-09-05.

## Context

Reviewing the physics schema raised the question of whether we are building a demo or a product. The docs claim a product that a rural county could use, with the Kerr County replay as its first scenario. The physics stack supports that claim: HAND FIM covers every HUC8 in the country, NWM covers CONUS, USGS gauges are national. The risk is that each teammate hardcodes Kerr County into their own layer and the product claim quietly becomes untrue.

## Decision

Everything specific to an incident, a basin, or an exposure dataset lives in one scenario file. Code reads the scenario; code never contains it.

- **Scenario file** (`scenarios/<scenario_id>.json`, schema in `docs/contracts/schemas/scenario.schema.json`) declares the HUC8s, the corridor AOI, the gauge sites, mass-balance junction inferences such as the South Fork at Hunt, the replay window, forcing defaults, scenario overrides such as a gauge outage, the exposure layer registry, training decision points, and scripted last-known positions.
- **Exposure layer registry.** Each exposure layer declares its own `layer_id`, source file, ID field, geometry type, and impact thresholds. The impact extractor iterates the registry. No layer name appears in code.
- **Feature ID namespace.** Every feature reference is `<layer_id>:<source_id>`. The physics contract reserves two layer IDs that are national namespaces: `reach` (NWM feature_id) and `gauge` (USGS site number). The corpus reserves `aar` for citation chunks. All other layer IDs come from the scenario's registry.
- **Generality acceptance test.** Preparing a second HUC8 (Wimberley 2015 on the Blanco is the natural candidate) must require editing only a scenario file. Run this once before the demo.
- **Review rule.** A literal basin name, site number, HUC code, camp name, or date in code outside the scenario file and its tests is a bug.

## Where generalisation stops

Not in scope, and the cut list already agrees: multiple concurrent users or sessions, live ingestion for arbitrary data sources, basins without HAND coverage. Live mode for a single basin remains on the cut list as documented.

## Consequences

- One config loader and one registry loop replace hardcoded names. About an hour of work, paid once.
- Training-mode content (decision points, scripted call data) is scenario data consumed through contract 4, not prompt text embedded in the LLM layer.
- Sub-specs handed to the implementer must state this rule explicitly, since a fast model will otherwise inline the demo constants.
