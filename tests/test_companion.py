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


def test_press_button_retries_once_on_stale_connection_and_succeeds() -> None:
    # Nutzerbeobachtung 2026-07-20: nach laengerer Inaktivitaet wirkt nur der
    # zweite Klick, weil die gepoolte Companion-Verbindung serverseitig schon
    # zu ist -- ein automatischer Retry soll das transparent auffangen.
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("server closed stale connection", request=request)
        return httpx.Response(200, text="")

    client = _mock_client(handler)

    _run(press_button(client, "192.168.0.50", 8000, 1, 0, 2))

    assert calls["count"] == 2


def test_press_button_raises_after_two_failed_attempts() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = _mock_client(handler)

    with pytest.raises(CompanionError):
        _run(press_button(client, "192.168.0.50", 8000, 1, 0, 2))

    assert calls["count"] == 2  # erster Versuch + genau ein Retry, kein Retry-Loop
