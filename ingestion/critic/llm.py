"""LangChain-mediated OpenAI generation for the historical critic.

`generate_critique` follows the same injectable-callable pattern
`aar.search.search_index`'s `embedder`/`embedder_factory` parameters already
establish: a caller (or test) can pass `generator` to fully replace the
default `ChatOpenAI` + `with_structured_output` call, so tests never need a
real `OPENAI_API_KEY` or network access.
"""
from __future__ import annotations

from typing import Callable, Sequence

from pydantic import BaseModel

from .prompts import SYSTEM_PROMPT, build_human_message
from .settings import Settings

Generator = Callable[..., BaseModel]


def _default_generator(
    plan: str,
    situation: str | None,
    decision_point: str | None,
    chunks: Sequence[dict],
    response_schema: type[BaseModel],
    *,
    settings: Settings,
    correction: str | None = None,
) -> BaseModel:
    # Imported lazily so importing this module (and constructing the FastAPI
    # app) never requires `langchain_openai`'s OpenAI client to validate an
    # API key; that only happens here, when a real request is actually made.
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=settings.openai_model, temperature=0, timeout=settings.request_timeout)
    structured_llm = llm.with_structured_output(response_schema)
    human_message = build_human_message(plan, situation, decision_point, chunks, correction=correction)
    return structured_llm.invoke([("system", SYSTEM_PROMPT), ("human", human_message)])


def generate_critique(
    plan: str,
    situation: str | None,
    decision_point: str | None,
    chunks: Sequence[dict],
    response_schema: type[BaseModel],
    *,
    generator: Generator | None = None,
    settings: Settings | None = None,
    correction: str | None = None,
) -> BaseModel:
    """Call the LLM (or an injected fake) to produce a structured critique.

    `settings` is consulted only by the default generator (for the
    configured OpenAI model/timeout); a caller-supplied `generator` may
    ignore it entirely. Defaults to a fresh `Settings()` (env-driven) if
    neither is given, so a caller that only overrides `generator` (as every
    offline test does) never needs to construct one.

    `correction`, when not `None`, is an additional corrective instruction
    (built by `prompts.py::build_correction_message`) for a regeneration
    attempt after the validator found a citation violation in a previous
    attempt's response; it is forwarded to `generator`/the default generator
    only when set, so an existing fake `generator` with no `correction`
    parameter (every fake generator in `historical-critic-api`'s tests)
    remains valid, unmodified, on a first, uncorrected attempt.
    """
    call = generator or _default_generator
    kwargs: dict = {"settings": settings or Settings()}
    if correction is not None:
        kwargs["correction"] = correction
    return call(plan, situation, decision_point, chunks, response_schema, **kwargs)
