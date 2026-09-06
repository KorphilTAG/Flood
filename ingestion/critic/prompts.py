"""Prompt templates encoding the critic's grounding rules and non-goals."""
from __future__ import annotations

from typing import Sequence

SYSTEM_PROMPT = (
    "You are a historical-critique assistant for flood emergency response training. "
    "You are given a trainee's proposed plan and a set of historical Texas flood "
    "after-action report (AAR) excerpts retrieved specifically for this request. "
    "Your job is to raise objections and suggest alternatives grounded in that "
    "historical record.\n\n"
    "Rules:\n"
    "- Cite only the AAR excerpts you were given, by their exact chunk ID. "
    "Never invent a chunk ID, and never cite a chunk ID that was not provided to you.\n"
    "- Every objection and every alternative must cite at least one real chunk ID; "
    "never make a bare, uncited claim.\n"
    "- Never issue a dispatch order, evacuation order, or any operational instruction. "
    "You are a critic, not a dispatcher -- the human commander remains the decision "
    "owner. Objections and alternatives are for a human to weigh, never a command.\n"
    "- If the plan matches historical best practice, `objections` and `alternatives` "
    "may both be empty lists. Do not invent a criticism just to fill them."
)


def _render_chunk(chunk: dict) -> str:
    return (
        f"[{chunk['chunk_id']}] {chunk['excerpt']} "
        f"(hazard={chunk.get('hazard')}, phase={chunk.get('phase')}, "
        f"tactic={chunk.get('tactic')}, outcome={chunk.get('outcome')})"
    )


def build_human_message(
    plan: str,
    situation: str | None,
    decision_point: str | None,
    chunks: Sequence[dict],
) -> str:
    """Render the plan/situation/decision-point text plus every retrieved
    chunk, formatted so the model can cite each one by its exact chunk ID.
    """
    lines: list[str] = []
    if decision_point:
        lines.append(f"Decision point: {decision_point}")
    if situation:
        lines.append(f"Situation: {situation}")
    lines.append(f"Trainee's proposed plan: {plan}")
    lines.append("")
    lines.append(
        "Retrieved historical AAR excerpts (cite only these, by their exact chunk ID "
        "in brackets):"
    )
    for chunk in chunks:
        lines.append(_render_chunk(chunk))
    return "\n".join(lines)
