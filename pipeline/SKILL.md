---
name: pipeline
description: >-
  Runs the Flood feature pipeline: plan (Fable) writes a spec from the PRD and
  FeatureBreakdown, developer (Sonnet) implements it and writes changes.md.
  Use only when the user invokes /pipeline, $pipeline, or explicitly asks to
  run the feature pipeline. Do not use for the product's AAR/data pipeline.
disable-model-invocation: true
---

# Feature pipeline

Orchestrate two isolated agents, in order, to ship one feature. Do not implement the feature yourself. Do not run the two stages in one context. Do not start the later stage until the earlier stage's artifact exists on disk.

## Required input

The user must name a feature. Examples: `/pipeline clock service`, `$pipeline stub the four JSON contracts`.

If the feature is missing or ambiguous, ask one clarifying question and stop. Do not invent a feature.

## Artifacts

Create a kebab-case slug from the feature (lowercase, hyphens, max 40 characters).

```
pipeline/features/<slug>/
  spec.md       # plan agent
  changes.md    # developer agent
```

Copy the matching file from `pipeline/templates/` into that folder before each stage writes it. Never overwrite a completed `spec.md` once the developer has started.

## Product references (plan agent only)

The plan agent must read these before writing the spec:

- `docs/PRD.md`
- `docs/FeatureBreakdown.md`
- `docs/architecture.md`
- `docs/README.md`

Later agents read the spec, not the PRD, unless a spec section is incomplete.

## Models

| Stage | Agent | Claude / Cursor | Codex |
|---|---|---|---|
| 1. Plan | `pipeline-plan` | Fable (`claude-fable-5`). Fallback: newest Opus. | Most capable available GPT (prefer GPT-5.4+ / Codex Max). |
| 2. Develop | `pipeline-dev` | Sonnet (`claude-sonnet-5`) | Default Codex coding model |

Pin these models on the subagent call. Do not inherit the parent model. If Fable is unavailable, say so and use Opus — do not silently drop to a fast or mini model for planning.

## Sequence

Copy this checklist and complete it in order:

```
Pipeline:
- [ ] Slug chosen, folder created
- [ ] Plan finished; spec.md exists and has all required sections
- [ ] Developer finished; changes.md exists
- [ ] Result reported to the user
```

### 1. Plan

Launch `pipeline-plan` as a **foreground** subagent. Pass:

- The user's feature request, verbatim
- The slug and the output path `pipeline/features/<slug>/spec.md`
- Instruction to follow `pipeline/agents/plan.md` and fill `pipeline/templates/spec.md`
- Instruction to use the product references above

Wait until it returns. Then confirm `spec.md` exists and contains `# Feature spec`, `## Acceptance criteria`, and `## Out of scope`. If any are missing, re-run only the plan agent with the gap named. Do not continue.

### 2. Develop

Launch `pipeline-dev` as a **foreground** subagent. Pass:

- Absolute path to `spec.md`
- Output path `pipeline/features/<slug>/changes.md`
- Instruction to follow `pipeline/agents/developer.md` and fill `pipeline/templates/changes.md`
- Instruction to implement only what the spec requires

Wait until it returns. Then confirm `changes.md` exists and lists at least one touched path. If the spec said the feature is already present, `changes.md` may list zero code files but must still explain that. Do not continue without `changes.md`.

### 3. Report

Summarize what `changes.md` says was implemented, and flag anything it marks as skipped or as a residual risk. Do not start a fix loop unless the user asks. Do not commit or push.

## How to launch agents

Use the named custom agents when they are registered. If a harness cannot see them, launch a general-purpose subagent and paste the matching file from `pipeline/agents/` as the system prompt, with the model from the table.

### Cursor

Use the Task tool with `subagent_type` set to `pipeline-plan`, then `pipeline-dev`. Set `run_in_background` to false. Pass `model` as `claude-fable-5` for plan and `claude-sonnet-5` for develop. Do not pass a different model — those agents set `force-default-model: true`.

### Claude Code

Delegate with the Agent tool to `pipeline-plan`, then `pipeline-dev`. Those definitions already pin `model: fable` and `model: sonnet`. Do not override.

### Codex

If custom agents are available, run `$pipeline-plan`, then `$pipeline-dev` (or the harness equivalent). Otherwise, execute each file in `pipeline/agents/` as a separate agent turn, in that order, switching models per the table. Do not keep plan-stage PRD context in the developer turn.

## Hard rules

- Sequential only. Never launch developer in parallel with plan.
- The parent agent does not edit application code or specs except to create the feature folder and copy templates.
- Stop the pipeline if a stage fails to write its artifact.
- This skill is the product **feature** pipeline. It is not the AAR extraction pipeline in the architecture doc.
