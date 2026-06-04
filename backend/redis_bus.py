"""
CropSentinel — Redis pub/sub bus for multi-instance WebSocket delivery.

When REDIS_URL is set, all inter-instance communication goes through Redis:
  - Broadcast events (agent data → admin dashboards) use the CH_BROADCAST channel.
    Every instance subscribes; the one whose admin WebSockets receive the message
    delivers it locally.
  - Agent commands (admin → specific agent) use CH_AGENT_PREFIX + machine_id.
    Every instance attempts delivery; only the one with the agent connected succeeds.
  - Global online machine set is maintained in Redis KEY_ONLINE (SADD / SREM).

When REDIS_URL is NOT set, all methods are no-ops and `enabled()` returns False.
The ConnectionManager falls back to its in-memory single-instance behaviour, so
single-instance and dev deployments need zero configuration.

Reconnection: the subscriber loop catches all exceptions and reconnects with a
5-second back-off so transient Redis restarts don't bring down the backend.
"""

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable

logger = logging.getLogger("croppro.redis")

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

# Channel / key names
CH_BROADCAST    = "croppro:events"
CH_AGENT_PREFIX = "croppro:agent:"
CH_WEBRTC       = "croppro:webrtc"
KEY_ONLINE      = "croppro:online"

# Two separate connections: Redis pub/sub protocol requires the subscriber
# connection to be dedicated (it can't interleave publish commands).
_pub_client = None
_sub_client = None


def enabled() -> bool:
    """True when Redis is configured — gates all pub/sub behaviour."""
    return bool(REDIS_URL)


async def _pub() -> "redis.asyncio.Redis":  # type: ignore[name-defined]
    global _pub_client
    if _pub_client is None:
        import redis.asyncio as aioredis  # noqa: PLC0415
        _pub_client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
        )
    return _pub_client


async def _sub() -> "redis.asyncio.Redis":  # type: ignore[name-defined]
    global _sub_client
    if _sub_client is None:
        import redis.asyncio as aioredis  # noqa: PLC0415
        _sub_client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
        )
    return _sub_client


# ── Publish helpers ────────────────────────────────────────────────────────────

async def publish_broadcast(data: dict) -> None:
    """Publish an event to all backend instances (admin dashboard broadcast)."""
    if not enabled():
        return
    try:
        r = await _pub()
        await r.publish(CH_BROADCAST, json.dumps(data, default=str))
    except Exception as exc:
        logger.warning("Redis publish_broadcast failed: %s", exc)


async def publish_agent_cmd(machine_id: str, data: dict) -> None:
    """Publish a command targeting a specific agent (cross-instance delivery)."""
    if not enabled():
        return
    try:
        r = await _pub()
        await r.publish(f"{CH_AGENT_PREFIX}{machine_id}", json.dumps(data, default=str))
    except Exception as exc:
        logger.warning("Redis publish_agent_cmd failed for %s: %s", machine_id, exc)


async def publish_webrtc_msg(data: dict) -> None:
    """Publish a WebRTC signalling message to all backend instances."""
    if not enabled():
        return
    try:
        r = await _pub()
        await r.publish(CH_WEBRTC, json.dumps(data, default=str))
    except Exception as exc:
        logger.warning("Redis publish_webrtc_msg failed: %s", exc)


# ── Online machine set ─────────────────────────────────────────────────────────

async def mark_online(machine_id: str) -> None:
    if not enabled():
        return
    try:
        r = await _pub()
        await r.sadd(KEY_ONLINE, machine_id)
    except Exception as exc:
        logger.debug("Redis mark_online failed: %s", exc)


async def mark_offline(machine_id: str) -> None:
    if not enabled():
        return
    try:
        r = await _pub()
        await r.srem(KEY_ONLINE, machine_id)
    except Exception as exc:
        logger.debug("Redis mark_offline failed: %s", exc)


async def get_online_count() -> int:
    """Global count of online machines across all instances."""
    if not enabled():
        return 0
    try:
        r = await _pub()
        return await r.scard(KEY_ONLINE)
    except Exception:
        return 0


async def get_online_set() -> set:
    """Full set of online machine_ids across all instances."""
    if not enabled():
        return set()
    try:
        r = await _pub()
        return set(await r.smembers(KEY_ONLINE))
    except Exception:
        return set()


# ── Subscriber loop ────────────────────────────────────────────────────────────

async def subscribe_loop(
    on_broadcast: Callable[[dict], Awaitable[None]],
    on_agent_cmd: Callable[[str, dict], Awaitable[None]],
    on_webrtc: Callable[[dict], Awaitable[None]],
) -> None:
    """
    Long-running coroutine — call from an asyncio.create_task in lifespan.
    Subscribes to Redis channels and dispatches incoming messages:
      - CH_BROADCAST messages   → on_broadcast(data)
      - CH_WEBRTC messages      → on_webrtc(data)
      - CH_AGENT_PREFIX* messages → on_agent_cmd(machine_id, data)
    Reconnects automatically after any disconnection.
    """
    if not enabled():
        logger.info("REDIS_URL not set — running in single-instance mode (no pub/sub)")
        return

    logger.info("Redis subscriber starting on %s", REDIS_URL.split("@")[-1])
    global _sub_client

    while True:
        try:
            r = await _sub()
            pubsub = r.pubsub(ignore_subscribe_messages=True)
            await pubsub.subscribe(CH_BROADCAST, CH_WEBRTC)
            await pubsub.psubscribe(f"{CH_AGENT_PREFIX}*")
            logger.info("Redis subscriber connected — listening for events")

            async for msg in pubsub.listen():
                if msg is None:
                    continue
                try:
                    mtype = msg.get("type", "")
                    if mtype == "message" and msg.get("channel") == CH_BROADCAST:
                        await on_broadcast(json.loads(msg["data"]))
                    elif mtype == "message" and msg.get("channel") == CH_WEBRTC:
                        await on_webrtc(json.loads(msg["data"]))
                    elif mtype == "pmessage":
                        ch: str = msg.get("channel", "")
                        if ch.startswith(CH_AGENT_PREFIX):
                            mid = ch[len(CH_AGENT_PREFIX):]
                            await on_agent_cmd(mid, json.loads(msg["data"]))
                except Exception as exc:
                    logger.debug("Redis dispatch error: %s", exc)

        except asyncio.CancelledError:
            logger.info("Redis subscriber cancelled — shutting down")
            return
        except Exception as exc:
            logger.warning(
                "Redis subscriber lost connection (%s) — reconnecting in 5 s", exc
            )
            _sub_client = None
            await asyncio.sleep(5)
