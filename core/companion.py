"""core/companion.py -- Bitfocus Companion remote trigger (v3 location HTTP API).

    POST http://<host>:<port>/api/location/<page>/<row>/<column>/press

Fires whatever action is configured behind that button in Companion; this
module only knows the address, not the underlying action.
"""

from __future__ import annotations

import httpx

_REQUEST_TIMEOUT = 1.5


class CompanionError(Exception):
    """Companion button trigger failed (connection error or non-2xx response)."""


def build_client() -> httpx.AsyncClient:
    """Reused client with a long keepalive so repeated SELECT presses don't
    each pay for a fresh TCP/TLS handshake."""
    limits = httpx.Limits(max_keepalive_connections=1, keepalive_expiry=3600)
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, limits=limits)


async def is_reachable(client: httpx.AsyncClient, host: str, port: int) -> bool:
    """Checks only that some HTTP server answers at host:port -- does not
    confirm it's actually Companion."""
    try:
        await client.get(f"http://{host}:{port}/")
    except httpx.HTTPError:
        return False
    return True


async def press_button(
    client: httpx.AsyncClient, host: str, port: int, page: int, row: int, column: int
) -> None:
    url = f"http://{host}:{port}/api/location/{page}/{row}/{column}/press"
    try:
        response = await client.post(url)
    except httpx.HTTPError:
        # One retry: a pooled keep-alive connection that Companion closed
        # server-side only surfaces as an error on the next write attempt.
        try:
            response = await client.post(url)
        except httpx.HTTPError as exc:
            raise CompanionError(f"Companion unreachable ({url}): {exc}") from exc
    if response.status_code >= 400:
        raise CompanionError(f"Companion error ({url}): HTTP {response.status_code}")
