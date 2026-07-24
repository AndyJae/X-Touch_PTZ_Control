from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable

Subscriber = Callable[[Any], Awaitable[None]]


class EventBus:
    """Async pub/sub bus for domain events (e.g. `iris_changed`,
    `connection_changed`). Publishers don't need to know their consumers
    directly; the web UI and MIDI layer both publish and subscribe on the
    same bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Subscriber) -> None:
        self._subscribers[topic].append(callback)

    async def publish(self, topic: str, payload: Any) -> None:
        for callback in self._subscribers.get(topic, []):
            await callback(payload)
