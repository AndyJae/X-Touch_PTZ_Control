from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import core.application as core_application
import web.app as web_app
from core.companion import CompanionError
from core.config import AppConfig
from tests.fakes import FakeCameraDriver

TEST_CONFIG = AppConfig.model_validate(
    {
        "cameras": [
            {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
        ],
        "banks": [{"name": "Bank A", "channels": [{"camera": "cam1"}]}],
        "channel_defaults": {"fader": "iris"},
        "global": {"rate_limit_hz": 15, "web_port": 8600},
    }
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "load_config", lambda path="config.yaml": TEST_CONFIG)
    # Verhindert, dass Tests, die register_camera/assign_channel_button ueber
    # die echte Route ausloesen, in die reale config.yaml des Repos schreiben.
    monkeypatch.setattr(web_app, "_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    # LOG_BUFFER haengt an einem prozessweiten Logger (core/log_buffer.py) --
    # ohne Reset wuerden Log-Zeilen aus vorherigen Tests hier sichtbar bleiben.
    web_app.LOG_BUFFER.clear()
    # Ausserhalb von main.py (das per logging.basicConfig(level=config.global_
    # .log_level) konfiguriert) hat der Root-Logger keinen expliziten Level
    # (Default WARNING) -- Tests wuerden INFO-Log-Zeilen sonst nie sehen,
    # obwohl der dokumentierte Default (log_level: INFO, siehe config.yaml-
    # Beispiel Spec §4) sie im echten Betrieb zeigen wuerde.
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    try:
        with TestClient(web_app.app) as test_client:
            yield test_client
    finally:
        root_logger.setLevel(previous_level)


def test_surface_page_returns_ok(client) -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_setup_page_returns_ok(client) -> None:
    response = client.get("/setup")
    assert response.status_code == 200


def test_config_page_returns_ok(client) -> None:
    response = client.get("/config")
    assert response.status_code == 200


def test_logs_page_returns_ok(client) -> None:
    response = client.get("/logs")
    assert response.status_code == 200


def test_logs_page_shows_captured_log_entries(client) -> None:
    logging.getLogger("ptz_control.web").info("test-marker-info")
    response = client.get("/logs")
    assert "test-marker-info" in response.text


def test_logs_page_filters_by_level(client) -> None:
    logging.getLogger("ptz_control.web").warning("test-marker-warning")
    logging.getLogger("ptz_control.web").error("test-marker-error")
    response = client.get("/logs", params={"level": "ERROR"})
    assert "test-marker-error" in response.text
    assert "test-marker-warning" not in response.text


def test_logs_page_unknown_level_falls_back_to_all(client) -> None:
    logging.getLogger("ptz_control.web").info("test-marker-fallback")
    response = client.get("/logs", params={"level": "NOT-A-LEVEL"})
    assert "test-marker-fallback" in response.text


def test_camera_connects_during_startup(client) -> None:
    driver = web_app.app.state.ptz.drivers["cam1"]
    assert driver.connected is True
    assert driver.model == "AW-UE160"


def test_websocket_initial_snapshot_reflects_connected_camera(client) -> None:
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()

    assert data["type"] == "snapshot"
    channel1 = next(c for c in data["channels"] if c["index"] == 1)
    assert channel1["camera_id"] == "cam1"
    assert channel1["connected"] is True
    unassigned = next(c for c in data["channels"] if c["index"] == 2)
    assert unassigned["camera_id"] is None


def test_set_iris_over_websocket_calls_driver_and_broadcasts_snapshot(client) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_json({"type": "set_iris", "channel": 1, "value": 0.75, "final": True})
        data = ws.receive_json()

    channel1 = next(c for c in data["channels"] if c["index"] == 1)
    assert channel1["iris"] == pytest.approx(0.75)

    driver = web_app.app.state.ptz.drivers["cam1"]
    assert driver.set_iris_calls == [0.75]


def test_rapid_non_final_updates_are_rate_limited(client) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        for value in (0.1, 0.2, 0.3):
            ws.send_json({"type": "set_iris", "channel": 1, "value": value, "final": False})
        # Priorisierter finaler Wert erzwingt garantiert eine Antwort, damit
        # der Test nicht auf eine ungewisse Zahl throttlebedingt ausgelassener
        # Broadcasts wartet (Spec §8: Zwischenwerte duerfen verworfen werden).
        ws.send_json({"type": "set_iris", "channel": 1, "value": 0.9, "final": True})
        # Der erste (nicht throttlebare) Wert 0.1 erzeugt garantiert einen
        # eigenen Broadcast, der finale Wert einen weiteren -- wie viele der
        # dazwischenliegenden Broadcasts throttlebedingt ausfallen ist nicht
        # deterministisch, daher wird eingesammelt, bis das finale `iris`
        # ankommt, statt sich auf eine feste Nachrichtenanzahl zu verlassen.
        data = ws.receive_json()
        while next(c for c in data["channels"] if c["index"] == 1)["iris"] != pytest.approx(0.9):
            data = ws.receive_json()

    channel1 = next(c for c in data["channels"] if c["index"] == 1)
    assert channel1["iris"] == pytest.approx(0.9)

    driver = web_app.app.state.ptz.drivers["cam1"]
    # Token-Bucket (15 Hz) laesst innerhalb derselben Millisekunden nicht alle
    # vier Sends durch -- mindestens der erste und der finale muessen aber
    # angekommen sein.
    assert driver.set_iris_calls[0] == pytest.approx(0.1)
    assert driver.set_iris_calls[-1] == pytest.approx(0.9)
    assert len(driver.set_iris_calls) <= 4


def test_set_iris_on_unmapped_channel_is_ignored(client) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_json({"type": "set_iris", "channel": 2, "value": 0.5, "final": True})
        # Kanal 2 hat keine Kamera zugeordnet (siehe TEST_CONFIG) -> kein
        # Broadcast, kein Treiberaufruf. Kein receive_json() hier, um nicht
        # auf eine Nachricht zu warten, die nie kommt.

    driver = web_app.app.state.ptz.drivers["cam1"]
    assert driver.set_iris_calls == []


def test_encoder_select_endpoint_advances_function(client) -> None:
    response = client.post("/api/channels/1/encoder/select")

    assert response.status_code == 200
    assert response.json()["function"] == "gain"


def test_encoder_turn_over_websocket_sends_live_to_driver(client) -> None:
    # Nutzerentscheid: Drehen sendet gain/pedestal sofort live (ueber den
    # Rate-Limiter), nicht erst nach dem Encoder-Push.
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_json({"type": "encoder_turn", "channel": 1, "delta": 1})
        data = ws.receive_json()

    channel1 = next(c for c in data["channels"] if c["index"] == 1)
    assert channel1["encoder"]["value"] == 1
    assert channel1["encoder"]["saved"] is False

    driver = web_app.app.state.ptz.drivers["cam1"]
    assert driver.step_gain_calls == [1]


def test_encoder_commit_over_websocket_only_sets_saved_flag(client) -> None:
    # Encoder-Push sendet seit Nutzerentscheid keinen Kamerabefehl mehr --
    # der Wert ist durch das Drehen bereits live aktuell, Push ist rein
    # visuelles "gespeichert"-Feedback.
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_json({"type": "encoder_turn", "channel": 1, "delta": 1})
        ws.receive_json()
        ws.send_json({"type": "encoder_commit", "channel": 1})
        data = ws.receive_json()

    channel1 = next(c for c in data["channels"] if c["index"] == 1)
    assert channel1["encoder"]["saved"] is True
    assert channel1["encoder"]["value"] == 1

    driver = web_app.app.state.ptz.drivers["cam1"]
    assert driver.step_gain_calls == [1]  # weiterhin nur der eine Dreh-Tick, kein Push-Befehl


def test_disconnect_camera_endpoint_marks_disconnected(client) -> None:
    response = client.post("/api/channels/1/camera/disconnect")

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert web_app.app.state.ptz.drivers["cam1"].connected is False


def test_disconnect_camera_endpoint_unmapped_channel_returns_404(client) -> None:
    response = client.post("/api/channels/5/camera/disconnect")

    assert response.status_code == 404


def test_rename_camera_endpoint_updates_name_without_disconnecting(client) -> None:
    response = client.post("/api/channels/1/camera/name", json={"name": "Studio Weit"})

    assert response.status_code == 200
    assert web_app.app.state.ptz.cameras["cam1"].name == "Studio Weit"


def test_companion_config_endpoint_persists(client, monkeypatch) -> None:
    async def fake_is_reachable(client, host, port):
        return True

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)

    response = client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})

    assert response.status_code == 200
    assert web_app.app.state.ptz.config.companion.host == "192.168.0.50"


def test_companion_config_endpoint_marks_connected_when_reachable(client, monkeypatch) -> None:
    async def fake_is_reachable(client, host, port):
        return True

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)

    client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})

    assert web_app.app.state.ptz.companion_connected is True
    setup_response = client.get("/setup")
    assert "Saved" in setup_response.text


def test_companion_config_endpoint_rejects_unreachable_and_stays_disconnected(client, monkeypatch) -> None:
    host_before_call = web_app.app.state.ptz.config.companion.host

    async def fake_is_reachable(client, host, port):
        return False

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)

    response = client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})

    assert response.status_code == 502
    assert web_app.app.state.ptz.companion_connected is False
    assert web_app.app.state.ptz.config.companion.host == host_before_call


def test_companion_disconnect_clears_connected_flag(client, monkeypatch) -> None:
    async def fake_is_reachable(client, host, port):
        return True

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)
    client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})
    assert web_app.app.state.ptz.companion_connected is True

    client.post("/api/companion/config", json={"host": "", "port": 8000})

    assert web_app.app.state.ptz.companion_connected is False
    setup_response = client.get("/setup")
    assert "data-companion-save>Save<" in setup_response.text


def test_setup_page_does_not_show_saved_when_companion_configured_but_unreachable_at_startup(
    monkeypatch, tmp_path
) -> None:
    """Bugfix: config.yaml kann einen Companion-Host enthalten, ohne dass
    Companion tatsaechlich laeuft -- die Setup-Seite darf 'Saved' dann nicht
    allein aus `companion.host` ableiten (siehe lifespan-Erreichbarkeitspruefung)."""
    config = AppConfig.model_validate(
        {
            "cameras": [
                {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
            ],
            "banks": [{"name": "Bank A", "channels": [{"camera": "cam1"}]}],
            "channel_defaults": {"fader": "iris"},
            "global": {"rate_limit_hz": 15, "web_port": 8600},
            "companion": {"host": "192.168.0.50", "port": 8000},
        }
    )
    monkeypatch.setattr(web_app, "load_config", lambda path="config.yaml": config)
    monkeypatch.setattr(web_app, "_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )

    async def fake_is_reachable(client, host, port):
        return False

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)

    with TestClient(web_app.app) as test_client:
        assert web_app.app.state.ptz.companion_connected is False
        response = test_client.get("/setup")

    assert response.status_code == 200
    assert "data-companion-save>Save<" in response.text
    assert "is-connected\" data-companion-save" not in response.text


def test_assign_channel_companion_endpoint_persists(client) -> None:
    response = client.post("/api/channels/1/companion", json={"page": 1, "row": 0, "column": 2})

    assert response.status_code == 200
    target = web_app.app.state.ptz.config.banks[0].channels[0].companion
    assert target.page == 1 and target.row == 0 and target.column == 2


def test_assign_channel_companion_endpoint_unmapped_channel_returns_400(client) -> None:
    response = client.post("/api/channels/2/companion", json={"page": 1, "row": 0, "column": 2})

    assert response.status_code == 400


def test_trigger_companion_select_endpoint_success(client, monkeypatch) -> None:
    async def fake_is_reachable(client, host, port):
        return True

    monkeypatch.setattr(web_app, "is_reachable", fake_is_reachable)

    client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})
    client.post("/api/channels/1/companion", json={"page": 1, "row": 0, "column": 2})
    calls = []

    async def fake_press_button(client, host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    response = client.post("/api/channels/1/companion/trigger")

    assert response.status_code == 200
    assert calls == [("192.168.0.50", 8000, 1, 0, 2)]


def test_trigger_companion_select_endpoint_error_returns_502(client, monkeypatch) -> None:
    client.post("/api/companion/config", json={"host": "192.168.0.50", "port": 8000})
    client.post("/api/channels/1/companion", json={"page": 1, "row": 0, "column": 2})

    async def failing_press_button(client, host, port, page, row, column):
        raise CompanionError("boom")

    monkeypatch.setattr(core_application, "press_button", failing_press_button)

    response = client.post("/api/channels/1/companion/trigger")

    assert response.status_code == 502
    assert web_app.app.state.ptz.drivers["cam1"].connected is True


def test_register_camera_endpoint_creates_and_connects(client) -> None:
    response = client.post(
        "/api/channels/2/camera",
        json={"name": "CAM 2", "host": "127.0.0.1", "port": 8082},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["model"] == "AW-UE160"

    driver = web_app.app.state.ptz.drivers["cam2"]
    assert driver.host == "127.0.0.1"
    assert driver.port == 8082


def test_register_camera_endpoint_empty_host_returns_400(client) -> None:
    response = client.post("/api/channels/2/camera", json={"name": "", "host": "", "port": ""})

    assert response.status_code == 400


def test_available_channel_buttons_endpoint_returns_connected_models_catalog(client) -> None:
    # cam1 ist in TEST_CONFIG Kanal 1 zugeordnet und verbindet beim Start
    # (FakeCameraDriver meldet immer "AW-UE160", siehe tests/fakes.py).
    response = client.get("/api/channels/1/available-buttons")

    assert response.status_code == 200
    features = response.json()["features"]
    assert features["drs"] == "DRS"
    assert "knee_manual" in features


def test_available_channel_buttons_endpoint_empty_for_unmapped_channel(client) -> None:
    response = client.get("/api/channels/5/available-buttons")

    assert response.status_code == 200
    assert response.json()["features"] == {}


def test_assign_channel_button_endpoint_persists_and_queries_state(client) -> None:
    driver = web_app.app.state.ptz.drivers["cam1"]
    driver.query_button_feature_result = True

    response = client.post("/api/channels/1/buttons/button2", json={"feature_key": "drs"})

    assert response.status_code == 200
    assert driver.query_button_feature_calls == ["drs"]
    cam_state = web_app.app.state.ptz.state_store.get_camera("cam1")
    assert cam_state.feature_states["drs"] is True
