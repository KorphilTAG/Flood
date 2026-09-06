"""Loads and schema-validates the fixed, checked-in sample-plan fixture.

No LLM call, no network call, no corpus read -- this module only reads and
validates a local JSON file.
"""
from __future__ import annotations

import json
from pathlib import Path


def _entry_label(index: int, entry: object) -> str:
    """A human-readable label for an offending entry: its `decision_point`
    when available (most useful for a human scanning the fixture), falling
    back to its index.
    """
    if isinstance(entry, dict):
        decision_point = entry.get("decision_point")
        if isinstance(decision_point, str) and decision_point:
            return f"entry {index} (decision_point={decision_point!r})"
    return f"entry {index}"


def load_sample_plans(path: str | Path) -> list[dict]:
    """Read and schema-validate `path`, returning one plain dict per fixture
    entry, each constructible as `critic.schemas.CritiqueRequest(**entry)`.

    The fixture file is a JSON object with a top-level `entries` list (plus
    an informational `_comment`, ignored here); each element of `entries`
    must be a JSON object with a non-empty, non-whitespace `plan`. Raises a
    `ValueError` naming the offending entry (by index and, when present, its
    `decision_point`) on a missing/blank `plan`, a non-object entry, a
    malformed/non-object top-level document, or invalid JSON.
    """
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read sample-plan fixture at {path}: {exc}") from exc

    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Sample-plan fixture at {path} is not valid JSON: {exc}") from exc

    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise ValueError(
            f"Sample-plan fixture at {path} must be a JSON object with a top-level "
            "'entries' list"
        )

    entries = document["entries"]
    if not entries:
        raise ValueError(f"Sample-plan fixture at {path} has no entries")

    samples: list[dict] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Sample-plan fixture {_entry_label(index, entry)} is not a JSON object")
        plan = entry.get("plan")
        if not isinstance(plan, str) or not plan.strip():
            raise ValueError(
                f"Sample-plan fixture {_entry_label(index, entry)} has a missing or blank 'plan'"
            )
        samples.append(dict(entry))
    return samples
