from __future__ import annotations

import asyncio

import httpx
import pytest

from drivers.base import CameraCommandError
from drivers.panasonic_aw import PanasonicAWDriver, _data_to_iris, _iris_to_data


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
    assert state.nd_index == 2
    assert state.error == "rER1"
