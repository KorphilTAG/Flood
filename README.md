# Flood

Flood digital twin with an outcome-grounded tactical critic — dnhacks, September 2026.

Reference scenario: the Guadalupe River flash flood of 4 July 2025 in Kerr County, Texas. The product replays that timeline and critiques tactical decisions (training mode) or red-teams a draft incident action plan (pre-deployment mode) against projected inundation and an after-action-report corpus. It is not a live tactical recommender — a human commander owns every operational decision.

See [architecture.md](architecture.md) for the full design: problem statement, competitive landscape, design principles, and system architecture.

## Data sources

- OWP HAND (HUC8 12100201): `s3://ciroh-owp-hand-fim/hand_fim_4_9_9_0/` (public, no credentials)
- NOAA National Water Model (analysis and short_range, 2025-07-04): GCS bucket `national-water-model` (public)

## Status

Scope (training/tactical-critic replay vs. live rescue decision-support) is still being finalized among the team as of 2026-09-05.
