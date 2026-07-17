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


class CompanionTarget(BaseModel):
    """Bitfocus-Companion-Button-Adresse (Page/Row/Column, v3-Location-Schema),
    für den SELECT-Button eines Kanals -- bewusste Erweiterung über den
    ursprünglichen v1-Scope hinaus (Spec §9 Kommentar), nicht Teil des
    Kamera-Domänenmodells."""

    page: int
    row: int
    column: int


class CompanionConfig(BaseModel):
    """Globale Bitfocus-Companion-Instanz (eine für alle Kanäle,
    Nutzerentscheid). `port` ist eine Vorbelegung/Platzhalter (Companions
    eigene Doku nennt keinen fest verifizierten Default-Port -- er läuft auf
    demselben Host/Port wie die Companion-Weboberfläche, dort typischerweise
    8000, aber in Companion selbst konfigurierbar), kein behaupteter
    verifizierter Wert."""

    host: str = ""
    port: int = 8000


class BankChannelConfig(BaseModel):
    camera: str
    # Feature-Button-Zuordnung pro Kanal (Spec §9a): Schlüssel nur "button2"/
    # "button3" -- Button 1 ist laut Spec §9 fest für die Encoder-
    # Funktionsauswahl reserviert und hier ausgeschlossen. Werte sind freie
    # Feature-Keys (z. B. "drs", "knee"); nicht gegen eine feste Liste
    # geprüft, da gültige Keys vom erkannten Kameramodell abhängen (gleiches
    # Muster wie `camera` oben, das auch nicht gegen `cameras` geprüft wird).
    buttons: dict[str, str] = Field(default_factory=dict)
    # SELECT-Button-Ziel in Bitfocus Companion (siehe CompanionTarget) --
    # optional, kein Kanal ist standardmäßig zugeordnet.
    companion: CompanionTarget | None = None

    @model_validator(mode="after")
    def _check_button_slots(self) -> "BankChannelConfig":
        unknown = sorted(set(self.buttons) - {"button2", "button3"})
        if unknown:
            raise ValueError(
                f"ungültige Button-Slots {unknown} -- nur 'button2'/'button3' erlaubt "
                "(Button 1 ist für die Encoder-Funktionsauswahl reserviert, Spec §9)"
            )
        return self


class BankConfig(BaseModel):
    name: str
    channels: list[BankChannelConfig | None] = Field(default_factory=list)


class ButtonActionConfig(BaseModel):
    action: str
    step_db: int | None = None


class ChannelDefaultsConfig(BaseModel):
    fader: str = "iris"
    # Encoder-Funktionsliste ist seit Spec-Nutzerentscheid fest im Code
    # verdrahtet (core/application.py._ENCODER_FUNCTIONS: gain/pedestal/
    # camera_status) statt konfigurierbar -- kein Feld hier mehr noetig.
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
    companion: CompanionConfig = Field(default_factory=CompanionConfig)
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


def save_config(path: str | Path, config: AppConfig) -> None:
    """Schreibt `config` als YAML nach `path`. Voller Datei-Rewrite, kein
    chirurgisches Patchen einzelner Felder -- unkritisch, solange die Datei
    keine Kommentare/eigene Formatierung enthält (aktuell der Fall für
    config.yaml). Gleichzeitige manuelle Bearbeitung der Datei, während die
    App läuft, würde dabei überschrieben."""
    data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
