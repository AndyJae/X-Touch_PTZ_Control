"""drivers/panasonic_models/registry.py -- Camera model registry.

Loads every module in `drivers/panasonic_models/` (except itself) on first
access and indexes them by `CAMERA_ID` (plus optional `CAMERA_ID_ALIASES`).
`PanasonicAWDriver.connect()` calls `resolve_model()` with the model string
detected via `QID` to find the matching BUTTON_FEATURES/
BUTTON_FEATURE_LABELS module -- unknown models return `None`, and the
driver simply shows no button features.
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

    def load_package(self, package_name: str = _PACKAGE_NAME) -> int:
        package = importlib.import_module(package_name)
        loaded = 0
        for info in pkgutil.iter_modules(package.__path__):
            if info.name == "registry":
                continue
            full_name = f"{package_name}.{info.name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.error("Konnte '%s' nicht importieren: %s", full_name, exc)
                continue
            self.register(module)
            loaded += 1
        return loaded


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    """Lazy singleton -- populated once, then read-only."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
        _registry.load_package()
    return _registry


def resolve_model(camera_id: str | None) -> ModuleType | None:
    return get_registry().resolve(camera_id)
