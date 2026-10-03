from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agentgymnasium.services.orchestrator import run_manager

router = APIRouter()


@router.websocket("/ws/runs/{run_id}")
async def ws_run(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    try:
        async for event in run_manager.subscribe(run_id):
            await ws.send_json(event)
            if event.get("type") == "error":
                break
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except RuntimeError:
            # Socket already closed by the client.
            pass
