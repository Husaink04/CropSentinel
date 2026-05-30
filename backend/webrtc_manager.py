"""
CropSentinel WebRTC Signalling Manager
===================================
The server acts as a pure SDP/ICE relay between admin browsers and agents.
It never touches media — it just routes signalling messages so peers can
negotiate a direct (or TURN-assisted) P2P connection.

Session lifecycle
-----------------
1. Admin  → server : { type:"webrtc_request",   machine_id, session_id }
2. Server → agent  : { type:"webrtc_offer_req",  session_id, machine_id }
3. Agent  → server : { type:"webrtc_offer",      session_id, sdp }
4. Server → admin  : { type:"webrtc_offer",      session_id, sdp }
5. Admin  → server : { type:"webrtc_answer",     session_id, sdp }
6. Server → agent  : { type:"webrtc_answer",     session_id, sdp }
7. Both sides exchange ICE candidates via { type:"webrtc_ice", session_id, candidate }
8. Either side: { type:"webrtc_end",   session_id }  →  session torn down
"""

import asyncio
import uuid
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class SessionState(str, Enum):
    REQUESTING  = "requesting"   # admin asked for a session, waiting for agent offer
    NEGOTIATING = "negotiating"  # offer sent to agent, waiting for answer
    CONNECTED   = "connected"    # answer received, ICE in progress / stream live
    ENDED       = "ended"


@dataclass
class RTCSession:
    session_id:  str
    machine_id:  str
    admin_ws:    Any            # WebSocket to the admin browser
    session_kind: str = "live"
    state:       SessionState = SessionState.REQUESTING
    created_at:  float = field(default_factory=lambda: __import__('time').time())


class WebRTCSignallingManager:
    """
    Thread-safe (asyncio) WebRTC signalling relay.
    Keyed by session_id so multiple admins can watch different machines.
    """

    def __init__(self):
        # session_id → RTCSession
        self._sessions: Dict[str, RTCSession] = {}
        # machine_id  → list[session_id]  (one machine can have multiple watchers)
        self._machine_sessions: Dict[str, list] = {}

    # ── Session management ────────────────────────────────────────────────────

    def create_session(self, machine_id: str, admin_ws, session_kind: str = "live") -> str:
        sid = str(uuid.uuid4())
        sess = RTCSession(session_id=sid, machine_id=machine_id, admin_ws=admin_ws, session_kind=session_kind)
        self._sessions[sid] = sess
        self._machine_sessions.setdefault(machine_id, []).append(sid)
        return sid

    def get_session(self, session_id: str) -> Optional[RTCSession]:
        return self._sessions.get(session_id)

    def get_sessions_for_machine(self, machine_id: str) -> list:
        return [self._sessions[sid]
                for sid in self._machine_sessions.get(machine_id, [])
                if sid in self._sessions]

    def end_session(self, session_id: str):
        sess = self._sessions.pop(session_id, None)
        if sess:
            sess.state = SessionState.ENDED
            ml = self._machine_sessions.get(sess.machine_id, [])
            if session_id in ml:
                ml.remove(session_id)

    def end_sessions_for_admin(self, admin_ws) -> list:
        """Called when an admin WS disconnects — returns ended session IDs."""
        ended = []
        for sid, sess in list(self._sessions.items()):
            if sess.admin_ws is admin_ws:
                self.end_session(sid)
                ended.append(sid)
        return ended

    def end_sessions_for_machine(self, machine_id: str) -> list:
        """Called when an agent disconnects."""
        ended = []
        for sid in list(self._machine_sessions.get(machine_id, [])):
            self.end_session(sid)
            ended.append(sid)
        return ended

    # ── Relay helpers ─────────────────────────────────────────────────────────

    async def relay_to_admin(self, session_id: str, payload: dict) -> bool:
        sess = self._sessions.get(session_id)
        if not sess:
            return False
        try:
            await sess.admin_ws.send_json(payload)
            return True
        except Exception:
            self.end_session(session_id)
            return False

    async def notify_admin_ended(self, session_id: str, reason: str = "agent_disconnected"):
        """Inform admin that the WebRTC session has ended."""
        sess = self._sessions.get(session_id)
        if not sess:
            return
        try:
            await sess.admin_ws.send_json({
                "type":       "webrtc_ended",
                "session_id": session_id,
                "reason":     reason,
            })
        except Exception:
            pass
        self.end_session(session_id)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def active_count(self) -> int:
        return len(self._sessions)

    def active_for_machine(self, machine_id: str) -> int:
        return len(self._machine_sessions.get(machine_id, []))


# Singleton
webrtc = WebRTCSignallingManager()
