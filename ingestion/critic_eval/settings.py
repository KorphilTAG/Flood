"""Environment-driven configuration for the citation-quality-eval harness.

Mirrors `critic/settings.py`'s dataclass-from-`os.environ` pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

# Shared with `critic/settings.py::DEFAULT_AAR_INDEX_DIR` -- this harness
# reads the same corpus the critic service itself reads.
DEFAULT_AAR_INDEX_DIR = "data/aar/library"
# A small, low-latency chat model, same default rationale as
# `critic/settings.py::DEFAULT_OPENAI_MODEL` (spec.md Assumptions: "RAGAS
# judge model"). Deliberately a separate setting from `CRITIC_OPENAI_MODEL`
# so the judge model can be tuned independently of the critic's own
# generation model.
DEFAULT_RAGAS_JUDGE_MODEL = "gpt-4o-mini"
# spec.md's own settings.py bullet writes these two defaults with an
# "ingestion/" prefix (`ingestion/critic_eval/fixtures/sample_plans.json`,
# `ingestion/critic_eval/reports/"`), matching how the rest of spec.md always
# refers to this package from repo-root for readability. But spec.md's own
# "Run/test" section runs this harness as `cd ingestion && python -m
# critic_eval run` (mirroring `aar`/`critic`'s established convention, and
# required for `python -m critic_eval` to resolve `critic_eval` as a
# top-level package at all) -- under that cwd, a literal "ingestion/"-
# prefixed default would resolve to a nonexistent
# `ingestion/ingestion/critic_eval/...` path. Defaulting to an
# ingestion/-relative path here (no prefix) keeps the documented run command
# actually work; see changes.md Residual risk for this internal spec
# inconsistency.
DEFAULT_SAMPLE_PATH = "critic_eval/fixtures/sample_plans.json"
DEFAULT_REPORT_DIR = "critic_eval/reports/"
# RAGAS scores are 0-1. Informational report-only flags, not hard gates
# (spec.md Assumptions: "Warn thresholds").
DEFAULT_FAITHFULNESS_WARN_THRESHOLD = 0.7
DEFAULT_CONTEXT_PRECISION_WARN_THRESHOLD = 0.7


@dataclass
class Settings:
    aar_index_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AAR_INDEX_DIR", DEFAULT_AAR_INDEX_DIR))
    )
    ragas_judge_model: str = field(
        default_factory=lambda: os.environ.get("RAGAS_JUDGE_MODEL", DEFAULT_RAGAS_JUDGE_MODEL)
    )
    sample_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CRITIC_EVAL_SAMPLE_PATH", DEFAULT_SAMPLE_PATH)
        )
    )
    report_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CRITIC_EVAL_REPORT_DIR", DEFAULT_REPORT_DIR)
        )
    )
    faithfulness_warn_threshold: float = field(
        default_factory=lambda: float(
            os.environ.get(
                "CRITIC_EVAL_FAITHFULNESS_WARN_THRESHOLD", DEFAULT_FAITHFULNESS_WARN_THRESHOLD
            )
        )
    )
    context_precision_warn_threshold: float = field(
        default_factory=lambda: float(
            os.environ.get(
                "CRITIC_EVAL_CONTEXT_PRECISION_WARN_THRESHOLD",
                DEFAULT_CONTEXT_PRECISION_WARN_THRESHOLD,
            )
        )
    )

    def __post_init__(self) -> None:
        if isinstance(self.aar_index_dir, str):
            self.aar_index_dir = Path(self.aar_index_dir)
        if isinstance(self.sample_path, str):
            self.sample_path = Path(self.sample_path)
        if isinstance(self.report_dir, str):
            self.report_dir = Path(self.report_dir)
