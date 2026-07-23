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
    # ND-Filter-Katalog (siehe core/application.py::apply_encoder_turn()s
    # "nd"-Zweig) -- ebenfalls aus dem echten AW-UE160-Modul. Tests fuer ein
    # Modell OHNE ND-Filter (z. B. AW-HE50) setzen `nd_options = None` auf
    # der Instanz.
    nd_options = _aw_ue160_model.ND_FILTER_OPTIONS
    # AW-UE160-Katalog hat keine Super-Gain-Kopplung (Nutzerauftrag
    # 2026-07-20, siehe drivers/panasonic_aw.py::effective_gain_max_db) --
    # Tests, die das simulieren wollen, setzen `gain_max_db_super_gain_off`/
    # `gain_super_gain_on` auf der Instanz.
    gain_max_db_super_gain_off: int | None = None

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self.iris = 0.0
        self.iris_f_number: str | None = None
        self.query_f_number_calls = 0
        self.gain_db = 0
        self.gain_auto = False
        # Simuliert eine kameraseitige Ablehnung (z. B. ER3, siehe
        # AW-UE100 mit Super Gain aus: Werte >36dB, obwohl GAIN_MAX_DB=42) --
        # einmalig, wird beim naechsten step_gain()-Aufruf geworfen und dann
        # zurueckgesetzt.
        self.raise_on_next_step_gain: Exception | None = None
        self.gain_super_gain_on: bool | None = None
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
        self.nd_index: int | None = 0
        self.set_nd_calls: list[int] = []
        # Simuliert eine kameraseitige Ablehnung, analog zu
        # `raise_on_next_step_gain` -- einmalig, wird beim naechsten
        # set_nd()-Aufruf geworfen und dann zurueckgesetzt.
        self.raise_on_next_set_nd: Exception | None = None
        # Von core.application._wire_camera_events() registrierter Callback --
        # Tests rufen ihn direkt auf, um extern ausgeloeste Kamera-Events
        # (Update-Notification-Kanal, siehe drivers/panasonic_aw.py) zu
        # simulieren, ohne echtes TCP/HTTP.
        self.subscribed_callback = None

    async def connect(self) -> None:
        self._connected = True
        self.model = "AW-UE160"

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def effective_gain_max_db(self) -> int | None:
        if self.gain_max_db_super_gain_off is not None and self.gain_super_gain_on is not True:
            return self.gain_max_db_super_gain_off
        return self.gain_max_db

    async def set_iris(self, value: float) -> None:
        self.set_iris_calls.append(value)
        self.iris = value

    async def set_auto_iris(self, on: bool) -> None:
        pass

    async def set_gain_db(self, db: int) -> None:
        self.gain_db = db
        self.gain_auto = False

    async def set_gain_auto(self) -> None:
        self.gain_db = None
        self.gain_auto = True

    async def step_gain(self, delta_db: int) -> tuple[int | None, bool]:
        # Auto/AGC-Verhalten (Nutzerauftrag 2026-07-20) spiegelt
        # drivers/panasonic_aw.py::step_gain() -- siehe dort fuer die live
        # gegen AW-UE160/AW-UE100 bestaetigte Grenzuebergangs-Logik.
        self.step_gain_calls.append(delta_db)
        if self.raise_on_next_step_gain is not None:
            exc = self.raise_on_next_step_gain
            self.raise_on_next_step_gain = None
            raise exc
        if self.gain_auto:
            if delta_db <= 0:
                return None, True
            self.gain_db = min(self.effective_gain_max_db, self.gain_min_db + (delta_db - 1))
            self.gain_auto = False
            return self.gain_db, False
        new_db = self.gain_db + delta_db
        if new_db < self.gain_min_db:
            self.gain_db = None
            self.gain_auto = True
            return None, True
        self.gain_db = min(self.effective_gain_max_db, new_db)
        return self.gain_db, False

    async def set_pedestal(self, value: int) -> None:
        pass

    async def step_pedestal(self, delta: int) -> int:
        self.step_pedestal_calls.append(delta)
        self.pedestal += delta
        return self.pedestal

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        pass

    async def set_nd(self, index: int) -> None:
        self.set_nd_calls.append(index)
        if self.raise_on_next_set_nd is not None:
            exc = self.raise_on_next_set_nd
            self.raise_on_next_set_nd = None
            raise exc
        self.nd_index = index

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

    async def query_f_number(self) -> str | None:
        self.query_f_number_calls += 1
        return self.iris_f_number

    async def get_state(self) -> CameraState:
        return CameraState(
            iris=self.iris,
            iris_f_number=self.iris_f_number,
            auto_iris=False,
            gain_db=self.gain_db,
            gain_auto=self.gain_auto,
            pedestal=self.pedestal,
            nd_index=self.nd_index,
        )

    def subscribe(self, callback) -> None:
        self.subscribed_callback = callback
