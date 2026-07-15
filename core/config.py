"""core/config.py -- Typisiertes Config-Schema, Spec §4.

"Validierung strikt über pydantic; bei Fehlern klare Meldung mit Pfad ins
YAML." (Spec §4) -- ersetzt das bisherige rohe `dict`, das an mehreren
Stellen (main.py, web/app.py, core/mapping.py) mit verstreuten
.get(..., default)-Aufrufen behandelt wurde.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    """Ungültige config.yaml -- Meldung enthält den YAML-Pfad zum Fehler."""


class MidiConfig(BaseModel):
    transport: Literal["system"] = "system"
    input_port: str = ""
    output_port: str = ""
    device_profile: str = "xtouch_extender"


class CameraFeedbackConfig(BaseModel):
    update_notifications: bool = False
    notify_listen_port: int | None = None
    lens_info: bool = False


class CameraConfig(BaseModel):
    id: str
    name: str
    driver: str
    host: str
    port: int = 80
    feedback: CameraFeedbackConfig = Field(default_factory=CameraFeedbackConfig)


class BankChannelConfig(BaseModel):
    camera: str


class BankConfig(BaseModel):
    name: str
    channels: list[BankChannelConfig | None] = Field(default_factory=list)


class ButtonActionConfig(BaseModel):
    action: str
    step_db: int | None = None


class EncoderDefaultsConfig(BaseModel):
    functions: list[str] = Field(default_factory=list)


class ChannelDefaultsConfig(BaseModel):
    fader: str = "iris"
    encoder: EncoderDefaultsConfig = Field(default_factory=EncoderDefaultsConfig)
    buttons: dict[str, ButtonActionConfig] = Field(default_factory=dict)


class GlobalConfig(BaseModel):
    rate_limit_hz: float = 15.0
    send_final_on_release: bool = True
    log_level: str = "INFO"
    web_port: int = 8600


class AppConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    midi: MidiConfig = Field(default_factory=MidiConfig)
    cameras: list[CameraConfig] = Field(default_factory=list)
    banks: list[BankConfig] = Field(default_factory=list)
    channel_defaults: ChannelDefaultsConfig = Field(default_factory=ChannelDefaultsConfig)
    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")

    @model_validator(mode="after")
    def _check_duplicate_notify_ports(self) -> "AppConfig":
        # Spec §4: "Doppelte notify_listen_port-Werte -> Startabbruch mit Fehlermeldung."
        ports = [
            cam.feedback.notify_listen_port
            for cam in self.cameras
            if cam.feedback.notify_listen_port is not None
        ]
        dupes = sorted({p for p in ports if ports.count(p) > 1})
        if dupes:
            raise ValueError(f"doppelte notify_listen_port-Werte über Kameras hinweg: {dupes}")
        return self


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"{path}: {errors}") from exc
