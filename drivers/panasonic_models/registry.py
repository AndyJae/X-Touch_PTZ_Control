"""drivers/panasonic_models/registry.py -- Modell-Registry (Spec §9a).

Laedt beim ersten Zugriff alle Module aus `drivers/panasonic_models/` (ausser
sich selbst) und indiziert sie nach `CAMERA_ID` (+ optionalen
`CAMERA_ID_ALIASES`). `PanasonicAWDriver.connect()` ruft `resolve_model()`
mit dem per `QID` erkannten Modell-String auf, um das passende
BUTTON_FEATURES/BUTTON_FEATURE_LABELS-Modul zu finden -- unbekannte Modelle
liefern `None` (kein erfundener Fallback), der Treiber zeigt dann einfach
keine Button-Features an (siehe `available_button_features()` in
core/application.py, bereits tolerant gegenueber fehlendem Katalog).

Angelehnt an `C:\\smart_reset_work\\core\\registry.py`s `PluginRegistry`, aber
ohne dessen Transport-Registry-Haelfte -- PTZ_Control hat nur einen Treiber
(`PanasonicAWDriver`), der alle diese Modelle ueber denselben CGI-Mechanismus
anspricht, es gibt kein Pendant zu deren protocol-spezifischen Transports.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

LOGGER = logging.getLogger("ptz_control.panasonic_models")

_PACKAGE_NAME = __name__.rsplit(".", 1)[0]  # "drivers.panasonic_models"


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModuleType] = {}

    def register(self, module: ModuleType) -> None:
        camera_id = getattr(module, "CAMERA_ID", "")
        if not camera_id or not isinstance(camera_id, str):
            LOGGER.error("Modul '%s' hat keine gueltige CAMERA_ID -- uebersprungen.", module.__name__)
            return
        self._models[camera_id] = module
        for alias in getattr(module, "CAMERA_ID_ALIASES", []):
            if isinstance(alias, str) and alias.strip():
                self._models[alias.strip()] = module

    def resolve(self, camera_id: str | None) -> ModuleType | None:
        if not camera_id:
            return None
        return self._models.get(camera_id)

    def registered_camera_ids(self) -> list[str]:
        return sorted({getattr(m, "CAMERA_ID", "") for m in self._models.values() if getattr(m, "CAMERA_ID", "")})

    def load_package(self, package_name: str = _PACKAGE_NAME) -> int:
        package = importlib.import_module(package_name)
        loaded = 0
        for info in pkgutil.iter_modules(package.__path__):
            if info.name == "registry":
                continue
            full_name = f"{package_name}.{info.name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:  # pragma: no cover - defensive, siehe PluginRegistry-Vorbild
                LOGGER.error("Konnte '%s' nicht importieren: %s", full_name, exc)
                continue
            self.register(module)
            loaded += 1
        return loaded


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    """Lazy Singleton -- einmalig befuellt, danach nur gelesen (kein Lock noetig,
    analog zum Vorbild)."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
        _registry.load_package()
    return _registry


def resolve_model(camera_id: str | None) -> ModuleType | None:
    return get_registry().resolve(camera_id)
