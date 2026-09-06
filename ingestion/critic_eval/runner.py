"""Runs the fixed sample set through the real (or injected) critic service.

`run_critic_on_samples` calls `critic.service.run_critique` once per sample,
in-process (a direct Python call, never an HTTP request to a running
`uvicorn` process -- spec.md Assumptions, "In-process call, not HTTP",
mirroring `historical-critic-api`'s own convention for `aar.search`). A
failure on any one sample (corpus missing, no historical context retrieved,
generation error) is captured on that sample's `SampleRun` rather than
aborting the batch -- samples after a failing one still run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from critic.schemas import CritiqueRequest, CritiqueResponse
from critic.service import run_critique as _default_run_critique
from critic.settings import Settings as CriticSettings

from .settings import Settings

RunCritiqueFn = Callable[..., CritiqueResponse]


@dataclass
class SampleRun:
    """The outcome of running one fixture sample through the critic.

    Exactly one of `response`/`error` is set: a successful call populates
    `response` and leaves `error` `None`; a failed call captures the raised
    exception in `error` and leaves `response` `None`. `sample` is the
    original fixture dict, unchanged, so a report can still identify a
    failed sample by its `decision_point`/`plan` even without a response.
    """

    sample: dict
    response: CritiqueResponse | None = None
    error: Exception | None = None


def run_critic_on_samples(
    samples: list[dict],
    settings: Settings,
    *,
    run_critique: RunCritiqueFn | None = None,
) -> list[SampleRun]:
    """Run every sample through `run_critique` (defaults to
    `critic.service.run_critique`, called with a `critic.settings.Settings`
    built from `settings.aar_index_dir`), returning one `SampleRun` per
    input sample in the same order. A raised exception on one sample is
    captured on that sample's `SampleRun` and does not prevent later
    samples from running.
    """
    call = run_critique or _default_run_critique
    critic_settings = CriticSettings(aar_index_dir=settings.aar_index_dir)

    runs: list[SampleRun] = []
    for sample in samples:
        try:
            request = CritiqueRequest(**sample)
            response = call(request, critic_settings)
        except Exception as exc:  # noqa: BLE001 - captured per-sample, never aborts the batch
            runs.append(SampleRun(sample=sample, response=None, error=exc))
            continue
        runs.append(SampleRun(sample=sample, response=response, error=None))
    return runs
