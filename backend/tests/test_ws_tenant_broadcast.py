from __future__ import annotations

import pytest

from app.ws_service import ConnectionManager


class _DummyWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_broadcast_injects_tenant_id_and_filters_admins():
    manager = ConnectionManager()
    tenant_one_ws = _DummyWebSocket()
    tenant_two_ws = _DummyWebSocket()
    manager.admins[tenant_one_ws] = 1
    manager.admins[tenant_two_ws] = 2
    manager._machine_tenants["machine-a"] = 1

    await manager.broadcast(
        {
            "type": "file_update",
            "machine_id": "machine-a",
            "data": {"machine_id": "machine-a", "action": "modify"},
        }
    )

    assert len(tenant_one_ws.messages) == 1
    assert tenant_one_ws.messages[0]["tenant_id"] == 1
    assert tenant_one_ws.messages[0]["machine_id"] == "machine-a"
    assert tenant_two_ws.messages == []
