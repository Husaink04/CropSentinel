"""WebSocket router."""

from fastapi import APIRouter, WebSocket

from app.ws_service import handle_admin_websocket, handle_agent_websocket

router = APIRouter()


@router.websocket("/ws/agent/{machine_id}")
async def agent_websocket(websocket: WebSocket, machine_id: str):
    await handle_agent_websocket(websocket, machine_id)


@router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    await handle_admin_websocket(websocket, websocket.app)
