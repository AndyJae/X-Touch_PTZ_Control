from __future__ import annotations

import asyncio

import httpx
import pytest

from core.companion import CompanionError, press_button


def _run(coro):
    return asyncio.run(coro)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_press_button_sends_correct_url_and_method() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="")

    client = _mock_client(handler)

    _run(press_button(client, "192.168.0.50", 8000, 1, 0, 2))

    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://192.168.0.50:8000/api/location/1/0/2/press"


def test_press_button_raises_on_non_2xx() -> None:
    client = _mock_client(lambda request: httpx.Response(500, text="internal error"))

    with pytest.raises(CompanionError):
        _run(press_button(client, "192.168.0.50", 8000, 1, 0, 2))


def test_press_button_raises_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _mock_client(handler)

    with pytest.raises(CompanionError):
        _run(press_button(client, "192.168.0.50", 8000, 1, 0, 2))
