---
name: pipeline
description: >-
  Runs the Flood feature pipeline: plan (Fable) writes a spec from the PRD and
  FeatureBreakdown, developer (Sonnet) implements it and writes changes.md,
  reviewer (Sonnet) checks the spec against the diff. Use only when the user
  invokes /pipeline, $pipeline, or explicitly asks to run the feature pipeline.
  Do not use for the product's AAR/data pipeline.
disable-model-invocation: true
---

Read and execute every instruction in [pipeline/SKILL.md](../../../pipeline/SKILL.md). Do not skip that file. Do not implement the feature in this conversation.
