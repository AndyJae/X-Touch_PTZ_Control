"""tests/test_application.py -- Unit-Tests der Anwendungsschicht (core/application.py).

Im Unterschied zu tests/test_web_app.py läuft hier kein FastAPI/TestClient
und kein WebSocket mit -- direkter Beleg dafür, dass Domain-/Anwendungslogik
(Mapping -> Rate-Limiter -> Driver -> StateStore -> EventBus) unabhängig vom
HTTP/WebSocket-Interface testbar ist.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

import core.application as core_application
from core.application import (
    apply_button_action,
    apply_encoder_turn,
    apply_iris,
    assign_channel_button,
    assign_channel_companion_target,
    available_button_features,
    build_app_state,
    channel_display_text,
    channel_line1_text,
    channel_snapshot,
    commit_encoder_value,
    configure_companion,
    connect_camera,
    cycle_encoder_function,
    disconnect_camera,
    encoder_preview,
    register_camera,
    rename_camera,
    trigger_companion_select,
)
from core.companion import CompanionError
from core.config import AppConfig, load_config
from drivers.base import CameraCommandError
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


def _build_state(monkeypatch, config: AppConfig | None = None, config_path: str | None = None):
    # Bugfix 2026-07-20 (siehe dieselbe Korrektur in tests/test_web_app.py):
    # `TEST_CONFIG` ist ein einziges Modul-Objekt -- register_camera()/
    # disconnect_camera() mutieren `state.config.cameras`/`.banks` aber
    # direkt, wodurch sich Aenderungen sonst stillschweigend zwischen Tests
    # durchsickern wuerden, die den Default nutzen. Frische Kopie pro Test.
    #
    # ZWEITER, schwerwiegenderer Bugfix (2026-07-20): der bisherige Default
    # `config_path="config.yaml"` war ein woertlicher relativer Pfad -- jeder
    # Test, der ueber diesen Default eine speichernde Funktion aufrief
    # (register_camera/disconnect_camera/rename_camera/configure_companion/
    # assign_channel_*), hat damit tatsaechlich die ECHTE `config.yaml` im
    # Projektverzeichnis ueberschrieben (Bugreport des Nutzers: config.yaml
    # zeigte ploetzlich Test-Fixture-Daten). Der Default ist jetzt IMMER ein
    # frisches `tempfile.mkdtemp()`-Verzeichnis, unabhaengig davon, ob ein
    # Test explizit `tmp_path` anfordert.
    if config_path is None:
        config_path = str(Path(tempfile.mkdtemp()) / "config.yaml")
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    return build_app_state(config if config is not None else TEST_CONFIG.model_copy(deep=True), config_path=config_path)


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


def test_driver_feature_changed_event_updates_state_and_publishes(monkeypatch) -> None:
    # Simuliert eine extern (z. B. Kamera-eigenes Web-UI) ausgeloeste
    # Aenderung, die ueber den Update-Notification-Kanal beim Treiber
    # ankommt (siehe PanasonicAWDriver._handle_notification()) -- die
    # Anwendungsschicht (_wire_camera_events) muss cam_state.feature_states
    # aktualisieren und denselben "feature_changed"-Event publizieren wie
    # bei einer lokal ausgeloesten Aktion (apply_button_action).
    state = _build_state(monkeypatch)
    received = []

    async def on_feature_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("feature_changed", on_feature_changed)

    async def scenario() -> None:
        await connect_camera(state, "cam1")
        driver = state.drivers["cam1"]
        driver.subscribed_callback({"type": "feature_changed", "key": "drs", "enabled": True})
        await asyncio.sleep(0)

    _run(scenario())

    cam_state = state.state_store.get_camera("cam1")
    assert cam_state.feature_states["drs"] is True
    assert received == [{"camera_id": "cam1", "key": "drs"}]


def test_driver_gain_changed_event_updates_state_and_publishes(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    received = []

    async def on_gain_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("gain_changed", on_gain_changed)

    async def scenario() -> None:
        await connect_camera(state, "cam1")
        driver = state.drivers["cam1"]
        driver.subscribed_callback({"type": "gain_changed", "value": 6})
        await asyncio.sleep(0)

    _run(scenario())

    cam_state = state.state_store.get_camera("cam1")
    assert cam_state.gain_db == 6
    assert cam_state.gain_auto is False
    assert received == [{"camera_id": "cam1", "value": 6, "auto": False}]


def test_driver_pedestal_changed_event_updates_state_and_publishes(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    received = []

    async def on_pedestal_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("pedestal_changed", on_pedestal_changed)

    async def scenario() -> None:
        await connect_camera(state, "cam1")
        driver = state.drivers["cam1"]
        driver.subscribed_callback({"type": "pedestal_changed", "value": -50})
        await asyncio.sleep(0)

    _run(scenario())

    cam_state = state.state_store.get_camera("cam1")
    assert cam_state.pedestal == -50
    assert received == [{"camera_id": "cam1", "value": -50}]


def test_driver_nd_changed_event_updates_state_and_publishes(monkeypatch) -> None:
    # Nutzerreport 2026-07-22 (reale AW-UE160): externe ND-Aenderung (z. B.
    # am Kamera-eigenen Bedienfeld) wurde bisher nicht erkannt.
    state = _build_state(monkeypatch)
    received = []

    async def on_nd_changed(payload: dict) -> None:
        received.append(payload)

    state.event_bus.subscribe("nd_changed", on_nd_changed)

    async def scenario() -> None:
        await connect_camera(state, "cam1")
        driver = state.drivers["cam1"]
        driver.subscribed_callback({"type": "nd_changed", "value": 2})
        await asyncio.sleep(0)

    _run(scenario())

    cam_state = state.state_store.get_camera("cam1")
    assert cam_state.nd_index == 2
    assert received == [{"camera_id": "cam1", "value": 2}]


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
    driver = state.drivers["cam1"]

    _run(disconnect_camera(state, "cam1"))

    assert driver.connected is False


def test_disconnect_camera_removes_registration_from_config(monkeypatch) -> None:
    # Nutzerentscheid 2026-07-20: Disconnect entfernt die Kamera komplett aus
    # config.yaml + Kanal-Zuordnung, statt sie fuer ein spaeteres Reconnect
    # zu behalten -- Bugreport: config.yaml sammelte sonst dauerhaft jede je
    # verbundene Kamera an.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(disconnect_camera(state, "cam1"))

    assert "cam1" not in state.drivers
    assert "cam1" not in state.cameras
    assert "cam1" not in state.rate_limiters
    assert "cam1" not in state.encoder_rate_limiters
    assert [c.id for c in state.config.cameras] == []
    assert state.config.banks[0].channels[0] is None
    assert state.mapping.get_channel("fader", 1) is None


def test_disconnect_camera_persists_removal_to_config_file(monkeypatch, tmp_path) -> None:
    config_path = str(tmp_path / "config.yaml")
    state = _build_state(monkeypatch, config_path=config_path)
    _run(connect_camera(state, "cam1"))

    _run(disconnect_camera(state, "cam1"))

    reloaded = load_config(config_path)
    assert reloaded.cameras == []
    assert reloaded.banks[0].channels[0] is None


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


def test_disconnect_camera_resets_iris_to_zero(monkeypatch) -> None:
    # Bugreport 2026-07-20: Motorfader blieb beim Trennen einer Kamera auf
    # der zuletzt bekannten Position stehen -- iris wird jetzt zurueckgesetzt,
    # midi/fader.py::_on_connection_changed() faehrt den Motor entsprechend.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    state.state_store.get_camera("cam1").iris = 1.0

    _run(disconnect_camera(state, "cam1"))

    assert state.state_store.get_camera("cam1").iris == 0.0


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


def test_assign_channel_button_queries_state_when_camera_connected(monkeypatch, tmp_path) -> None:
    # Nutzerauftrag 2026-07-18: beim Zuweisen sofort den Ist-Zustand abfragen
    # (siehe drivers/panasonic_aw.py::query_button_feature()), statt ihn erst
    # nach dem ersten Druck lokal zu kennen.
    state = _build_state(monkeypatch, config_path=str(tmp_path / "config.yaml"))
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.query_button_feature_result = True

    _run(assign_channel_button(state, 1, "button2", "drs"))

    assert driver.query_button_feature_calls == ["drs"]
    assert state.state_store.get_camera("cam1").feature_states["drs"] is True


def test_assign_channel_button_leaves_state_unknown_when_query_returns_none(monkeypatch, tmp_path) -> None:
    # query_button_feature() liefert None, wenn kein Query-Kommando bekannt
    # ist (Default des Fakes) -- dann bleibt der Zustand wie bisher unbekannt,
    # kein erfundener Fallback.
    state = _build_state(monkeypatch, config_path=str(tmp_path / "config.yaml"))
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    _run(assign_channel_button(state, 1, "button2", "drs"))

    assert driver.query_button_feature_calls == ["drs"]
    assert "drs" not in state.state_store.get_camera("cam1").feature_states


def test_assign_channel_button_skips_query_when_camera_not_connected(monkeypatch, tmp_path) -> None:
    state = _build_state(monkeypatch, config_path=str(tmp_path / "config.yaml"))
    driver = state.drivers["cam1"]
    driver.query_button_feature_result = True  # sollte ignoriert werden

    _run(assign_channel_button(state, 1, "button2", "drs"))

    assert driver.query_button_feature_calls == []
    assert "drs" not in state.state_store.get_camera("cam1").feature_states


def test_assign_channel_button_skips_query_when_clearing_assignment(monkeypatch, tmp_path) -> None:
    state = _build_state(monkeypatch, config_path=str(tmp_path / "config.yaml"))
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.query_button_feature_result = True
    _run(assign_channel_button(state, 1, "button2", "drs"))
    driver.query_button_feature_calls.clear()

    _run(assign_channel_button(state, 1, "button2", None))

    assert driver.query_button_feature_calls == []


def test_apply_button_action_toggle_flips_state(monkeypatch) -> None:
    state = _build_state(monkeypatch, config=_config_with_button("button2", "drs"))
    _run(connect_camera(state, "cam1"))

    _run(apply_button_action(state, 1, "button2"))
    _run(apply_button_action(state, 1, "button2"))

    driver = state.drivers["cam1"]
    assert driver.button_feature_calls == [("drs", True), ("drs", False)]
    assert state.state_store.get_camera("cam1").feature_states["drs"] is False


def test_apply_button_action_trigger_ignores_state(monkeypatch) -> None:
    # Kein Katalog-Eintrag hat aktuell "kind": "trigger" (AWW/ABB, die
    # einzigen "trigger"-Features, wurden entfernt) -- mit einem
    # synthetischen Katalog-Eintrag geprueft, um den generischen
    # "trigger ignoriert Zustand"-Zweig weiterhin abzudecken.
    state = _build_state(monkeypatch, config=_config_with_button("button2", "_synthetic_trigger"))
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.BUTTON_FEATURES = {**driver.BUTTON_FEATURES, "_synthetic_trigger": {"kind": "trigger", "cmd": "OAS"}}

    _run(apply_button_action(state, 1, "button2"))
    _run(apply_button_action(state, 1, "button2"))

    assert driver.button_feature_calls == [("_synthetic_trigger", None), ("_synthetic_trigger", None)]
    assert "_synthetic_trigger" not in state.state_store.get_camera("cam1").feature_states


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


def test_cycle_encoder_function_advances_and_wraps(monkeypatch) -> None:
    # Feste Reihenfolge (Nutzerentscheid, core/application.py._ENCODER_FUNCTIONS):
    # gain -> pedestal -> nd -> camera_status -> wrap.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    assert _run(cycle_encoder_function(state, 1)) == "gain"
    assert _run(cycle_encoder_function(state, 1)) == "pedestal"
    assert _run(cycle_encoder_function(state, 1)) == "nd"
    assert _run(cycle_encoder_function(state, 1)) == "camera_status"
    assert _run(cycle_encoder_function(state, 1)) == "gain"  # wrap


def test_cycle_encoder_function_queries_camera_baseline(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.gain_db = 4
    driver.pedestal = -50

    _run(cycle_encoder_function(state, 1))  # -> "gain"
    assert state.state_store.get_camera("cam1").gain_db == 4

    _run(cycle_encoder_function(state, 1))  # -> "pedestal"
    assert state.state_store.get_camera("cam1").pedestal == -50


def test_apply_encoder_turn_sends_live_to_camera(monkeypatch) -> None:
    # Nutzerentscheid: Drehen sendet gain/pedestal SOFORT live (kein
    # Preview/Commit mehr) -- der erste Tick passiert immer den
    # Rate-Limiter, da dessen "zuletzt gesendet"-Zeitstempel anfangs -inf ist.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    _run(apply_encoder_turn(state, 1, 1))  # aktive Funktion: "gain", +1

    assert driver.step_gain_calls == [1]
    assert state.encoder_pending_delta.get(1, 0) == 0  # vollstaendig gesendet
    assert encoder_preview(state, 1) == ("gain", 1)


def test_apply_encoder_turn_accumulates_pending_delta_when_rate_limited(monkeypatch) -> None:
    # Ticks, die schneller als der Rate-Limiter (15 Hz Default, TEST_CONFIG)
    # eintreffen, werden nicht gesendet, aber auch nicht verworfen -- sie
    # sammeln sich in encoder_pending_delta fuer den naechsten erlaubten Tick.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    _run(apply_encoder_turn(state, 1, 1))  # erster Tick: Limiter laesst sofort durch
    _run(apply_encoder_turn(state, 1, -1))  # gleiche Zeit -> vom Limiter zurueckgehalten
    _run(apply_encoder_turn(state, 1, 1))  # ebenfalls zurueckgehalten

    assert driver.step_gain_calls == [1]  # nur der erste Tick kam durch
    assert state.encoder_pending_delta[1] == 0  # -1 +1 = 0, wartet auf den naechsten erlaubten Tick
    assert encoder_preview(state, 1) == ("gain", 1)  # 1 (gesendet) + 0 (pending)


def test_apply_encoder_turn_clamps_preview_to_spec_range(monkeypatch) -> None:
    # Reproduziert den gemeldeten Bug: Vorschauwert lief vor dem Commit
    # unbegrenzt weiter (z.B. "+239dB"), obwohl AW-UE160_InterfaceSpecification_
    # E.pdf Kap.9 "GAIN"/"OSL:25" nur -6..+12dB bestaetigt. Feste Zeit noetig,
    # sonst wuerde der Rate-Limiter ab dem 2. Tick blockieren (siehe oben) und
    # das Clamping nie am tatsaechlich gesendeten Wert pruefen.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    for _ in range(50):  # 50 Klicks je +1 -> ohne Clamp waere die Vorschau +50
        _run(apply_encoder_turn(state, 1, 1))
        fake_now[0] += 1.0  # weit ueber dem Rate-Limiter-Intervall -> jeder Tick wird gesendet

    assert encoder_preview(state, 1) == ("gain", 12)  # geclamped auf _GAIN_MAX_DB

    for _ in range(50):  # jetzt in die andere Richtung ueber die untere Grenze
        _run(apply_encoder_turn(state, 1, -1))
        fake_now[0] += 1.0

    # Nutzerauftrag 2026-07-20: Unterschreiten von _GAIN_MIN_DB clampt bei
    # `gain` nicht mehr, sondern wechselt in Auto/AGC (live gegen AW-UE160
    # UND AW-UE100 bestaetigt, siehe CLAUDE.md) -- encoder_preview() liefert
    # dafuer `("gain", None)`, `_encoder_value_text()` zeigt "AUTO".
    assert encoder_preview(state, 1) == ("gain", None)
    assert state.state_store.get_camera("cam1").gain_auto is True


def test_apply_encoder_turn_gain_auto_further_turns_down_stay_in_auto(monkeypatch) -> None:
    # Nutzerauftrag 2026-07-20: kein tieferer Zustand als Auto -- weiteres
    # Herunterdrehen waehrend Auto bleibt ein No-Op (kein Kamerabefehl).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    cam_state = state.state_store.get_camera("cam1")
    cam_state.gain_db = None
    cam_state.gain_auto = True
    driver = state.drivers["cam1"]
    driver.step_gain_calls.clear()

    _run(apply_encoder_turn(state, 1, -1))

    assert driver.step_gain_calls == []
    assert cam_state.gain_auto is True
    assert encoder_preview(state, 1) == ("gain", None)


def test_apply_encoder_turn_gain_auto_turn_up_exits_to_gain_min_db(monkeypatch) -> None:
    # Nutzerauftrag 2026-07-20: Hochdrehen aus Auto verlaesst Auto auf
    # gain_min_db (live gegen AW-UE160 UND AW-UE100 bestaetigt, siehe
    # CLAUDE.md) -- Sequenz "Auto, 0, +1, +2" beim Hochdrehen.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    cam_state = state.state_store.get_camera("cam1")
    cam_state.gain_db = None
    cam_state.gain_auto = True
    driver = state.drivers["cam1"]
    driver.gain_db = None  # Fake-Treiber trackt seinen Gain-Zustand unabhaengig von cam_state
    driver.gain_auto = True

    _run(apply_encoder_turn(state, 1, 1))

    assert cam_state.gain_auto is False
    assert cam_state.gain_db == driver.gain_min_db
    assert encoder_preview(state, 1) == ("gain", driver.gain_min_db)


def test_apply_encoder_turn_gain_auto_exit_continues_proportionally_like_normal_turning(
    monkeypatch,
) -> None:
    # Nutzerentscheid 2026-07-20 (revidiert): eine erste Version liess nach
    # dem Auto-Ausstieg den Rest einer schnellen Drehbewegung verwerfen
    # (immer exakt bei gain_min_db landen). Das fuehlte sich beim Testen
    # anders an als normales Drehen bei anderen Werten -- jetzt wirkt JEDER
    # Tick sofort normal weiter, genau wie bei jedem anderen Gain-Wert (kein
    # Sonderfall/keine Pause noetig), nur weiterhin auf effective_gain_max_db
    # geclampt.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    cam_state = state.state_store.get_camera("cam1")
    cam_state.gain_db = None
    cam_state.gain_auto = True
    driver = state.drivers["cam1"]
    driver.gain_db = None
    driver.gain_auto = True

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    _run(apply_encoder_turn(state, 1, 1))  # verlaesst Auto -> gain_min_db
    assert cam_state.gain_auto is False
    assert cam_state.gain_db == driver.gain_min_db

    for _ in range(9):  # dieselbe schnelle Drehbewegung, <100ms spaeter -- KEINE Pause
        fake_now[0] += 0.01
        _run(apply_encoder_turn(state, 1, 1))

    # wirkt normal weiter (kein Verwerfen mehr) -- Wert ist jetzt hoeher als
    # gain_min_db, aber nicht ueber effective_gain_max_db hinaus.
    assert cam_state.gain_db > driver.gain_min_db
    assert cam_state.gain_db <= driver.effective_gain_max_db


def test_apply_encoder_turn_rejected_gain_value_clears_stale_pending_delta(monkeypatch) -> None:
    # Bugreport 2026-07-20 (live gegen AW-UE100 mit Super Gain aus: Werte
    # >36dB werden von der Kamera per ER3 abgelehnt, siehe
    # drivers/panasonic_models/aw_ue100.py -- GAIN_MAX_DB=42 kennt diese
    # Kopplung nicht). Ein abgelehnter Wert liess bisher ein "pending"-Delta
    # stehen, wodurch die naechste Vorschau einen nie erreichten Wert zeigte
    # (hier reproduziert per FakeCameraDriver.raise_on_next_step_gain, ohne
    # echte Kamera).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    _run(apply_encoder_turn(state, 1, 1))  # Tick 1: erster Tick ueberhaupt, immer gesendet
    _run(apply_encoder_turn(state, 1, 1))  # Tick 2: sofort danach -> vom Rate-Limiter geblockt
    assert state.encoder_pending_delta[1] != 0  # Vorbedingung: es steht ein Delta an

    driver.raise_on_next_step_gain = CameraCommandError("ER3", command="OGU")
    fake_now[0] += 10.0  # Rate-Limiter-Intervall abgelaufen -> Tick 3 wird gesendet
    _run(apply_encoder_turn(state, 1, 1))  # Tick 3: Kamera lehnt ab (ER3)

    assert state.encoder_pending_delta[1] == 0
    assert encoder_preview(state, 1) == ("gain", state.state_store.get_camera("cam1").gain_db)


def test_apply_encoder_turn_respects_gain_step_db_for_3db_step_models(monkeypatch) -> None:
    # AW-HE50/60/HE40/UE70/HE42 akzeptieren laut PDF nur 3dB-Schritte (0/3/6/
    # 9dB usw.) -- ein Tick muss deshalb um GAIN_STEP_DB bewegen, nicht immer
    # um 1dB (frueherer offener Punkt, siehe CLAUDE.md).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.gain_step_db = 3

    _run(apply_encoder_turn(state, 1, 1))

    assert driver.step_gain_calls == [3]
    assert encoder_preview(state, 1) == ("gain", 3)


def test_apply_encoder_turn_gain_step_combines_with_acceleration(monkeypatch) -> None:
    # Beschleunigung (x5, siehe Spec §9) multipliziert weiterhin auf denselben
    # Wert wie GAIN_STEP_DB -- ein beschleunigter Tick bei einem 3dB-Schritt-
    # Modell bewegt also um 5 Schritte a 3dB = 15dB, nicht um 5dB. Bereich
    # bewusst weit genug (0..48dB, wie real AW-HE40) gewaehlt, damit das
    # Range-Clamping aus test_apply_encoder_turn_clamps_preview_to_spec_range
    # hier nicht mit hineinspielt und nur die Schrittweiten-Multiplikation
    # geprueft wird.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.gain_step_db = 3
    driver.gain_min_db = 0
    driver.gain_max_db = 48

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    for _ in range(4):
        _run(apply_encoder_turn(state, 1, 1))
        fake_now[0] += 0.01  # > 3 Klicks/100ms -> Tick 4 beschleunigt (x5)

    assert driver.step_gain_calls == [3]  # nur der erste (nicht beschleunigte) Tick kam durch
    assert state.encoder_pending_delta[1] == 3 + 3 + 15  # Tick 2,3 (x1 Schritt) + Tick 4 (x5 Schritte)
    assert encoder_preview(state, 1) == ("gain", 3 + 3 + 3 + 15)


def test_apply_encoder_turn_pedestal_ignores_gain_step_db(monkeypatch) -> None:
    # Pedestal hat kein eigenes Schrittweiten-Feld -- GAIN_STEP_DB darf hier
    # keinen Einfluss haben, ein Tick bleibt bei 1.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.gain_step_db = 3
    _run(cycle_encoder_function(state, 1))  # -> "gain"
    _run(cycle_encoder_function(state, 1))  # -> "pedestal"

    _run(apply_encoder_turn(state, 1, 1))

    assert driver.step_pedestal_calls == [1]
    assert encoder_preview(state, 1) == ("pedestal", 1)


def test_apply_encoder_turn_uses_function_selected_via_button1(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(cycle_encoder_function(state, 1))  # -> "gain" (Index -1 -> 0, Baseline-Bestaetigung)
    _run(cycle_encoder_function(state, 1))  # -> "pedestal"
    _run(apply_encoder_turn(state, 1, 1))

    assert encoder_preview(state, 1)[0] == "pedestal"


def test_apply_encoder_turn_accelerates_after_three_fast_clicks(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    for _ in range(4):
        _run(apply_encoder_turn(state, 1, 1))
        fake_now[0] += 0.01  # 4 Klicks in 40ms -> > 3 Klicks/100ms, aber weiterhin
        # innerhalb des Rate-Limiter-Intervalls (1/15s > 0.01s) -- nur der erste
        # (nicht beschleunigte) Tick wird gesendet, der Rest sammelt sich an.
    assert driver.step_gain_calls == [1]
    assert state.encoder_pending_delta[1] == 1 + 1 + 5  # Tick 2,3 (x1) + Tick 4 (x5 Beschleunigung)
    assert encoder_preview(state, 1) == ("gain", 1 + 1 + 1 + 5)  # Gesamtsumme aller vier Ticks


def test_apply_encoder_turn_on_disconnected_camera_is_noop(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    # kein connect_camera() -- Treiber bleibt disconnected

    _run(apply_encoder_turn(state, 1, 1))

    assert state.encoder_pending_delta.get(1) is None


def test_cycle_encoder_function_discards_pending_value_of_previous_function(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    _run(apply_encoder_turn(state, 1, 1))  # erster Tick: sofort gesendet
    _run(apply_encoder_turn(state, 1, 1))  # zu schnell danach -> vom Limiter zurueckgehalten
    assert state.encoder_pending_delta[1] == 1  # noch nicht gesendetes Delta fuer "gain"

    _run(cycle_encoder_function(state, 1))  # -> "gain" erneut, verwirft das Pending-Delta
    assert state.encoder_pending_delta[1] == 0


def test_commit_encoder_value_sets_saved_flag_without_sending_to_camera(monkeypatch) -> None:
    # Nutzerentscheid: Encoder-Push sendet nichts mehr an die Kamera (der
    # Wert ist durch das Drehen bereits live aktuell) -- rein visuelles
    # "gespeichert"-Feedback.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    _run(apply_encoder_turn(state, 1, 1))  # sofort live gesendet
    driver.step_gain_calls.clear()  # nur den Effekt des Commits selbst pruefen

    _run(commit_encoder_value(state, 1))

    assert driver.step_gain_calls == []
    assert state.encoder_saved[1] is True
    channel1 = next(c for c in channel_snapshot(state) if c["index"] == 1)
    assert channel1["encoder"]["saved"] is True
    assert channel1["encoder"]["value"] == 1


def test_apply_encoder_turn_resets_saved_flag(monkeypatch) -> None:
    # "Gespeichert" (rot) gilt nur bis zum naechsten Dreh-Tick (Nutzerentscheid).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    _run(apply_encoder_turn(state, 1, 1))
    _run(commit_encoder_value(state, 1))
    assert state.encoder_saved[1] is True

    _run(apply_encoder_turn(state, 1, 1))

    assert state.encoder_saved[1] is False


def test_commit_encoder_value_is_noop_for_camera_status(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    for _ in range(4):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd -> camera_status

    _run(commit_encoder_value(state, 1))

    assert state.encoder_saved.get(1) is False  # von cycle_encoder_function zurueckgesetzt, nicht gesetzt


def test_encoder_preview_shows_default_function_without_any_button_press(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    # Ohne Button-1-Druck ist die erste Funktion aktiv ("gain") -- das
    # Baseline-Ansehen kommt bereits aus dem initialen connect_camera()-
    # get_state().
    assert encoder_preview(state, 1) == ("gain", 0)


def test_encoder_preview_none_for_camera_status(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    assert encoder_preview(state, 1) == ("gain", 0)  # Default: erste Funktion

    for _ in range(4):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd -> camera_status
    assert encoder_preview(state, 1) is None


def test_apply_encoder_turn_is_noop_for_camera_status(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    for _ in range(4):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd -> camera_status

    _run(apply_encoder_turn(state, 1, 1))

    assert driver.step_gain_calls == []
    assert driver.step_pedestal_calls == []
    assert encoder_preview(state, 1) is None


def test_channel_line1_shows_camera_name_for_camera_status(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    for _ in range(4):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd -> camera_status

    assert channel_line1_text(state, 1, "CAM 1") == "CAM 1"


def test_channel_line1_shows_function_name_for_gain_and_pedestal(monkeypatch) -> None:
    # Nutzerentscheid: Zeile 1 zeigt bei gain/pedestal den Funktionsnamen
    # statt des Kameranamens, damit der Wert in Zeile 2 eindeutig zuordenbar
    # bleibt (sonst waere z.B. "+45" ohne Kontext mehrdeutig).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    assert channel_line1_text(state, 1, "CAM 1") == "GAIN"  # Default-Funktion

    _run(cycle_encoder_function(state, 1))  # -> "gain" erneut
    _run(cycle_encoder_function(state, 1))  # -> "pedestal"
    assert channel_line1_text(state, 1, "CAM 1") == "PEDESTAL"


def test_channel_display_text_shows_raw_value_without_percent_or_prefix(monkeypatch) -> None:
    # Pedestal ist bei der AW-UE160 ein unitloser Rohwert -200..+200
    # (kein Prozentwert); Zeile 2 zeigt seit Nutzerentscheid auch kein
    # G/P-Praefix mehr, da Zeile 1 (channel_line1_text) den Funktionsnamen
    # schon traegt.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    _run(apply_encoder_turn(state, 1, 5))  # aktive Funktion: "gain"
    assert channel_display_text(state, 1, None) == "+5dB"

    _run(cycle_encoder_function(state, 1))  # -> "gain" (bestaetigt erneut)
    _run(cycle_encoder_function(state, 1))  # -> "pedestal"
    fake_now[0] += 1.0
    _run(apply_encoder_turn(state, 1, -45))
    assert channel_display_text(state, 1, None) == "-45"  # kein "%", kein "P"-Praefix


# --- ND-Filter als 4. Encoder-Funktion (Nutzerauftrag 2026-07-22) -----------
# FakeCameraDriver meldet immer "AW-UE160" (siehe tests/fakes.py) -- Katalog
# [0,1,2,3] = THROUGH/1/4/1/16/1/64, `nd_index` startet bei 0 (get_state()).


def test_apply_encoder_turn_nd_steps_through_options_by_position(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    _run(cycle_encoder_function(state, 1))  # -> "gain"
    _run(cycle_encoder_function(state, 1))  # -> "pedestal"
    _run(cycle_encoder_function(state, 1))  # -> "nd"

    _run(apply_encoder_turn(state, 1, 1))

    assert driver.set_nd_calls == [1]  # Position 0 ("THROUGH") -> Position 1 ("1/4")
    assert encoder_preview(state, 1) == ("nd", 1)
    assert state.state_store.get_camera("cam1").nd_index == 1


def test_apply_encoder_turn_nd_clamps_at_last_option_no_wrap(monkeypatch) -> None:
    # Nutzerentscheid 2026-07-22: Anschlag am Rand, kein Wraparound (anders
    # als PanasonicAWDriver.cycle_nd()).
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    for _ in range(10):  # weit ueber die letzte Position (3) hinausdrehen
        _run(apply_encoder_turn(state, 1, 1))
        fake_now[0] += 1.0

    assert driver.set_nd_calls[-1] == 3  # letzter gueltiger Data-Wert (AW-UE160: 0..3)
    assert encoder_preview(state, 1) == ("nd", 3)


def test_apply_encoder_turn_nd_clamps_at_first_option_no_wrap(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.nd_index = 3

    fake_now = [1000.0]
    monkeypatch.setattr(core_application.time, "monotonic", lambda: fake_now[0])

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    for _ in range(10):  # weit unter die erste Position (0) hinausdrehen
        _run(apply_encoder_turn(state, 1, -1))
        fake_now[0] += 1.0

    assert driver.set_nd_calls[-1] == 0
    assert encoder_preview(state, 1) == ("nd", 0)


def test_apply_encoder_turn_nd_sparse_group_skips_missing_indices(monkeypatch) -> None:
    # AW-HE130/AW-HR140 haben nur Data 0/3/4 (kein 1/2) -- ein Tick muss zur
    # naechsten LISTENPOSITION springen, nicht zum naechsten Rohwert.
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.nd_options = [(0, "THROUGH"), (3, "1/64"), (4, "1/8")]
    driver.nd_index = 0

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    _run(apply_encoder_turn(state, 1, 1))

    assert driver.set_nd_calls == [3]  # naechste Position nach 0 ist Data 3, nicht 1
    assert encoder_preview(state, 1) == ("nd", 3)


def test_apply_encoder_turn_nd_rejected_value_clears_stale_pending_delta(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.raise_on_next_set_nd = CameraCommandError("ER3", command="OFT")

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    _run(apply_encoder_turn(state, 1, 1))

    assert state.encoder_pending_delta[1] == 0
    assert state.state_store.get_camera("cam1").error is not None


def test_encoder_function_unsupported_nd_shows_na_for_model_without_nd_filter(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))
    driver = state.drivers["cam1"]
    driver.nd_options = None  # z. B. AW-HE50 (kein physischer ND-Filter)

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    assert channel_display_text(state, 1, None) == "n/a"
    assert channel_line1_text(state, 1, "CAM 1") == "ND"


def test_commit_encoder_value_marks_saved_for_nd(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd
    _run(apply_encoder_turn(state, 1, 1))
    assert state.encoder_saved.get(1) is False  # von apply_encoder_turn zurueckgesetzt

    _run(commit_encoder_value(state, 1))

    assert state.encoder_saved.get(1) is True


def test_channel_display_text_shows_nd_label(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    for _ in range(3):
        _run(cycle_encoder_function(state, 1))  # -> gain -> pedestal -> nd

    assert channel_display_text(state, 1, None) == "THROUGH"  # nd_index startet bei 0

    _run(apply_encoder_turn(state, 1, 1))
    assert channel_display_text(state, 1, None) == "1/4"


def test_channel_snapshot_exposes_display_line1_and_text(monkeypatch) -> None:
    state = _build_state(monkeypatch)
    _run(connect_camera(state, "cam1"))

    channel1 = next(c for c in channel_snapshot(state) if c["index"] == 1)
    assert channel1["display_line1"] == "GAIN"
    assert channel1["display_text"] == "+0dB"


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


def test_configure_companion_defaults_to_not_connected(monkeypatch, tmp_path) -> None:
    """Bugfix: ohne explizit bestaetigte Erreichbarkeit darf `companion_connected`
    nicht faelschlich True werden, nur weil ein Host gespeichert wurde."""
    state = _empty_state(monkeypatch, tmp_path)

    _run(configure_companion(state, "192.168.0.50", 8000))

    assert state.companion_connected is False


def test_configure_companion_sets_connected_when_caller_confirmed_reachability(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)

    _run(configure_companion(state, "192.168.0.50", 8000, connected=True))

    assert state.companion_connected is True


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

    async def fake_press_button(client, host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    _run(trigger_companion_select(state, 1))

    assert calls == [("192.168.0.50", 8000, 1, 0, 2)]


def test_trigger_companion_select_without_target_is_noop(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))

    calls = []

    async def fake_press_button(client, host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    _run(trigger_companion_select(state, 1))

    assert calls == []


def test_trigger_companion_select_propagates_companion_error(monkeypatch, tmp_path) -> None:
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="127.0.0.1", port=8081))
    _run(configure_companion(state, "192.168.0.50", 8000))
    _run(assign_channel_companion_target(state, 1, 1, 0, 2))

    async def failing_press_button(client, host, port, page, row, column):
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


def test_register_camera_rejects_duplicate_ip_on_another_channel(monkeypatch, tmp_path) -> None:
    # Bugreport 2026-07-20: zwei Kanaele auf derselben physischen Kamera
    # teilen sich unbemerkt Zustand (Lens-Info-Push, Gain, Pedestal) --
    # siehe CLAUDE.md Offene Punkte (cam1/cam4 auf 192.168.0.10).
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="192.168.0.10", port=80))

    with pytest.raises(ValueError, match="already connected"):
        _run(register_camera(state, 2, name="CAM 2", host="192.168.0.10", port=80))

    assert [c.id for c in state.config.cameras] == ["cam1"]  # Kanal 2 nicht angelegt


def test_register_camera_same_host_on_same_channel_is_allowed(monkeypatch, tmp_path) -> None:
    # Erneutes Connect/Update desselben Kanals mit unveraendertem Host darf
    # nicht als Duplikat abgelehnt werden.
    state = _empty_state(monkeypatch, tmp_path)
    _run(register_camera(state, 1, name="CAM 1", host="192.168.0.10", port=80))

    _run(register_camera(state, 1, name="Renamed", host="192.168.0.10", port=80))  # darf nicht raisen

    assert state.config.cameras[0].name == "Renamed"


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
