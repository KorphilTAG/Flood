# Physics engine cycles: parallel run configuration

Companion to [physics-engine-master.md](physics-engine-master.md) section 12. One sub-spec per cycle lives at `pipeline/features/<slug>/spec.md` in the team template plus an "Implementer notes" section. The developer is a fast model driven from a terminal. Expect a short fix-up pass by a stronger model after every cycle, which also checks `changes.md` and the diff against the spec before merge.

## Waves

Cycles in the same wave touch disjoint files and can run at the same time in separate worktrees. A wave starts only after every cycle it depends on has merged to `master`.

| Wave | Cycles | Gate |
|---|---|---|
| 0 | C01 `engine-scaffold-contracts` | none. Freezes `src/flood/interfaces.py` and the `mini_huc` fixture that every later cycle codes against. |
| 1 | C02 `hand-ingest-cube`, C03 `hand-mapping-core`, C04 `forcing-ingest-nwm-usgs`, C05 `routing-forecast`, C08 `clock-service` | C01 merged |
| 2 | C06 `run-orchestrator-products`, C07 `engine-api`, C09 `verifier-ui`, C10 `hindcast-skill` | C06 needs C03 and C05. C07, C09, C10 start against fakes as soon as C01 has merged and integrate when C06 lands. |
| 3 | C11 `second-scenario-smoke`, C12 `terrain-cesium`, C13 `boundary-blend-short-range`, C14 `rainfall-inflow-tier2` | C11 after C06. C12 after the frontend picks Cesium. C13 and C14 after C10. |

## File ownership

A cycle may create or edit only the paths listed in its spec's "Files to change". Shared files are owned as follows and edited only by their owner. Anyone else who needs a change records it under "Residual risk" in `changes.md` and the fix-up pass makes it.

| Path | Owner |
|---|---|
| `pyproject.toml`, `.gitignore`, `src/flood/__init__.py`, `src/flood/interfaces.py`, `src/flood/contracts/**`, `src/flood/scenario.py`, `src/flood/timegrid.py`, `src/flood/timing.py`, `src/flood/engine/cube.py`, `tests/conftest.py`, `tests/fixtures/mini_huc/**` | C01 |
| `src/flood/cli.py` | C01 creates it with one subcommand registry; each later cycle adds exactly one `register_<name>(subparsers)` call at the marked line and its own `src/flood/cli_<name>.py` module |
| `src/flood/ingest/hand.py`, `hydrotable.py`, `network.py` | C02 |
| `src/flood/engine/rating.py`, `mapping.py`, `ensemble.py`, `src/flood/products/raster.py` | C03 |
| `src/flood/ingest/nwm.py`, `usgs.py`, `src/flood/engine/forcing.py` | C04 |
| `src/flood/engine/routing.py`, `boundary.py` | C05 |
| `src/flood/engine/run.py`, `src/flood/products/tables.py`, `manifest.py` | C06 |
| `src/flood/api/app.py`, `runs.py`, `scenarios.py` | C07 |
| `src/flood/clock/**`, `src/flood/api/clock.py` | C08 |
| `src/flood/verifier/**` | C09 |
| `src/flood/skill/**` | C10 |
| `scenarios/*.json` other than Kerr | C11 |

Tests: each cycle owns `tests/test_<its module names>.py` only.

## Interface freeze

`src/flood/interfaces.py` is written by C01 and frozen. It holds the dataclasses, protocols, and constants named in the C01 spec. Later cycles import from it and never edit it. If an interface is insufficient, the cycle implements what it can, notes the gap in `changes.md`, and the fix-up pass extends the interface in a backward-compatible way before the next wave.

## Branches and worktrees

Branch per cycle: `feature/<slug>`. Worktree per cycle as a sibling directory so several developers run at once:

```bash
git -C C:/Users/splat/Desktop/Flood worktree add ../Flood-<slug> -b feature/<slug> master
```

Each worktree needs its own environment:

```bash
cd ../Flood-<slug> && py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
```

Merge order within a wave does not matter because files are disjoint. Merge with `git merge --no-ff feature/<slug>` on `master`, run `pytest`, push. Delete the worktree after merge: `git worktree remove ../Flood-<slug>`.

Never `git rebase` a `master` that contains these merge commits; rebase flattens them and re-raises every resolved conflict. To pick up teammates' work use `git fetch` then `git merge origin/master` (or `git pull --no-rebase`). Several cycles may also run in one worktree if the terminals are started there by mistake; it works because the files are disjoint, but the combined branch then merges as one commit.

## Per-cycle procedure

1. Confirm the wave gate has merged. Create the worktree and environment.
2. Copy `pipeline/templates/changes.md` to `pipeline/features/<slug>/changes.md`.
3. Launch the developer in the worktree with this instruction, verbatim, followed by the absolute path of the spec:

   > Implement exactly the spec at the path below. Read it in full first, then read `src/flood/interfaces.py` and the files the spec names. Follow "Files to change" and "Implementer notes" literally: exact paths, signatures, and test names. Do not edit files you do not own; record any needed change under Residual risk in changes.md. No scenario constants in code; everything comes from the scenario file. Run `pytest` before finishing. Fill `pipeline/features/<slug>/changes.md`. Do not commit.

4. Fix-up pass: a stronger model checks the real diff and file contents against `spec.md` (not only `changes.md`'s self-report), addresses anything missing or incorrect, reruns `pytest`, commits on the feature branch.
5. Merge to `master`, push, remove the worktree.

## Definition of done for the MVP path

C01 through C11 merged, `pytest` green on `master`, the Kerr run serves every contract 1 endpoint, the verifier shows the skill table, and decision 0003 has real measurements.
