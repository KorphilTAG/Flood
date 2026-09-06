"""FastAPI application factory for the historical critic service.

Run from `ingestion/` (same convention as `aar`):

    uvicorn critic.app:app --reload --port 8001
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aar.models import IndexError as AarIndexError

from .facts import ImpactFactsError
from .schemas import CritiqueRequest, CritiqueResponse
from .service import CritiqueGenerationError, NoHistoricalContextError, run_critique
from .settings import Settings

logger = logging.getLogger(__name__)


def _error_body(code: str, message: str) -> dict:
    # Matches the convention used by `src/flood/api/errors.py` for
    # consistency across the two backend services -- not a hard dependency
    # on that module.
    return {"error": {"code": code, "message": message}}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application. Construction alone
    never requires a real `OPENAI_API_KEY` or a built AAR corpus -- both are
    only needed once a real `POST /v1/critique` request is made.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(title="Flood Historical Critic API", version="0.1.0")
    app.state.settings = settings

    @app.exception_handler(NoHistoricalContextError)
    async def _no_historical_context_handler(request: Request, exc: NoHistoricalContextError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_error_body("no_historical_context", str(exc)))

    @app.exception_handler(ImpactFactsError)
    async def _impact_facts_handler(request: Request, exc: ImpactFactsError) -> JSONResponse:
        # A malformed or coordinate-carrying impact document is caller input, not a
        # service fault: 422, the same class as an ungroundable request.
        return JSONResponse(status_code=422, content=_error_body("invalid_impact_document", str(exc)))

    @app.exception_handler(AarIndexError)
    async def _aar_index_error_handler(request: Request, exc: AarIndexError) -> JSONResponse:
        return JSONResponse(status_code=503, content=_error_body("aar_index_error", str(exc)))

    @app.exception_handler(CritiqueGenerationError)
    async def _critique_generation_error_handler(request: Request, exc: CritiqueGenerationError) -> JSONResponse:
        return JSONResponse(status_code=502, content=_error_body("critique_generation_failed", str(exc)))

    @app.exception_handler(RuntimeError)
    async def _runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        # aar.search.search_index raises bare RuntimeError for missing
        # dependencies (e.g. faiss-cpu) / embedder failures -- a
        # service-configuration failure, not a user input error.
        return JSONResponse(status_code=503, content=_error_body("service_unavailable", str(exc)))

    @app.exception_handler(Exception)
    async def _general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error in historical critic service")
        return JSONResponse(status_code=500, content=_error_body("internal", str(exc)))

    @app.get("/healthz")
    async def healthz() -> dict:
        # Liveness only -- no call to aar.search or any LLM client.
        return {"status": "ok"}

    @app.post("/v1/critique", response_model=CritiqueResponse)
    async def critique(payload: CritiqueRequest) -> CritiqueResponse:
        return run_critique(payload, app.state.settings)

    return app


app = create_app()
