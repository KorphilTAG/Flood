"""LangChain boundary for the deterministic search-area estimator."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from flood.search_area.estimator import (
    DEFAULT_SEARCH_AREA_CONFIG,
    SearchAreaConfig,
    estimate_missing_person_search_area,
)


class SearchAreaToolInput(BaseModel):
    """The complete public input surface: no arbitrary incident coordinates."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    p: str | datetime | None
    t: str | datetime
    last_known_position_id: str = Field(min_length=1)


class SearchAreaTool(BaseTool):
    """Resolve a Run then delegate unchanged to deterministic engine geometry."""

    name: str = "estimate_missing_person_search_area"
    description: str = (
        "Return three uncertain, probability-ranked search-priority polygons using the Physics "
        "Engine Manning/HAND velocity proxy and declared downstream flowline topology. "
        "This does not predict a person location; relative weights are uncalibrated."
    )
    args_schema: Type[BaseModel] = SearchAreaToolInput
    run_resolver: Callable[[str], Any] | None = Field(default=None, exclude=True)
    config: SearchAreaConfig = Field(default=DEFAULT_SEARCH_AREA_CONFIG, exclude=True)

    def _run(
        self,
        run_id: str,
        p: str | datetime | None,
        t: str | datetime,
        last_known_position_id: str,
    ) -> dict[str, Any]:
        if self.run_resolver is None:
            raise RuntimeError("SearchAreaTool requires an injected run_resolver")
        run = self.run_resolver(run_id)
        return estimate_missing_person_search_area(
            run,
            p,
            t,
            last_known_position_id,
            config=self.config,
        )


def create_search_area_tool(
    run_resolver: Callable[[str], Any],
    *,
    config: SearchAreaConfig = DEFAULT_SEARCH_AREA_CONFIG,
) -> SearchAreaTool:
    """Factory for later registries to inject their RunStore lookup infrastructure."""
    return SearchAreaTool(run_resolver=run_resolver, config=config)
