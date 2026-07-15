from __future__ import annotations

import pytest

from core.config import AppConfig, ConfigError, load_config


def test_shipped_config_yaml_is_valid() -> None:
    config = load_config("config.yaml")

    assert config.global_.web_port == 8600
    assert config.channel_defaults.fader == "iris"


def test_defaults_apply_to_minimal_config() -> None:
    config = AppConfig.model_validate({})

    assert config.midi.transport == "system"
    assert config.cameras == []
    assert config.global_.rate_limit_hz == 15.0
    assert config.global_.web_port == 8600


def test_global_alias_reads_from_yaml_key() -> None:
    config = AppConfig.model_validate({"global": {"web_port": 9000}})

    assert config.global_.web_port == 9000


def test_camera_missing_required_field_raises_config_error(tmp_path) -> None:
    bad_yaml = tmp_path / "config.yaml"
    bad_yaml.write_text("cameras:\n  - id: cam1\n    driver: panasonic_aw\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="cameras.0"):
        load_config(bad_yaml)


def test_duplicate_notify_listen_port_raises_config_error(tmp_path) -> None:
    bad_yaml = tmp_path / "config.yaml"
    bad_yaml.write_text(
        """
cameras:
  - id: cam1
    name: "CAM 1"
    driver: panasonic_aw
    host: 127.0.0.1
    feedback: { notify_listen_port: 31004 }
  - id: cam2
    name: "CAM 2"
    driver: panasonic_aw
    host: 127.0.0.2
    feedback: { notify_listen_port: 31004 }
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="31004"):
        load_config(bad_yaml)


def test_unassigned_bank_channel_is_none() -> None:
    config = AppConfig.model_validate({"banks": [{"name": "Bank A", "channels": [{"camera": "cam1"}, None]}]})

    assert config.banks[0].channels[0].camera == "cam1"
    assert config.banks[0].channels[1] is None
