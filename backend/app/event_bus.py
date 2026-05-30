"""Shared internal event envelope and bus abstraction."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.request_context import get_trace_id

logger = logging.getLogger("cropsentinel.event_bus")

EventHandler = Callable[[str, "EventEnvelope"], Awaitable[None] | None]


class EventTopics:
    AGENT_EVENTS = "agent.events"
    ACTIVITY_LOGS = "activity.logs"
    SCREENSHOT_EVENTS = "screenshot.events"
    ALERT_EVENTS = "alert.events"
    DLP_EVENTS = "dlp.events"
    PHISHING_EVENTS = "phishing.events"
    SYSTEM_EVENTS = "system.events"
    AUDIT_EVENTS = "audit.events"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backend_name() -> str:
    return os.environ.get("EVENT_BUS_BACKEND", "noop").strip().lower() or "noop"


def _schema_version() -> int:
    try:
        return int(os.environ.get("EVENT_SCHEMA_VERSION", "1"))
    except ValueError:
        return 1


@dataclass(slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    tenant_id: int | None
    machine_id: str
    occurred_at: str
    produced_at: str
    schema_version: int
    payload: dict[str, Any]
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InternalEventBus:
    def __init__(self) -> None:
        self.backend = _backend_name()
        self.queue: deque[tuple[str, EventEnvelope]] = deque()
        self._lock = threading.Lock()
        self._drain_task: asyncio.Task | None = None
        self._consume_task: asyncio.Task | None = None
        self._redis = None
        self._kafka = None
        self._consumer = None
        self._started = False
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._ephemeral_tasks: set[asyncio.Task] = set()
        self._published_count = 0
        self._subscriber_delivery_count = 0
        self._failed_count = 0
        self._consumed_count = 0

    def build_event(
        self,
        *,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        tenant_id: int | None = None,
        machine_id: str = "",
        occurred_at: str | None = None,
        schema_version: int | None = None,
    ) -> tuple[str, EventEnvelope]:
        produced_at = _utcnow_iso()
        resolved_occurred_at = occurred_at or payload.get("timestamp") or produced_at
        envelope = EventEnvelope(
            event_id=payload.get("event_id") or f"{event_type}-{produced_at}",
            event_type=event_type,
            tenant_id=tenant_id,
            machine_id=machine_id or payload.get("machine_id", ""),
            occurred_at=resolved_occurred_at,
            produced_at=produced_at,
            schema_version=schema_version or _schema_version(),
            payload=payload,
            trace_id=get_trace_id(),
        )
        return topic, envelope

    def publish(
        self,
        *,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        tenant_id: int | None = None,
        machine_id: str = "",
        occurred_at: str | None = None,
        schema_version: int | None = None,
    ) -> None:
        item = self.build_event(
            topic=topic,
            event_type=event_type,
            payload=payload,
            tenant_id=tenant_id,
            machine_id=machine_id,
            occurred_at=occurred_at,
            schema_version=schema_version,
        )
        if not self._started:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and self._subscribers.get(topic):
                task = loop.create_task(self._deliver_local(topic, item[1]))
                self._ephemeral_tasks.add(task)
                task.add_done_callback(self._ephemeral_tasks.discard)
            if self.backend == "noop":
                self._published_count += 1
                return
        with self._lock:
            self.queue.append(item)

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        handlers = self._subscribers.setdefault(topic, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(topic)
        if not handlers:
            return
        self._subscribers[topic] = [candidate for candidate in handlers if candidate != handler]
        if not self._subscribers[topic]:
            self._subscribers.pop(topic, None)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self.backend == "redis":
            self._redis = await self._build_redis()
        elif self.backend == "kafka":
            self._kafka = await self._build_kafka()
        self._drain_task = asyncio.create_task(self._drain_loop())
        if self._external_consumer_enabled():
            self._consumer = await self._build_external_consumer()
            if self._consumer is not None:
                self._consume_task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        self._started = False
        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
            self._consume_task = None
        if self._consumer is not None:
            close = getattr(self._consumer, "close", None)
            if callable(close):
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            stop = getattr(self._consumer, "stop", None)
            if callable(stop):
                result = stop()
                if asyncio.iscoroutine(result):
                    await result
            self._consumer = None
        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None
        if self._kafka is not None:
            await self._kafka.stop()
            self._kafka = None
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None

    async def _build_redis(self):
        url = os.environ.get("EVENT_BUS_REDIS_URL", "").strip() or os.environ.get("REDIS_URL", "").strip()
        if not url:
            logger.warning("EVENT_BUS_BACKEND=redis but no Redis URL is configured; falling back to noop")
            self.backend = "noop"
            return None
        import redis.asyncio as aioredis  # noqa: PLC0415

        return aioredis.from_url(url, decode_responses=True)

    async def _build_kafka(self):
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        if not bootstrap:
            logger.warning("EVENT_BUS_BACKEND=kafka but KAFKA_BOOTSTRAP_SERVERS is missing; falling back to noop")
            self.backend = "noop"
            return None
        from aiokafka import AIOKafkaProducer  # noqa: PLC0415

        producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
        await producer.start()
        return producer

    def _external_consumer_enabled(self) -> bool:
        return self.backend in {"redis", "kafka"} and (
            os.environ.get("EVENT_BUS_CONSUME_EXTERNAL", "0").strip().lower() in {"1", "true", "yes", "on"}
        )

    def _deliver_inline(self) -> bool:
        if self._external_consumer_enabled():
            return False
        return True

    async def _build_external_consumer(self):
        topics = sorted(self._subscribers.keys())
        if not topics:
            return None
        if self.backend == "redis":
            pubsub = self._redis.pubsub() if self._redis is not None else None
            if pubsub is None:
                return None
            await pubsub.subscribe(*[f"eventbus:{topic}" for topic in topics])
            return pubsub
        if self.backend == "kafka":
            bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
            if not bootstrap:
                return None
            from aiokafka import AIOKafkaConsumer  # noqa: PLC0415

            group_id = os.environ.get("EVENT_BUS_CONSUMER_GROUP", "").strip() or "cropsentinel-internal"
            consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=bootstrap,
                group_id=group_id,
                enable_auto_commit=True,
                auto_offset_reset=os.environ.get("EVENT_BUS_AUTO_OFFSET_RESET", "latest").strip() or "latest",
            )
            await consumer.start()
            return consumer
        return None

    async def _drain_loop(self) -> None:
        while True:
            item = None
            with self._lock:
                if self.queue:
                    item = self.queue.popleft()
            if item is None:
                await asyncio.sleep(0.1)
                continue
            topic, envelope = item
            try:
                if self._deliver_inline():
                    await self._deliver_local(topic, envelope)
                await self._publish_one(topic, envelope)
                self._published_count += 1
            except Exception as exc:
                self._failed_count += 1
                logger.warning("Event bus publish failed topic=%s event_type=%s: %s", topic, envelope.event_type, exc)
                await asyncio.sleep(0.2)

    async def _publish_one(self, topic: str, envelope: EventEnvelope) -> None:
        payload = json.dumps(envelope.to_dict(), default=str)
        if self.backend == "redis" and self._redis is not None:
            await self._redis.publish(f"eventbus:{topic}", payload)
            return
        if self.backend == "kafka" and self._kafka is not None:
            await self._kafka.send_and_wait(topic, payload.encode("utf-8"))
            return
        logger.debug("event_bus noop topic=%s event_type=%s", topic, envelope.event_type)

    async def _deliver_local(self, topic: str, envelope: EventEnvelope) -> None:
        handlers = list(self._subscribers.get(topic, ()))
        if not handlers:
            return
        for handler in handlers:
            result = handler(topic, envelope)
            if asyncio.iscoroutine(result):
                await result
            self._subscriber_delivery_count += 1

    async def _consume_loop(self) -> None:
        if self.backend == "redis":
            await self._consume_loop_redis()
            return
        if self.backend == "kafka":
            await self._consume_loop_kafka()

    async def _consume_loop_redis(self) -> None:
        while True:
            if self._consumer is None:
                await asyncio.sleep(0.2)
                continue
            message = await self._consumer.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                await asyncio.sleep(0.05)
                continue
            channel = str(message.get("channel", ""))
            payload = message.get("data")
            if not channel.startswith("eventbus:") or not payload:
                continue
            topic = channel.split("eventbus:", 1)[1]
            envelope = self._decode_envelope(payload)
            await self._deliver_local(topic, envelope)
            self._consumed_count += 1

    async def _consume_loop_kafka(self) -> None:
        while True:
            if self._consumer is None:
                await asyncio.sleep(0.2)
                continue
            batches = await self._consumer.getmany(timeout_ms=1000)
            if not batches:
                await asyncio.sleep(0.05)
                continue
            for _partition, messages in batches.items():
                for message in messages:
                    envelope = self._decode_envelope(message.value.decode("utf-8"))
                    await self._deliver_local(message.topic, envelope)
                    self._consumed_count += 1

    def _decode_envelope(self, payload: str) -> EventEnvelope:
        data = json.loads(payload)
        return EventEnvelope(
            event_id=str(data.get("event_id", "")),
            event_type=str(data.get("event_type", "")),
            tenant_id=data.get("tenant_id"),
            machine_id=str(data.get("machine_id", "")),
            occurred_at=str(data.get("occurred_at", "")),
            produced_at=str(data.get("produced_at", "")),
            schema_version=int(data.get("schema_version", 1) or 1),
            payload=dict(data.get("payload") or {}),
            trace_id=str(data.get("trace_id", "")),
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            queue_depth = len(self.queue)
        return {
            "backend": self.backend,
            "queue_depth": queue_depth,
            "published_count": self._published_count,
            "subscriber_delivery_count": self._subscriber_delivery_count,
            "failed_count": self._failed_count,
            "consumed_count": self._consumed_count,
            "subscriber_topics": sorted(self._subscribers.keys()),
            "started": self._started,
            "external_consumer_enabled": self._external_consumer_enabled(),
            "external_consumer_started": self._consume_task is not None,
            "ephemeral_tasks": len(self._ephemeral_tasks),
        }

    def cancel_ephemeral_tasks(self) -> None:
        for task in list(self._ephemeral_tasks):
            if not task.done():
                try:
                    task.cancel()
                except RuntimeError:
                    pass
        self._ephemeral_tasks.clear()


internal_event_bus = InternalEventBus()
