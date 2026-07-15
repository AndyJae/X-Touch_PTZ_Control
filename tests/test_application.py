"""tests/test_application.py -- Unit-Tests der Anwendungsschicht (core/application.py).

Im Unterschied zu tests/test_web_app.py läuft hier kein FastAPI/TestClient
und kein WebSocket mit -- direkter Beleg dafür, dass Domain-/Anwendungslogik
(Mapping -> Rate-Limiter -> Driver -> StateStore -> EventBus) unabhängig vom
HTTP/WebSocket-Interface testbar ist.
"""

from __future__ import annotations

import asyncio

import core.application as core_application
from core.application import (
    apply_iris,
    build_app_state,
    camera_status_list,
    channel_snapshot,
    connect_camera,
)
from core.config import AppConfig
from tests.fakes import FakeCameraDriver


def _run(coro):
    return asyncio.run(coro)


TEST_CONFIG = AppConfig.model_validate(
    {
        "cameras": [
            {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
        ],
        "banks": [{"name": "Bank A", "channels": [{"camera": "cam1"}]}],
        "channel_defaults": {"fader": "iris"},
        "global": {"rate_limit_hz": 15},
    }
)


def _build_state(monkeypatch, config: AppConfig = TEST_CONFIG):
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    return build_app_state(config)


def test_connect_camera_updates_state_store_on_success(monkeypatch) -> None:
    state = _build_state(monkeypatch)

    _run(connect_camera(state, "cam1"))

    driver = state.drivers["cam1"]
    assert driver.connected is True
    cam_state = state.state_store.get_camera("cam1")
    assert cam_state.error is None


def test_connect_camera_publishes_connection_changed(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    received = []

    async def on_connection_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("connection_changed", on_connection_changed)

    _run(connect_camera(state, "cam1"))

    assert received == [{"camera_id": "cam1"}]


def test_apply_iris_clamps_and_calls_driver(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(apply_iris(state, 1, 1.5, final=True))  # ueber 1.0 hinaus

    driver = state.drivers["cam1"]
    assert driver.set_iris_calls == [1.0]
    assert state.state_store.get_camera("cam1").iris == 1.0


def test_apply_iris_on_unmapped_channel_is_ignored(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(apply_iris(state, 5, 0.5, final=True))  # Kanal 5 ist nicht in TEST_CONFIG gemappt

    driver = state.drivers["cam1"]
    assert driver.set_iris_calls == []


def test_apply_iris_on_disconnected_camera_is_ignored(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    # kein connect_camera() -- Treiber bleibt disconnected

    _run(apply_iris(state, 1, 0.5, final=True))

    driver = state.drivers["cam1"]
    assert driver.set_iris_calls == []


def test_channel_snapshot_lists_all_eight_channels_with_gaps() -> None:
    state = build_app_state(AppConfig.model_validate({}))

    channels = channel_snapshot(state)

    assert [c["index"] for c in channels] == list(range(1, 9))
    assert all(c["camera_id"] is None for c in channels)


def test_camera_status_list_reflects_connection_and_model(monkeypatch) -> None:
    state = _build_state(monkeypatch)

    _run(connect_camera(state, "cam1"))

    statuses = camera_status_list(state)
    assert statuses == [
        {
            "id": "cam1",
            "name": "CAM 1",
            "host": "127.0.0.1",
            "connected": True,
            "model": "AW-UE160",
            "error": None,
        }
    ]
