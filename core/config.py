"""core/config.py -- Typed config.yaml schema, validated via pydantic."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    """Invalid config.yaml -- message includes the YAML path to the error."""


class MidiConfig(BaseModel):
    input_port: str = ""
    output_port: str = ""


class CameraConfig(BaseModel):
    id: str
    name: str
    driver: str
    host: str
    port: int = 80


class CompanionTarget(BaseModel):
    """Bitfocus Companion button address (page/row/column, v3 location
    schema) for a channel's SELECT button."""

    page: int
    row: int
    column: int


class CompanionConfig(BaseModel):
    """A single Bitfocus Companion instance, shared across all channels."""

    host: str = ""
    port: int = 8000


class BankChannelConfig(BaseModel):
    camera: str
    # Feature key assigned to each button slot ("button2"/"button3" only --
    # button 1 is reserved for encoder function selection). Values are free
    # feature keys (e.g. "drs", "knee"), not validated against a fixed list
    # since valid keys depend on the detected camera model.
    buttons: dict[str, str] = Field(default_factory=dict)
    # Companion SELECT target for this channel; optional.
    companion: CompanionTarget | None = None

    @model_validator(mode="after")
    def _check_button_slots(self) -> "BankChannelConfig":
        unknown = sorted(set(self.buttons) - {"button2", "button3"})
        if unknown:
            raise ValueError(
                f"invalid button slots {unknown} -- only 'button2'/'button3' allowed "
                "(button 1 is reserved for encoder function selection)"
            )
        return self


class BankConfig(BaseModel):
    name: str
    channels: list[BankChannelConfig | None] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    rate_limit_hz: float = 15.0
    log_level: str = "INFO"
    web_port: int = 8600


class AppConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    midi: MidiConfig = Field(default_factory=MidiConfig)
    cameras: list[CameraConfig] = Field(default_factory=list)
    banks: list[BankConfig] = Field(default_factory=list)
    companion: CompanionConfig = Field(default_factory=CompanionConfig)
    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        # A missing config.yaml behaves like an empty one -- every field has
        # a default.
        raw = {}
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"{path}: {errors}") from exc


def save_config(path: str | Path, config: AppConfig) -> None:
    """Writes `config` as YAML to `path`. Always a full file rewrite, not a
    surgical patch of individual fields."""
    data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
