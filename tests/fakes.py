"""tests/fakes.py -- Gemeinsame Test-Doubles.

`FakeCameraDriver` implementiert `drivers.base.CameraDriver`, ohne echtes
HTTP zu senden -- Kontrakt-Test statt Wire-Format-Test (das Wire-Format wird
separat in tests/test_panasonic.py gegen Mock-HTTP geprueft). Wird sowohl von
tests/test_web_app.py (Interface-Schicht, über FastAPI/WebSocket) als auch
von tests/test_application.py (Anwendungsschicht, direkt) verwendet.
"""

from __future__ import annotations

from core.state import CameraState
from drivers.panasonic_models import aw_ue160 as _aw_ue160_model

# Wiederverwendet den echten AW-UE160-Katalog (Spec §9a, `connect()` meldet
# unten immer "AW-UE160") statt einen zweiten, parallelen Test-Katalog zu
# erfinden, der davon abweichen koennte -- Sinn dieses Fakes ist nur, kein
# echtes HTTP zu senden, nicht eine andere Feature-Liste zu simulieren.
# `PanasonicAWDriver.BUTTON_FEATURES` ist seit dem Modell-Registry-Umbau kein
# fester Klassenkatalog mehr (siehe dortiger Kommentar), daher hier direkt
# aus dem Modell-Modul statt von der Treiberklasse.


class FakeCameraDriver:
    BUTTON_FEATURES = _aw_ue160_model.BUTTON_FEATURES
    BUTTON_FEATURE_LABELS = _aw_ue160_model.BUTTON_FEATURE_LABELS
    # Gain-/Pedestal-Wertebereich (siehe core/application.py::_encoder_value_range()),
    # ebenfalls aus dem echten AW-UE160-Modul statt einem zweiten Test-Katalog.
    gain_min_db = _aw_ue160_model.GAIN_MIN_DB
    gain_max_db = _aw_ue160_model.GAIN_MAX_DB
    gain_step_db = _aw_ue160_model.GAIN_STEP_DB
    pedestal_min = _aw_ue160_model.PEDESTAL_MIN
    pedestal_max = _aw_ue160_model.PEDESTAL_MAX

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self.iris = 0.0
        self.gain_db = 0
        self.pedestal = 0
        self.set_iris_calls: list[float] = []
        self.button_feature_calls: list[tuple[str, bool | None]] = []
        self.query_button_feature_calls: list[str] = []
        # Steuert, was query_button_feature() als naechstes zurueckgibt (siehe
        # core/application.py::assign_channel_button(), Nutzerentscheid
        # 2026-07-18: Zustand beim Zuweisen sofort abfragen) -- Default None
        # entspricht "kein Query-Kommando bekannt/Zustand unbekannt".
        self.query_button_feature_result: bool | None = None
        self.step_gain_calls: list[int] = []
        self.step_pedestal_calls: list[int] = []

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
        self.step_gain_calls.append(delta_db)
        self.gain_db += delta_db
        return self.gain_db

    async def set_pedestal(self, value: int) -> None:
        pass

    async def step_pedestal(self, delta: int) -> int:
        self.step_pedestal_calls.append(delta)
        self.pedestal += delta
        return self.pedestal

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        pass

    async def set_nd(self, index: int) -> None:
        pass

    async def cycle_nd(self) -> int:
        return 0

    async def trigger_awb(self) -> None:
        pass

    async def set_bars(self, on: bool) -> None:
        pass

    async def recall_preset(self, number: int) -> None:
        pass

    async def trigger_button_feature(self, key: str, *, enabled: bool | None = None) -> None:
        self.button_feature_calls.append((key, enabled))

    async def query_button_feature(self, key: str) -> bool | None:
        self.query_button_feature_calls.append(key)
        return self.query_button_feature_result

    async def get_state(self) -> CameraState:
        return CameraState(
            iris=self.iris, auto_iris=False, gain_db=self.gain_db, pedestal=self.pedestal, nd_index=0
        )

    def subscribe(self, callback) -> None:
        pass
