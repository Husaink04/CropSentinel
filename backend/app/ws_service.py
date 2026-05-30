"""Connection management and WebSocket event handling."""

import asyncio
import logging
import os
from typing import Dict

import jwt
from fastapi.encoders import jsonable_encoder
from fastapi import WebSocket, WebSocketDisconnect

import redis_bus
from database import clear_tenant_context, db, set_tenant_context, utcnow, utcnow_iso
from licensing import has_feature as license_has_feature
from webrtc_manager import webrtc
from app.core import ALGORITHM, SECRET_KEY, VALID_ROLES, agent_public_config, agent_ws_key_ok, can_access_machine, has_permission
from app.event_bus import EventTopics, internal_event_bus
from app.ops_metrics import ops_metrics
from app.services.activity_ingest_service import ActivityValidationError, activity_ingest_service
from app.services.phishing_service import phishing_service
from app.services.session_service import normalize_session_kind

logger = logging.getLogger("cropsentinel")

OFFLINE_GRACE_SECONDS = 45


class ConnectionManager:
    def __init__(self):
        self.agents: Dict[str, WebSocket] = {}
        self.admins: Dict[WebSocket, int] = {}
        self._offline_tasks: Dict[str, asyncio.Task] = {}
        self._machine_tenants: Dict[str, int] = {}

    async def connect_agent(self, ws: WebSocket, machine_id: str):
        await ws.accept()
        old_ws = self.agents.get(machine_id)
        if old_ws is not None and old_ws is not ws:
            try:
                await old_ws.close()
            except Exception:
                pass
        task = self._offline_tasks.pop(machine_id, None)
        if task and not task.done():
            task.cancel()
        self.agents[machine_id] = ws
        tenant_id = db.get_machine_tenant_id(machine_id) or 1
        self._machine_tenants[machine_id] = int(tenant_id)
        self._sync_metrics()
        await redis_bus.mark_online(machine_id)
        machine = db.get_machine(machine_id) or {}
        count = (await redis_bus.get_online_count()) if redis_bus.enabled() else len(self.agents)
        await self.broadcast(
            {
                "type": "machine_online",
                "machine_id": machine_id,
                "hostname": machine.get("hostname", machine_id),
                "online_count": count,
            }
        )

    async def connect_admin(self, ws: WebSocket, tenant_id: int):
        await ws.accept()
        self.admins[ws] = int(tenant_id)
        self._sync_metrics()

    def disconnect_agent(self, machine_id: str):
        self.agents.pop(machine_id, None)
        self._sync_metrics()
        asyncio.create_task(redis_bus.mark_offline(machine_id))

    def disconnect_admin(self, ws: WebSocket):
        self.admins.pop(ws, None)
        self._sync_metrics()

    async def schedule_offline(self, machine_id: str):
        tenant_id = int(self._machine_tenants.get(machine_id) or db.get_machine_tenant_id(machine_id) or 1)
        set_tenant_context(tenant_id)
        try:
            machine = db.get_machine(machine_id) or {}
        finally:
            clear_tenant_context()
        hostname = machine.get("hostname", machine_id)
        await self.broadcast({"type": "machine_unstable", "machine_id": machine_id, "hostname": hostname})

        async def _fire_offline():
            await asyncio.sleep(OFFLINE_GRACE_SECONDS)
            still_gone = machine_id not in self.agents
            if still_gone and redis_bus.enabled():
                still_gone = machine_id not in await redis_bus.get_online_set()
                if still_gone:
                    set_tenant_context(tenant_id)
                    try:
                        db.update_machine_field(machine_id, "last_seen", utcnow())
                    finally:
                        clear_tenant_context()
                    count = await redis_bus.get_online_count() if redis_bus.enabled() else len(self.agents)
                    await self.broadcast(
                        {
                            "type": "machine_offline",
                            "tenant_id": tenant_id,
                            "machine_id": machine_id,
                            "hostname": hostname,
                            "online_count": count,
                        }
                    )
                set_tenant_context(tenant_id)
                try:
                    alerts = db.evaluate_alerts_for_offline(machine_id)
                finally:
                    clear_tenant_context()
                for alert in alerts:
                    await self.broadcast({"type": "new_alert", "tenant_id": tenant_id, **alert})
                for session_id in webrtc.end_sessions_for_machine(machine_id):
                    await self.broadcast(
                        {
                            "type": "webrtc_ended",
                            "tenant_id": tenant_id,
                            "session_id": session_id,
                            "reason": "agent_disconnected",
                            "machine_id": machine_id,
                        }
                    )
            self._offline_tasks.pop(machine_id, None)
            self._machine_tenants.pop(machine_id, None)

        self._offline_tasks[machine_id] = asyncio.create_task(_fire_offline())

    def _machine_tenant(self, machine_id: str) -> int:
        if not machine_id:
            return 1
        cached = self._machine_tenants.get(machine_id)
        if cached is not None:
            return int(cached)
        tid = int(db.get_machine_tenant_id(machine_id) or 1)
        self._machine_tenants[machine_id] = tid
        return tid

    def _event_tenant(self, data: dict):
        if "tenant_id" in data and data.get("tenant_id") is not None:
            try:
                return int(data.get("tenant_id"))
            except Exception:
                pass
        machine_id = data.get("machine_id") or ((data.get("data") or {}).get("machine_id"))
        if machine_id:
            return self._machine_tenant(machine_id)
        return None

    async def broadcast(self, data: dict):
        payload = dict(data or {})
        event_tenant = self._event_tenant(payload)
        if event_tenant is not None and payload.get("tenant_id") is None:
            payload["tenant_id"] = int(event_tenant)
        if redis_bus.enabled():
            await redis_bus.publish_broadcast(payload)
        else:
            await self._local_broadcast(payload)

    async def _local_broadcast(self, data: dict):
        event_tenant = self._event_tenant(data)
        dead = []
        payload = jsonable_encoder(data)
        for ws, admin_tenant in self.admins.items():
            if event_tenant is not None and int(admin_tenant) != int(event_tenant):
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.admins.pop(ws, None)

    async def send_to_agent(self, machine_id: str, data: dict) -> bool:
        ws = self.agents.get(machine_id)
        if ws:
            try:
                await ws.send_json(jsonable_encoder(data))
                return True
            except Exception:
                self.agents.pop(machine_id, None)
        if redis_bus.enabled():
            await redis_bus.publish_agent_cmd(machine_id, data)
            return True
        return False

    async def _local_deliver_to_agent(self, machine_id: str, data: dict) -> None:
        ws = self.agents.get(machine_id)
        if ws:
            try:
                await ws.send_json(jsonable_encoder(data))
            except Exception:
                self.agents.pop(machine_id, None)

    def online(self) -> list:
        return list(self.agents.keys())

    def online_for_tenant(self, tenant_id: int) -> list:
        return [mid for mid in self.agents.keys() if self._machine_tenant(mid) == int(tenant_id)]

    def _sync_metrics(self) -> None:
        ops_metrics.set_realtime_counts(agents=len(self.agents), admins=len(self.admins))


manager = ConnectionManager()


async def handle_remote_command(machine_id: str, data: dict):
    internal_event_bus.publish(
        topic=EventTopics.SYSTEM_EVENTS,
        event_type="remote.command.result",
        tenant_id=db.get_machine_tenant_id(machine_id) or 1,
        machine_id=machine_id,
        payload=data,
    )
    await manager.broadcast(
        {
            "type": "remote_result",
            "machine_id": machine_id,
            "action": data.get("action", ""),
            "status": data.get("status", "sent"),
            "detail": data.get("detail", ""),
        }
    )


async def handle_agent_websocket(websocket: WebSocket, machine_id: str):
    if not agent_ws_key_ok(websocket):
        await websocket.close(code=4401)
        return
    tid = db.get_machine_tenant_id(machine_id)
    enroll_token = (
        websocket.headers.get("x-cropsentinel-enroll-token")
        or websocket.headers.get("X-CropSentinel-Enroll-Token")
        or websocket.headers.get("x-croppro-enroll-token")
        or websocket.headers.get("X-CropPro-Enroll-Token")
    )
    if tid and enroll_token:
        tenant = db.get_tenant_by_enrollment_token(enroll_token.strip())
        if tenant and int(tenant["id"]) != int(tid):
                logger.warning(
                    "Agent WS rejected: machine %s belongs to tenant %s but header token maps to tenant %s",
                    machine_id,
                    tid,
                    tenant["id"],
                )
                await websocket.close(code=4403)
                return

    resolved_tid = int(tid or 1)
    if not tid and enroll_token:
        tenant = db.get_tenant_by_enrollment_token(enroll_token.strip())
        if tenant:
            resolved_tid = int(tenant["id"])

    set_tenant_context(resolved_tid)
    try:
        await manager.connect_agent(websocket, machine_id)
        db.update_machine_field(machine_id, "last_seen", utcnow())
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            queue_id = data.get("_queue_id")
            try:
                if msg_type == "browser_activity":
                    result = activity_ingest_service.ingest_browser(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "app_activity":
                    result = activity_ingest_service.ingest_application(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "screenshot":
                    result = activity_ingest_service.ingest_screenshot(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "remote_command":
                    await handle_remote_command(machine_id, data)
                elif msg_type == "webrtc_offer":
                    session_id = data.get("session_id", "")
                    if webrtc.get_session(session_id):
                        await webrtc.relay_to_admin(
                            session_id,
                            {"type": "webrtc_offer", "tenant_id": resolved_tid, "session_id": session_id, "sdp": data.get("sdp")},
                        )
                elif msg_type == "webrtc_ice":
                    session_id = data.get("session_id", "")
                    await webrtc.relay_to_admin(
                        session_id,
                        {"type": "webrtc_ice_agent", "tenant_id": resolved_tid, "session_id": session_id, "candidate": data.get("candidate")},
                    )
                elif msg_type == "webrtc_end":
                    await webrtc.notify_admin_ended(data.get("session_id", ""), reason="agent_closed")
                elif msg_type == "input_activity":
                    result = activity_ingest_service.ingest_input(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "network_activity":
                    result = activity_ingest_service.ingest_network(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "file_activity":
                    result = activity_ingest_service.ingest_file(machine_id, data)
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                elif msg_type == "dlp_alert_activity":
                    data["machine_id"] = machine_id
                    event_id = db.insert_dlp_event(data)
                    internal_event_bus.publish(
                        topic=EventTopics.DLP_EVENTS,
                        event_type="dlp.alert.ingested",
                        tenant_id=resolved_tid,
                        machine_id=machine_id,
                        payload={**data, "id": event_id},
                    )
                    risk = data.get("risk_level", data.get("risk", "low"))
                    if risk in ("medium", "high"):
                        severity = "critical" if risk == "high" else "warning"
                        machine = db.get_machine(machine_id) or {}
                        findings = ", ".join(f"{item['type']}({item['count']})" for item in data.get("findings", []))
                        alert_id = db.create_alert_log(
                            {
                                "rule_id": 0,
                                "rule_name": "DLP Auto-Alert",
                                "machine_id": machine_id,
                                "hostname": machine.get("hostname", machine_id),
                                "severity": severity,
                                "message": f"DLP {risk.upper()}: Sensitive data in {data.get('file_name', 'unknown')}",
                                "details": f"File: {data.get('file_path', '')} | Findings: {findings}",
                            }
                        )
                        await manager.broadcast(
                            {
                                "type": "new_alert",
                                "tenant_id": resolved_tid,
                                "id": alert_id,
                                "severity": severity,
                                "machine_id": machine_id,
                                "message": f"DLP {risk.upper()}: {data.get('file_name', '')}",
                            }
                        )
                    await manager.broadcast({"type": "dlp_update", "machine_id": machine_id, "data": {**data, "id": event_id}})
                elif msg_type == "phishing_alert_activity":
                    data["machine_id"] = machine_id
                    tenant_id = manager._machine_tenant(machine_id)
                    result = phishing_service.ingest_event(tenant_id, data)
                    internal_event_bus.publish(
                        topic=EventTopics.PHISHING_EVENTS,
                        event_type="phishing.alert.ingested",
                        tenant_id=tenant_id,
                        machine_id=machine_id,
                        payload={**result.get("event", {}), "id": result.get("event_id")},
                    )
                    incident = result.get("incident") or {}
                    await manager.broadcast({"type": "phishing_update", "tenant_id": tenant_id, "machine_id": machine_id, "data": {**result["event"], "id": result["event_id"]}})
                    if incident:
                        await manager.broadcast({"type": "phishing_incident_update", "tenant_id": tenant_id, "machine_id": machine_id, "data": incident})
                        if incident.get("_new_alert"):
                            machine = db.get_machine(machine_id) or {}
                            set_tenant_context(tenant_id)
                            try:
                                alert_id = db.create_alert_log(
                                    {
                                        "rule_id": 0,
                                        "rule_name": "Phishing Auto-Alert",
                                        "machine_id": machine_id,
                                        "hostname": machine.get("hostname", machine_id),
                                        "severity": incident.get("severity", "warning"),
                                        "message": incident.get("title", "Phishing incident"),
                                        "details": incident.get("summary", ""),
                                    }
                                )
                            finally:
                                clear_tenant_context()
                            await manager.broadcast(
                                {
                                    "type": "new_alert",
                                    "tenant_id": tenant_id,
                                    "id": alert_id,
                                    "severity": incident.get("severity", "warning"),
                                    "machine_id": machine_id,
                                    "message": incident.get("title", "Phishing incident"),
                                }
                            )
                elif msg_type == "heartbeat":
                    result = activity_ingest_service.ingest_heartbeat(
                        machine_id,
                        data,
                        config=agent_public_config(),
                    )
                    for event in result.broadcasts:
                        await manager.broadcast(event)
                    await websocket.send_json(
                        jsonable_encoder({"type": "ack", "server_time": result.response.get("server_time", utcnow_iso()), "config": result.response.get("config", agent_public_config())})
                    )
                if queue_id:
                    await websocket.send_json(jsonable_encoder({"type": "event_ack", "ack_ids": [queue_id]}))
            except ActivityValidationError as exc:
                logger.warning("Rejected %s from %s: %s: %s", msg_type, machine_id, exc.code, exc.message)
                if queue_id:
                    try:
                        await websocket.send_json(jsonable_encoder({"type": "event_ack", "ack_ids": [queue_id], "error": f"{exc.code}: {exc.message}"}))
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("Error processing %s from %s: %s", msg_type, machine_id, exc)
                if queue_id:
                    try:
                        await websocket.send_json(jsonable_encoder({"type": "event_ack", "ack_ids": [queue_id], "error": str(exc)}))
                    except Exception:
                        pass
    except WebSocketDisconnect:
        manager.disconnect_agent(machine_id)
        await manager.schedule_offline(machine_id)
    finally:
        clear_tenant_context()


async def handle_admin_websocket(websocket: WebSocket, app):
    token = websocket.query_params.get("token", "")
    if not token:
        logger.warning("admin_ws_auth_failed reason_code=missing_token path=%s", str(websocket.url.path))
        await websocket.close(code=4001)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role", "") not in VALID_ROLES:
            logger.warning(
                "admin_ws_auth_failed reason_code=invalid_role path=%s role=%s",
                str(websocket.url.path),
                payload.get("role", ""),
            )
            await websocket.close(code=4003)
            return
    except Exception as exc:
        logger.warning("admin_ws_auth_failed reason_code=invalid_token path=%s detail=%s", str(websocket.url.path), exc)
        await websocket.close(code=4001)
        return

    admin_tenant_id = int(payload.get("tenant_id") or 1)
    admin_user = payload
    await manager.connect_admin(websocket, admin_tenant_id)
    try:
        await websocket.send_json(jsonable_encoder({"type": "online_machines", "machines": manager.online_for_tenant(admin_tenant_id)}))
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "request_screenshot":
                machine_id = data.get("machine_id", "")
                if not has_permission(admin_user, "screenshots.view"):
                    await websocket.send_json(jsonable_encoder({"type": "error", "message": "Permission denied: screenshots.view"}))
                    continue
                if manager._machine_tenant(machine_id) != admin_tenant_id:
                    await websocket.send_json(jsonable_encoder({"type": "error", "message": "Forbidden for this tenant"}))
                    continue
                if not can_access_machine(admin_user, machine_id):
                    await websocket.send_json(jsonable_encoder({"type": "error", "message": "No access to this machine"}))
                    continue
                sent = await manager.send_to_agent(data["machine_id"], {"type": "take_screenshot"})
                if not sent:
                    await websocket.send_json(jsonable_encoder({"type": "error", "message": "Machine offline"}))
            elif msg_type == "webrtc_request":
                machine_id = data.get("machine_id", "")
                session_kind = normalize_session_kind(data.get("session_kind", "live"))
                required_perm = "remote.access" if session_kind == "remote" else "screenshots.view"
                if not has_permission(admin_user, required_perm):
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_error", "message": f"Permission denied: {required_perm}"}))
                    continue
                if manager._machine_tenant(machine_id) != admin_tenant_id:
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_error", "message": "Forbidden for this tenant"}))
                    continue
                if not can_access_machine(admin_user, machine_id):
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_error", "message": "No access to this machine"}))
                    continue
                if session_kind == "remote":
                    lic = getattr(app.state, "license", None)
                    if not license_has_feature(lic, "remote_access"):
                        await websocket.send_json(
                            jsonable_encoder({
                                "type": "webrtc_error",
                                "message": "Remote access is not included in your license tier. Contact HAAK IT Solutions to upgrade.",
                            })
                        )
                        continue
                if machine_id not in manager.online():
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_error", "message": "Machine is offline"}))
                    continue
                session_id = webrtc.create_session(machine_id, websocket, session_kind=session_kind)
                sent = await manager.send_to_agent(machine_id, {"type": "webrtc_offer_req", "session_id": session_id, "session_kind": session_kind})
                if not sent:
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_error", "message": "Failed to reach agent", "session_id": session_id}))
                    webrtc.end_session(session_id)
                else:
                    await websocket.send_json(jsonable_encoder({"type": "webrtc_session_created", "session_id": session_id, "machine_id": machine_id, "session_kind": session_kind}))
            elif msg_type == "webrtc_answer":
                session_id = data.get("session_id", "")
                session = webrtc.get_session(session_id)
                if session:
                    payload = {"type": "webrtc_answer", "session_id": session_id, "sdp": data.get("sdp")}
                    if data.get("ice_restart"):
                        payload["ice_restart"] = True
                    await manager.send_to_agent(session.machine_id, payload)
            elif msg_type == "webrtc_ice_admin":
                session_id = data.get("session_id", "")
                session = webrtc.get_session(session_id)
                if session:
                    await manager.send_to_agent(
                        session.machine_id,
                        {"type": "webrtc_ice", "session_id": session_id, "candidate": data.get("candidate")},
                    )
            elif msg_type == "webrtc_end":
                session_id = data.get("session_id", "")
                session = webrtc.get_session(session_id)
                if session:
                    await manager.send_to_agent(session.machine_id, {"type": "webrtc_end", "session_id": session_id})
                    webrtc.end_session(session_id)
    except WebSocketDisconnect:
        webrtc.end_sessions_for_admin(websocket)
        manager.disconnect_admin(websocket)

