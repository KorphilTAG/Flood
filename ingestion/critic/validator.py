"""Deterministic, dependency-free rule-checker for critique citations.

Runs as a post-processing layer after `llm.py::generate_critique` returns a
structured response, independently re-checking that every `chunk_id` the
model cited -- both in the structured `chunk_ids` fields and inline in
bracketed free-text `text` fields -- actually belongs to the request's own
retrieved chunk set (spec.md "critic-output-validator", In scope item 1).

Pure function: no LLM call, no network call, standard library `re` only.
This backstops -- and does not replace -- the existing per-request `Enum`
constraint in `schemas.py::build_structured_response_schema`.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

# The exact bracketed citation convention `prompts.py::build_human_message`
# already instructs the model to use when presenting retrieved chunks:
# "[chunk_id] excerpt ...".
_INLINE_CITATION_RE = re.compile(r"\[([^\[\]\s]+)\]")


@dataclass(frozen=True)
class CitationViolation:
    """One offending citation found in a structured critique response.

    `item_kind` is "objection" or "alternative"; `item_index` is that item's
    position within its own list; `field` is "chunk_ids" (a structured-field
    entry outside the retrieved set) or "text" (a bracketed inline token
    outside the retrieved set); `value` is the offending chunk_id/token.
    """

    item_kind: str
    item_index: int
    field: str
    value: str


def _check_items(
    item_kind: str, items: Sequence[dict], known_chunk_ids: set[str]
) -> list[CitationViolation]:
    violations: list[CitationViolation] = []
    for index, item in enumerate(items):
        for chunk_id in item.get("chunk_ids", []):
            if chunk_id not in known_chunk_ids:
                violations.append(CitationViolation(item_kind, index, "chunk_ids", chunk_id))
        text = item.get("text") or ""
        for token in _INLINE_CITATION_RE.findall(text):
            if token not in known_chunk_ids:
                violations.append(CitationViolation(item_kind, index, "text", token))
    return violations


def find_citation_violations(
    objections: Sequence[dict],
    alternatives: Sequence[dict],
    known_chunk_ids: set[str],
) -> list[CitationViolation]:
    """Return every citation violation found across `objections` and
    `alternatives`.

    Each of `objections`/`alternatives` is a sequence of
    `{"text": str, "chunk_ids": list[str]}` dicts. Empty lists are trivially
    valid (a plan may align with the historical record and cite nothing).
    Returns an empty list when every structured `chunk_ids` entry and every
    bracketed inline `[token]` in `text` is a member of `known_chunk_ids`.

    `known_chunk_ids` is a plain `set[str]` of every ID this request may cite.
    `service.py` now populates it with the union of the retrieved AAR `chunk_id`s
    and the feature IDs carried by the request's Contract 2 impact document, so a
    fabricated crossing or reach reference fails here exactly as a fabricated AAR
    chunk does (spec.md In scope item 4; PRD 6.6 output validator). Both kinds share
    one grammar, so no format branch is needed. Nothing here reads, fetches, or
    fabricates an ID.
    """
    violations = _check_items("objection", objections, known_chunk_ids)
    violations.extend(_check_items("alternative", alternatives, known_chunk_ids))
    return violations
