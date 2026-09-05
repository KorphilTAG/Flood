# Flood

Flood digital twin with an outcome-grounded tactical critic — dnhacks, September 2026.

Reference scenario: the Guadalupe River flash flood of 4 July 2025 in Kerr County, Texas. The product supports training (Kerr County replay with cited tactical critique) and live rescue (real-time inundation plus outcome-grounded critique during an active response). A human commander owns every operational decision — the system critiques and synthesizes; it does not issue dispatch orders.

See [architecture.md](architecture.md) for the full design: problem statement, competitive landscape, design principles, and system architecture. Requirements live in [PRD.md](PRD.md). Team work split is only in [FeatureBreakdown.md](FeatureBreakdown.md).

Decisions are recorded one per file in [docs/decisions](decisions/README.md).

## Data sources

- OWP HAND (HUC8 12100201): `s3://ciroh-owp-hand-fim/hand_fim_4_9_9_0/` (public, no credentials)
- NOAA National Water Model (analysis and short_range, 2025-07-04): GCS bucket `national-water-model` (public)

## Status

Positioning is training and live-rescue decision support (see [PRD.md](PRD.md)).
