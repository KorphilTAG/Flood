"""Environment-driven configuration for the historical critic service.

Mirrors `src/flood/api/settings.py`'s dataclass-from-`os.environ` pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

DEFAULT_AAR_INDEX_DIR = "data/aar/library"
# A small, low-latency chat-completions-capable OpenAI model. Not a hard
# product requirement -- adjust for the hackathon demo based on
# latency/cost testing (see spec.md Assumptions).
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_TOP_K = 5


@dataclass
class Settings:
    aar_index_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AAR_INDEX_DIR", DEFAULT_AAR_INDEX_DIR))
    )
    openai_model: str = field(
        default_factory=lambda: os.environ.get("CRITIC_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    )
    request_timeout: float = field(
        default_factory=lambda: float(os.environ.get("CRITIC_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT))
    )
    default_top_k: int = field(
        default_factory=lambda: int(os.environ.get("CRITIC_DEFAULT_TOP_K", DEFAULT_TOP_K))
    )

    def __post_init__(self) -> None:
        if isinstance(self.aar_index_dir, str):
            self.aar_index_dir = Path(self.aar_index_dir)
