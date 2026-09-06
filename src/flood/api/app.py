"""FastAPI application factory for the Flood Engine API."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from flood.api.errors import (
    APIError,
    api_error_handler,
    general_exception_handler,
    http_exception_handler,
    timegrid_error_handler,
    validation_error_handler,
)
from flood.api.runs import router as runs_router
from flood.api.scenarios import router as scenarios_router
from flood.api.settings import Settings
from flood.interfaces import TimeGridError
from flood.scenario import load_scenario

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, store: Any = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    if store is None:
        try:
            from flood.engine.run import RunStore
            store = RunStore(settings.runs_dir, settings.data_dir)
        except ImportError:
            logger.warning("flood.engine.run not importable; engine is unavailable")
            store = None

    # Clock initialization
    clock_service = None
    start_env = os.environ.get("FLOOD_CLOCK_START")
    end_env = os.environ.get("FLOOD_CLOCK_END")

    if start_env and end_env:
        record_start: Any = start_env
        record_end: Any = end_env
    else:
        record_start = None
        record_end = None
        if settings.scenarios_dir.is_dir():
            for p in sorted(settings.scenarios_dir.glob("*.json")):
                try:
                    sc = load_scenario(p)
                    record_start = sc.hydrology.record.start
                    record_end = sc.hydrology.record.end
                    break
                except Exception:
                    continue
        if record_start is None or record_end is None:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            record_start = now
            record_end = now + timedelta(days=1)

    try:
        from flood.clock.service import ClockService
        clock_service = ClockService(record_start, record_end)
    except ImportError:
        logger.warning("flood.clock.service not importable; clock service unavailable")
        clock_service = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if clock_service is not None:
            clock_service.start()
        yield
        if clock_service is not None:
            clock_service.stop()

    app = FastAPI(
        title="Flood Engine API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.clock_service = clock_service

    # Map front ends on another origin fetch JSON, PNG overlays (WebGL textures need CORS
    # headers or the browser refuses to upload the image) and byte ranges of the COGs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Bounds-3857", "X-Bounds-4326", "Content-Range", "Accept-Ranges", "Content-Length"],
        max_age=600,
    )

    # Request timing logger middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        # Verifier pages are edited in place; without this browsers cache the module
        # scripts heuristically and keep running stale code after a deploy.
        if request.url.path.startswith("/verifier"):
            response.headers["Cache-Control"] = "no-cache"
        log_line = json.dumps({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        })
        logger.info(log_line)
        return response

    # Exception handlers
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(TimeGridError, timegrid_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Mount routers
    app.include_router(scenarios_router)
    app.include_router(runs_router)

    if clock_service is not None:
        try:
            from flood.api.clock import make_clock_router
            app.include_router(make_clock_router(clock_service), prefix="/clock")
        except ImportError:
            logger.warning("flood.api.clock not importable; clock router not mounted")

    # Static verifier mount if directory exists
    package_dir = Path(__file__).resolve().parent.parent
    verifier_static = package_dir / "verifier" / "static"
    if verifier_static.is_dir():
        app.mount("/verifier", StaticFiles(directory=str(verifier_static), html=True), name="verifier")

    return app
