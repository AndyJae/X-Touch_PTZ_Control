from __future__ import annotations

import asyncio

import httpx
import pytest

from drivers.base import CameraCommandError
from drivers.panasonic_aw import (
    PanasonicAWDriver,
    _data_to_iris,
    _iris_to_data,
    _parse_lens_info_iris,
    _parse_notification_payload,
)


def _run(coro):
    return asyncio.run(coro)


def _build_driver(handler) -> PanasonicAWDriver:
    driver = PanasonicAWDriver(host="192.168.0.10", port=80)
    driver._client = httpx.AsyncClient(
        base_url="http://192.168.0.10:80",
        transport=httpx.MockTransport(handler),
    )
    driver._connected = True
    return driver


def test_iris_scaling_boundaries() -> None:
    assert _iris_to_data(0.0) == 0x555
    assert _iris_to_data(1.0) == 0xFFF
    assert _data_to_iris(0x555) == pytest.approx(0.0)
    assert _data_to_iris(0xFFF) == pytest.approx(1.0)


def test_set_iris_sends_correct_url_and_hash_encoding() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.set_iris(0.0))
    _run(driver.set_iris(1.0))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23AXI555&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23AXIFFF&res=1"


def test_set_gain_db_uses_aw_cam_endpoint_and_correct_data() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.set_gain_db(0))
    _run(driver.set_gain_db(-6))
    _run(driver.set_gain_db(12))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:08&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:02&res=1"
    assert seen[2] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:14&res=1"


def test_step_gain_reads_current_value_then_sets_new_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "cmd=QGU" in url:
            return httpx.Response(200, text="OGU:0C")  # 0x0C - 0x08 = +4 dB
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_db = _run(driver.step_gain(3))

    assert new_db == 7  # +4dB + 3 -> +7dB
    assert seen[-1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:0F&res=1"  # 0x08+7=0x0F


def test_step_gain_raises_when_agc_active() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OGU:80")  # 80h = AGC aktiv

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.step_gain(1))


def test_query_pedestal_parses_offset_from_center() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QSJ:0F" in str(request.url)
        return httpx.Response(200, text="OSJ:0F:764")  # 0x764 - 0x800 = -156

    driver = _build_driver(handler)
    value = _run(driver._query_pedestal())

    assert value == 0x764 - 0x800


def test_step_pedestal_reads_current_value_then_sets_new_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "cmd=QSJ:0F" in url:
            return httpx.Response(200, text="OSJ:0F:800")  # 0
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_value = _run(driver.step_pedestal(20))

    assert new_value == 20
    assert seen[-1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSJ:0F:814&res=1"  # 0x800+20=0x814


def test_step_pedestal_clamps_to_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cmd=QSJ:0F" in str(request.url):
            return httpx.Response(200, text="OSJ:0F:8C8")  # +200, bereits am Maximum
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_value = _run(driver.step_pedestal(50))

    assert new_value == 200


def test_step_pedestal_raises_when_unreadable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="garbage")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.step_pedestal(1))


def test_camera_error_response_raises_with_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ER3:out of range")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError) as excinfo:
        _run(driver.set_gain_db(99))
    assert excinfo.value.response == "ER3:out of range"


def test_ptz_endpoint_error_prefix_is_recognized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="eR2")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.set_iris(0.5))


def test_query_model_extracts_model_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QID" in str(request.url)
        return httpx.Response(200, text="OID:AW-UE160")

    driver = _build_driver(handler)
    model = _run(driver._query_model())
    assert model == "AW-UE160"


def test_query_iris_parses_position_and_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="gi7ff1")

    driver = _build_driver(handler)
    iris, auto_iris = _run(driver._query_iris())

    assert iris == pytest.approx(_data_to_iris(0x7FF))
    assert auto_iris is True


def test_get_state_aggregates_queries() -> None:
    responses = {
        "cmd=%23GI": "gi5551",
        "cmd=QIF": "OIF:0E",
        "cmd=QGU": "OGU:08",
        "cmd=QSJ:0F": "OSJ:0F:800",
        "cmd=QFT": "OFT:2",
        "cmd=QER": "rER1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, text in responses.items():
            if key in url:
                return httpx.Response(200, text=text)
        raise AssertionError(f"unexpected request: {url}")

    driver = _build_driver(handler)
    state = _run(driver.get_state())

    assert state.iris == pytest.approx(0.0)
    assert state.auto_iris is True
    assert state.iris_f_number == "0E"
    assert state.gain_db == 0
    assert state.pedestal == 0
    assert state.nd_index == 2
    assert state.error == "rER1"


def test_trigger_button_feature_toggle_sends_on_and_off() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("drs", enabled=True))
    _run(driver.trigger_button_feature("drs", enabled=False))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:0D:1&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:0D:0&res=1"


def test_trigger_button_feature_trigger_ignores_enabled() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("awb_black"))

    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=OAS&res=1"]


def test_trigger_button_feature_auto_iris_delegates_to_set_auto_iris() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("auto_iris", enabled=True))

    # Muss ueber set_auto_iris() laufen (ORS:1), nicht ueber eine zweite,
    # eigene Kommando-Implementierung fuer denselben Befehl.
    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=ORS:1&res=1"]


def test_trigger_button_feature_aww_white_delegates_to_trigger_awb() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("aww_white"))

    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=OWS&res=1"]


def test_trigger_button_feature_toggle_without_enabled_raises() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    with pytest.raises(ValueError):
        _run(driver.trigger_button_feature("drs"))


def test_trigger_button_feature_unknown_key_raises() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    with pytest.raises(ValueError):
        _run(driver.trigger_button_feature("does_not_exist", enabled=True))


def test_cycle_button_feature_sends_all_commands_of_target_step() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.cycle_button_feature("knee", 2))  # "Auto": OSL:45:1 + OSA:2D:2

    assert seen == [
        "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSL:45:1&res=1",
        "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:2D:2&res=1",
    ]


def test_cycle_button_feature_out_of_range_raises() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    with pytest.raises(ValueError):
        _run(driver.cycle_button_feature("knee", 99))


# --- Update-Notification-Kanal / Lens-Info (§7.3) ---------------------------
# Die Hex-Fixtures sind raw TCP-Captures gegen eine reale AW-UE160 nach
# #LPC1-Registrierung (siehe CLAUDE.md Offene Punkte) -- kein konstruiertes
# Beispiel, sondern das tatsaechlich beobachtete Frame-Layout.
_REAL_LPC1_ACK_FRAME = bytes.fromhex(
    "c0a8000a0001170101011025000100800000000000010010010000000d0a"
    "6c5043310d0a00020018b8208e1725ba0001170101011025000000000000"
)
_REAL_LPI_FRAME = bytes.fromhex(
    "c0a8000a0002170101011025000100800000000000010018010000000d0a"
    "6c50493535353842444439420d0a00020018b8208e1725ba00011701010110"
    "25000000000000"
)


def test_parse_notification_payload_lpc1_ack() -> None:
    assert _parse_notification_payload(_REAL_LPC1_ACK_FRAME) == "lPC1"


def test_parse_notification_payload_lpi() -> None:
    assert _parse_notification_payload(_REAL_LPI_FRAME) == "lPI5558BDD9B"


def test_parse_notification_payload_too_short_returns_none() -> None:
    assert _parse_notification_payload(b"\x00" * 10) is None


def test_parse_lens_info_iris_extracts_last_group() -> None:
    # lPI[ZZZ][FFF][III] -- Iris sind die letzten 3 Hex-Digits (§7.3.2)
    assert _parse_lens_info_iris("lPI5558BDD9B") == pytest.approx(_data_to_iris(0xD9B))


def test_parse_lens_info_iris_wrong_prefix_returns_none() -> None:
    assert _parse_lens_info_iris("OIF:2B") is None


class _FakeWriter:
    def close(self) -> None:
        pass


class _FakeReader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, n: int) -> bytes:
        return self._data


def test_handle_notification_fires_iris_changed_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_REAL_LPI_FRAME), _FakeWriter()))

    assert events == [{"type": "iris_changed", "value": pytest.approx(_data_to_iris(0xD9B))}]


def test_handle_notification_non_lpi_payload_fires_no_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_REAL_LPC1_ACK_FRAME), _FakeWriter()))

    assert events == []


def test_start_lens_feedback_registers_and_enables_lpc1() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)

    async def scenario() -> None:
        await driver.start_lens_feedback()
        try:
            assert "cgi-bin/event?connect=start&my_port=" in seen[0]
            assert "uid=0" in seen[0]
            assert seen[1] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23LPC1&res=1"
        finally:
            await driver.stop_lens_feedback()

    _run(scenario())


def test_stop_lens_feedback_sends_lpc0_and_deregisters() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)

    async def scenario() -> None:
        await driver.start_lens_feedback()
        seen.clear()
        await driver.stop_lens_feedback()

    _run(scenario())

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23LPC0&res=1"
    assert "cgi-bin/event?connect=stop&my_port=" in seen[1]
