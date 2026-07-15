from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import web.app as web_app
from core.state import CameraState

TEST_CONFIG = {
    "cameras": [
        {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
    ],
    "banks": [{"name": "Bank A", "channels": [{"camera": "cam1"}]}],
    "channel_defaults": {"fader": "iris"},
    "global": {"rate_limit_hz": 15, "web_port": 8600},
}


class FakeCameraDriver:
    """Implementiert `drivers.base.CameraDriver`, ohne echtes HTTP zu senden --
    Spec-Verdrahtung (Mapping -> Rate-Limiter -> Driver -> StateStore ->
    WebSocket) wird so getestet, ohne von einer echten/emulierten Kamera
    abhaengig zu sein (Kontrakt-Test statt Wire-Format-Test; Wire-Format wird
    separat in tests/test_panasonic.py gegen Mock-HTTP geprueft)."""

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self.iris = 0.0
        self.set_iris_calls: list[float] = []

    async def connect(self) -> None:
        self._connected = True
        self.model = "AW-UE160"

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def set_iris(self, value: float) -> None:
        self.set_iris_calls.append(value)
        self.iris = value

    async def set_auto_iris(self, on: bool) -> None:
        pass

    async def set_gain_db(self, db: int) -> None:
        pass

    async def step_gain(self, delta_db: int) -> int:
        return 0

    async def set_pedestal(self, value: int) -> None:
        pass

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        pass

    async def set_nd(self, index: int) -> None:
        pass

    async def cycle_nd(self) -> int:
        return 0

    async def set_shutter(self, mode: str, value: int | None) -> None:
        pass

    async def trigger_awb(self) -> None:
        pass

    async def set_bars(self, on: bool) -> None:
        pass

    async def recall_preset(self, number: int) -> None:
        pass

    async def get_state(self) -> CameraState:
        return CameraState(iris=self.iris, auto_iris=False, gain_db=0, nd_index=0)

    def subscribe(self, callback) -> None:
        pass


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(web_app, "load_config", lambda path="config.yaml": TEST_CONFIG)
    monkeypatch.setattr(
        web_app,
        "build_driver",
        lambda camera: FakeCameraDriver(camera["host"], camera.get("port", 80)),
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
