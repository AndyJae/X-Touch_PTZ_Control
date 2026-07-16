from __future__ import annotations

import asyncio

import httpx
import pytest

from core.companion import CompanionError, press_button


def _run(coro):
    return asyncio.run(coro)


def _patch_client(monkeypatch, handler) -> None:
    """Companion laeuft nicht auf einer festen, injizierbaren Basis-URL wie
    der Kamera-Treiber (press_button baut die volle URL selbst) -- daher
    hier die httpx.AsyncClient-Klasse selbst durch eine MockTransport-Variante
    ersetzen, statt eine Instanz vorzukonfigurieren."""

    class _MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("core.companion.httpx.AsyncClient", _MockClient)


def test_press_button_sends_correct_url_and_method(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="")

    _patch_client(monkeypatch, handler)

    _run(press_button("192.168.0.50", 8000, 1, 0, 2))

    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://192.168.0.50:8000/api/location/1/0/2/press"


def test_press_button_raises_on_non_2xx(monkeypatch) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(500, text="internal error"))

    with pytest.raises(CompanionError):
        _run(press_button("192.168.0.50", 8000, 1, 0, 2))


def test_press_button_raises_on_connection_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_client(monkeypatch, handler)

    with pytest.raises(CompanionError):
        _run(press_button("192.168.0.50", 8000, 1, 0, 2))
