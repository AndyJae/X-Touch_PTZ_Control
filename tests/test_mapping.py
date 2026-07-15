from __future__ import annotations

from core.mapping import build_mapping_from_config


def _config(channels: list[dict | None]) -> dict:
    return {
        "banks": [{"name": "Bank A", "channels": channels}],
        "channel_defaults": {"fader": "iris"},
    }


def test_maps_channels_to_cameras_in_order() -> None:
    engine = build_mapping_from_config(_config([{"camera": "cam1"}, {"camera": "cam2"}]))

    ch1 = engine.get_channel("fader", 1)
    ch2 = engine.get_channel("fader", 2)

    assert ch1 is not None and ch1.camera_id == "cam1" and ch1.function == "iris"
    assert ch2 is not None and ch2.camera_id == "cam2" and ch2.function == "iris"


def test_unassigned_channel_is_missing_not_none_camera() -> None:
    engine = build_mapping_from_config(_config([{"camera": "cam1"}, None, {"camera": "cam3"}]))

    assert engine.get_channel("fader", 2) is None
    ch3 = engine.get_channel("fader", 3)
    assert ch3 is not None and ch3.camera_id == "cam3"


def test_empty_banks_yields_no_channels() -> None:
    engine = build_mapping_from_config({"banks": [], "channel_defaults": {"fader": "iris"}})

    assert engine.channels_for_type("fader") == {}


def test_fader_function_comes_from_channel_defaults() -> None:
    config = _config([{"camera": "cam1"}])
    config["channel_defaults"]["fader"] = "iris"

    engine = build_mapping_from_config(config)

    assert engine.get_channel("fader", 1).function == "iris"


def test_channels_for_type_returns_only_requested_type() -> None:
    engine = build_mapping_from_config(_config([{"camera": "cam1"}]))
    engine.set_channel("button", 1, "cam1", "awb_trigger")

    fader_channels = engine.channels_for_type("fader")

    assert set(fader_channels) == {1}
    assert fader_channels[1].camera_id == "cam1"
