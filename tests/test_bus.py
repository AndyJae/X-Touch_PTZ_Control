from __future__ import annotations

import asyncio

from core.bus import EventBus


def _run(coro):
    return asyncio.run(coro)


def test_publish_calls_subscribed_callback_with_payload() -> None:
    bus = EventBus()
    received = []

    async def on_event(payload: dict) -> None:
        received.append(payload)

    bus.subscribe("iris_changed", on_event)

    _run(bus.publish("iris_changed", {"camera_id": "cam1", "value": 0.5}))

    assert received == [{"camera_id": "cam1", "value": 0.5}]


def test_publish_to_topic_with_no_subscribers_is_noop() -> None:
    bus = EventBus()

    _run(bus.publish("nobody_listens", {"x": 1}))  # muss nicht raisen


def test_multiple_subscribers_all_receive_the_event() -> None:
    bus = EventBus()
    calls: list[str] = []

    async def first(_payload: dict) -> None:
        calls.append("first")

    async def second(_payload: dict) -> None:
        calls.append("second")

    bus.subscribe("connection_changed", first)
    bus.subscribe("connection_changed", second)

    _run(bus.publish("connection_changed", {}))

    assert calls == ["first", "second"]


def test_subscriber_on_other_topic_is_not_called() -> None:
    bus = EventBus()
    called = False

    async def on_iris(_payload: dict) -> None:
        nonlocal called
        called = True

    bus.subscribe("iris_changed", on_iris)

    _run(bus.publish("connection_changed", {}))

    assert called is False


def test_clear_removes_all_subscribers() -> None:
    bus = EventBus()
    called = False

    async def on_event(_payload: dict) -> None:
        nonlocal called
        called = True

    bus.subscribe("iris_changed", on_event)
    bus.clear()

    _run(bus.publish("iris_changed", {}))

    assert called is False
