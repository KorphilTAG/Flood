"""Clock API router factory."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from flood.clock.service import ClockService

ALLOWED_SET_FIELDS = {"t", "speed", "playing"}


def make_clock_router(service: ClockService) -> APIRouter:
    """Create APIRouter for ClockService without the /clock prefix."""
    router = APIRouter()

    @router.get("")
    def get_clock() -> JSONResponse:
        return JSONResponse(status_code=200, content=service.state())

    @router.post("")
    async def set_clock(request: Request) -> JSONResponse:
        raw_body = await request.body()
        if not raw_body:
            body: dict[str, Any] = {}
        else:
            try:
                body = await request.json()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_clock", "message": f"Malformed JSON: {e}"}},
                )

        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "invalid_clock", "message": "Body must be a JSON object"}},
            )

        unknown = set(body.keys()) - ALLOWED_SET_FIELDS
        if unknown:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "invalid_clock",
                        "message": f"Unknown field(s): {', '.join(sorted(unknown))}",
                    }
                },
            )

        try:
            new_state = service.set(
                t=body.get("t"),
                speed=body.get("speed"),
                playing=body.get("playing"),
            )
            return JSONResponse(status_code=200, content=new_state)
        except ValueError as e:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "invalid_clock", "message": str(e)}},
            )

    @router.post("/reset")
    def reset_clock() -> JSONResponse:
        return JSONResponse(status_code=200, content=service.reset())

    @router.websocket("/ws")
    async def clock_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(service.state())
        q = service.subscribe()
        send_lock = asyncio.Lock()

        async def sender() -> None:
            try:
                while True:
                    msg = await q.get()
                    async with send_lock:
                        await websocket.send_json(msg)
            except (WebSocketDisconnect, RuntimeError, ConnectionResetError, asyncio.CancelledError):
                pass

        async def receiver() -> None:
            try:
                while True:
                    data = await websocket.receive_json()
                    if not isinstance(data, dict):
                        async with send_lock:
                            await websocket.send_json(
                                {
                                    "error": {
                                        "code": "invalid_clock",
                                        "message": "Body must be a JSON object",
                                    }
                                }
                            )
                        continue

                    unknown = set(data.keys()) - ALLOWED_SET_FIELDS
                    if unknown:
                        async with send_lock:
                            await websocket.send_json(
                                {
                                    "error": {
                                        "code": "invalid_clock",
                                        "message": f"Unknown field(s): {', '.join(sorted(unknown))}",
                                    }
                                }
                            )
                        continue

                    try:
                        service.set(
                            t=data.get("t"),
                            speed=data.get("speed"),
                            playing=data.get("playing"),
                        )
                    except ValueError as e:
                        async with send_lock:
                            await websocket.send_json(
                                {"error": {"code": "invalid_clock", "message": str(e)}}
                            )
            except (WebSocketDisconnect, RuntimeError, ConnectionResetError, asyncio.CancelledError):
                pass

        sender_task = asyncio.create_task(sender())
        receiver_task = asyncio.create_task(receiver())

        try:
            await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            service.unsubscribe(q)
            sender_task.cancel()
            receiver_task.cancel()

    return router
