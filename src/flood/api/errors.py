"""Structured error definitions and response helpers."""
from __future__ import annotations

from typing import Any
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from flood.interfaces import TimeGridError


class APIError(Exception):
    """Base API exception with HTTP status code and contract error code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Format exact contract error response: {"error": {"code": str, "message": str}}."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


async def timegrid_error_handler(request: Request, exc: TimeGridError) -> JSONResponse:
    return error_response(400, exc.code, str(exc))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(400, "invalid_request", str(exc))


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    return error_response(exc.status_code, code, str(exc.detail))


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "internal", str(exc))
