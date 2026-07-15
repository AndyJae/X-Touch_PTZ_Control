from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.application as core_application
import web.app as web_app
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
def client(monkeypatch):
    monkeypatch.setattr(web_app, "load_config", lambda path="config.yaml": TEST_CONFIG)
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    with TestClient(web_app.app) as test_client:
        yield test_client


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


def test_connect_endpoint_returns_model_and_status(client) -> None:
    response = client.post("/api/cameras/cam1/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["model"] == "AW-UE160"


def test_connect_endpoint_unknown_camera_returns_404(client) -> None:
    response = client.post("/api/cameras/does-not-exist/connect")

    assert response.status_code == 404
