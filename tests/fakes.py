"""tests/fakes.py -- Gemeinsame Test-Doubles.

`FakeCameraDriver` implementiert `drivers.base.CameraDriver`, ohne echtes
HTTP zu senden -- Kontrakt-Test statt Wire-Format-Test (das Wire-Format wird
separat in tests/test_panasonic.py gegen Mock-HTTP geprueft). Wird sowohl von
tests/test_web_app.py (Interface-Schicht, über FastAPI/WebSocket) als auch
von tests/test_application.py (Anwendungsschicht, direkt) verwendet.
"""

from __future__ import annotations

from core.state import CameraState
from drivers.panasonic_aw import PanasonicAWDriver


class FakeCameraDriver:
    # Wiederverwendet den echten Katalog (Spec §9a) statt einen zweiten,
    # parallelen Test-Katalog zu erfinden, der von PanasonicAWDriver
    # abweichen könnte -- Sinn dieses Fakes ist nur, kein echtes HTTP zu
    # senden, nicht eine andere Feature-Liste zu simulieren.
    BUTTON_FEATURES = PanasonicAWDriver.BUTTON_FEATURES
    BUTTON_FEATURE_LABELS = PanasonicAWDriver.BUTTON_FEATURE_LABELS

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self.iris = 0.0
        self.set_iris_calls: list[float] = []
        self.button_feature_calls: list[tuple[str, bool | None]] = []
        self.cycle_feature_calls: list[tuple[str, int]] = []

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

    async def trigger_button_feature(self, key: str, *, enabled: bool | None = None) -> None:
        self.button_feature_calls.append((key, enabled))

    async def cycle_button_feature(self, key: str, target_index: int) -> None:
        self.cycle_feature_calls.append((key, target_index))

    async def get_state(self) -> CameraState:
        return CameraState(iris=self.iris, auto_iris=False, gain_db=0, nd_index=0)

    def subscribe(self, callback) -> None:
        pass
