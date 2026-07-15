from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable

Subscriber = Callable[[Any], Awaitable[None]]


class EventBus:
    """Pub/Sub-Rückgrat, Spec §3 Core-Baustein "EventBus".

    Domain-Events (z. B. `iris_changed`, `connection_changed`) werden hier
    publiziert, statt dass Aufrufer Konsumenten (WebSocket-Broadcast heute,
    Motorfader-Feedback für X-Touch später) direkt kennen und aufrufen.
    Web-UI und MIDI werden dadurch zu zwei gleichwertigen Publishern/
    Subscribern auf demselben Bus, statt dass MIDI später als Sonderfall
    nachgezogen werden muss.

    Async, weil alle heutigen Konsumenten (WebSocket-Versand) async sind.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Subscriber) -> None:
        self._subscribers[topic].append(callback)

    async def publish(self, topic: str, payload: Any) -> None:
        for callback in self._subscribers.get(topic, []):
            await callback(payload)

    def clear(self) -> None:
        self._subscribers.clear()
