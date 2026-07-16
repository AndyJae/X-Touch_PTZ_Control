"""tests/test_application.py -- Unit-Tests der Anwendungsschicht (core/application.py).

Im Unterschied zu tests/test_web_app.py läuft hier kein FastAPI/TestClient
und kein WebSocket mit -- direkter Beleg dafür, dass Domain-/Anwendungslogik
(Mapping -> Rate-Limiter -> Driver -> StateStore -> EventBus) unabhängig vom
HTTP/WebSocket-Interface testbar ist.
"""

from __future__ import annotations

import asyncio

import pytest

import core.application as core_application
from core.application import (
    apply_button_action,
    apply_iris,
    assign_channel_button,
    assign_channel_companion_target,
    available_button_features,
    build_app_state,
    channel_snapshot,
    configure_companion,
    connect_camera,
    disconnect_camera,
    register_camera,
    rename_camera,
    trigger_companion_select,
)
from core.companion import CompanionError
from core.config import AppConfig, load_config
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


def _build_state(monkeypatch, config: AppConfig = TEST_CONFIG, config_path: str = "config.yaml"):
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    return build_app_state(config, config_path=config_path)


def _config_with_button(slot: str, feature_key: str) -> AppConfig:
    return AppConfig.model_validate(
        {
            "cameras": [
                {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
            ],
            "banks": [{"name": "Bank A", "channels": [{"camera": "cam1", "buttons": {slot: feature_key}}]}],
            "channel_defaults": {"fader": "iris"},
            "global": {"rate_limit_hz": 15},
        }
    )


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


def test_disconnect_camera_marks_driver_disconnected(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(disconnect_camera(state, "cam1"))

    assert state.drivers["cam1"].connected is False


def test_disconnect_camera_publishes_connection_changed(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    received = []

    async def on_connection_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("connection_changed", on_connection_changed)

    _run(disconnect_camera(state, "cam1"))

    assert received == [{"camera_id": "cam1"}]


def test_disconnect_camera_unknown_id_is_noop(monkeypatch) -> None:
    state = _build_state(monkeypatch)

    _run(disconnect_camera(state, "does-not-exist"))  # darf nicht raisen


def test_available_button_features_returns_driver_catalog(monkeypatch) -> None:
    state = _build_state(monkeypatch)

    assert available_button_features(state, "cam1") == FakeCameraDriver.BUTTON_FEATURE_LABELS


def test_available_button_features_unknown_camera_is_empty(monkeypatch) -> None:
    state = _build_state(monkeypatch)

    assert available_button_features(state, "does-not-exist") == {}


def test_assign_channel_button_persists_to_config_file(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    state = _build_state(monkeypatch, config_path=str(config_path))

    _run(assign_channel_button(state, 1, "button2", "drs"))

    assert state.config.banks[0].channels[0].buttons == {"button2": "drs"}
    from core.config import load_config

    reloaded = load_config(config_path)
    assert reloaded.banks[0].channels[0].buttons == {"button2": "drs"}


def test_assign_channel_button_clears_with_empty_key(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    state = _build_state(monkeypatch, config_path=str(config_path))
    _run(assign_channel_button(state, 1, "button2", "drs"))

    _run(assign_channel_button(state, 1, "button2", None))

    assert state.config.banks[0].channels[0].buttons == {}


def test_assign_channel_button_invalid_slot_raises(monkeypatch, tmp_path) -> None:
    state = _build_state(monkeypatch, config_path=str(tmp_path / "config.yaml"))
    with pytest.raises(ValueError):
        _run(assign_channel_button(state, 1, "button1", "drs"))


def test_apply_button_action_toggle_flips_state(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "drs"))
    _run(connect_camera(state, "cam1"))

    _run(apply_button_action(state, 1, "button2"))
    _run(apply_button_action(state, 1, "button2"))

    driver = state.drivers["cam1"]
    assert driver.button_feature_calls == [("drs", True), ("drs", False)]
    assert state.state_store.get_camera("cam1").feature_states["drs"] is False


def test_apply_button_action_trigger_ignores_state(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "awb_black"))
    _run(connect_camera(state, "cam1"))

    _run(apply_button_action(state, 1, "button2"))
    _run(apply_button_action(state, 1, "button2"))

    driver = state.drivers["cam1"]
    assert driver.button_feature_calls == [("awb_black", None), ("awb_black", None)]
    assert "awb_black" not in state.state_store.get_camera("cam1").feature_states


def test_apply_button_action_cycle_wraps(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button3", "knee"))
    _run(connect_camera(state, "cam1"))

    for _ in range(3):
        _run(apply_button_action(state, 1, "button3"))

    driver = state.drivers["cam1"]
    assert driver.cycle_feature_calls == [("knee", 1), ("knee", 2), ("knee", 0)]


def test_apply_button_action_without_assignment_is_noop(monkeypatch) -> None:
    state = _build_state(monkeypatch)  # TEST_CONFIG hat keine Button-Zuordnung
    _run(connect_camera(state, "cam1"))

    _run(apply_button_action(state, 1, "button2"))

    driver = state.drivers["cam1"]
    assert driver.button_feature_calls == []


def test_apply_button_action_on_disconnected_camera_is_noop(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "drs"))
    # kein connect_camera() -- Treiber bleibt disconnected

    _run(apply_button_action(state, 1, "button2"))

    driver = state.drivers["cam1"]
    assert driver.button_feature_calls == []


def test_apply_button_action_publishes_feature_changed(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "drs"))
    _run(connect_camera(state, "cam1"))
    received = []

    async def on_feature_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("feature_changed", on_feature_changed)

    _run(apply_button_action(state, 1, "button2"))

    assert received == [{"camera_id": "cam1", "key": "drs"}]


def test_channel_snapshot_includes_button_assignment_and_state(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "drs"))
    _run(connect_camera(state, "cam1"))
    _run(apply_button_action(state, 1, "button2"))  # -> enabled True

    channels = channel_snapshot(state)
    ch1 = channels[0]
    assert ch1["buttons"]["button2"] == {"key": "drs", "label": "DRS", "state": True}
    assert ch1["buttons"]["button3"] is None


def _empty_state(monkeypatch, tmp_path):
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    return build_app_state(AppConfig.model_validate({}), config_path=str(tmp_path / "config.yaml"))


def test_configure_companion_persists(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    _run(configure_companion(state, "192.168.0.50", 8000))

    assert state.config.companion.host == "192.168.0.50"
    reloaded = load_config(state.config_path)
    assert reloaded.companion.host == "192.168.0.50"
    assert reloaded.companion.port == 8000


def test_assign_channel_companion_target_persists(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    _run(assign_channel_companion_target(state, 1, 1, 0, 2))

    target = state.config.banks[0].channels[0].companion
    assert target.page == 1 and target.row == 0 and target.column == 2
    reloaded = load_config(state.config_path)
    assert reloaded.banks[0].channels[0].companion.column == 2


def test_assign_channel_companion_target_clears_with_none(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    _run(assign_channel_companion_target(state, 1, 1, 0, 2))

    _run(assign_channel_companion_target(state, 1, None, None, None))

    assert state.config.banks[0].channels[0].companion is None


def test_assign_channel_companion_target_without_camera_raises(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        _run(assign_channel_companion_target(state, 1, 1, 0, 2))


def test_trigger_companion_select_calls_press_button(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    _run(configure_companion(state, "192.168.0.50", 8000))
    _run(assign_channel_companion_target(state, 1, 1, 0, 2))

    calls = []

    async def fake_press_button(host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    _run(trigger_companion_select(state, 1))

    assert calls == [("192.168.0.50", 8000, 1, 0, 2)]


def test_trigger_companion_select_without_target_is_noop(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    calls = []

    async def fake_press_button(host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    _run(trigger_companion_select(state, 1))

    assert calls == []


def test_trigger_companion_select_propagates_companion_error(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    _run(configure_companion(state, "192.168.0.50", 8000))
    _run(assign_channel_companion_target(state, 1, 1, 0, 2))

    async def failing_press_button(host, port, page, row, column):
        raise CompanionError("boom")

    monkeypatch.setattr(core_application, "press_button", failing_press_button)

    with pytest.raises(CompanionError):
        _run(trigger_companion_select(state, 1))


def test_register_camera_creates_camera_and_binds_channel(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    assert [c.id for c in state.config.cameras] == ["cam1"]
    assert state.config.banks[0].channels[0].camera == "cam1"
    assert state.mapping.get_channel("fader", 1).camera_id == "cam1"
    driver = state.drivers["cam1"]
    assert isinstance(driver, FakeCameraDriver)
    assert driver.host == "127.0.0.1"
    assert driver.connected is True


def test_register_camera_persists_to_config_file(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    reloaded = load_config(state.config_path)
    assert reloaded.cameras[0].host == "127.0.0.1"
    assert reloaded.cameras[0].port == 8081
    assert reloaded.banks[0].channels[0].camera == "cam1"


def test_register_camera_updates_existing_entry_on_same_channel(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    first_driver = state.drivers["cam1"]

    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.2", port=8082))

    assert [c.id for c in state.config.cameras] == ["cam1"]  # kein Duplikat
    assert state.config.cameras[0].host == "127.0.0.2"
    assert first_driver.connected is False  # alter Treiber wurde disconnected
    assert state.drivers["cam1"] is not first_driver
    assert state.drivers["cam1"].host == "127.0.0.2"


def test_register_camera_invalid_channel_raises(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        _run(register_camera(state, 9, name="", host="127.0.0.1", port=80))


def test_register_camera_empty_host_raises(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        _run(register_camera(state, 1, name="", host="", port=80))


def test_register_camera_publishes_connection_changed(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    received = []

    async def on_connection_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("connection_changed", on_connection_changed)

    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    assert received == [{"camera_id": "cam1"}]


def test_rename_camera_updates_name_and_persists(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    _run(rename_camera(state, 1, "Studio Weit"))

    assert state.cameras["cam1"].name == "Studio Weit"
    reloaded = load_config(state.config_path)
    assert reloaded.cameras[0].name == "Studio Weit"


def test_rename_camera_does_not_touch_connection(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    driver = state.drivers["cam1"]
    assert driver.connected is True

    _run(rename_camera(state, 1, "Studio Weit"))

    assert driver.connected is True  # derselbe Treiber, nicht neu verbunden/getrennt
    assert state.drivers["cam1"] is driver


def test_rename_camera_empty_name_falls_back_to_default(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    _run(rename_camera(state, 1, "  "))

    assert state.cameras["cam1"].name == "CAM 1"


def test_rename_camera_on_unmapped_channel_is_noop(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    _run(rename_camera(state, 3, "Irgendwas"))  # kein Effekt, darf nicht raisen
