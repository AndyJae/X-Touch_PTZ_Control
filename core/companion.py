"""core/companion.py -- Bitfocus-Companion-Fernauslösung (v3 HTTP-API).

Bewusste Erweiterung über den ursprünglichen v1-Scope hinaus (siehe Spec §9,
Abschnitt zum SELECT-Button) -- Companion ist keine Kamera, daher kein
`drivers/`-Treiber-Interface, sondern eine schlanke, eigenständige Funktion.

Endpunkt verifiziert gegen die offizielle Doku
(companion.free/user-guide/v5.0/remote-control/http-remote-control, aktuellste
verfügbare Version -- eine archivierte v3-spezifische Seite war nicht
erreichbar, aber das Location-Schema (Page/Row/Column) wurde laut Doku genau
mit v3 eingeführt und löste das ältere, dort als "legacy/deprecated"
markierte Bank-Nummern-Schema ab, gilt also unverändert ab v3):

    POST http://<host>:<port>/api/location/<page>/<row>/<column>/press

Löst die in Companion hinter diesem Button konfigurierte Aktion aus (z. B.
eine Kreuzschienen-Schaltung) -- PTZ_Control kennt den eigentlichen Befehl
nicht, nur die Adresse.
"""

from __future__ import annotations

import httpx

_REQUEST_TIMEOUT = 1.5  # gleiche Größenordnung wie drivers/panasonic_aw.py, kein Retry (siehe Modul-Docstring: schlanke Funktion)


class CompanionError(Exception):
    """Companion-Button-Trigger fehlgeschlagen (Verbindung oder Non-2xx-Antwort)."""


def build_client() -> httpx.AsyncClient:
    """Ein wiederverwendeter Client statt einem neuen pro Trigger -- ein
    frischer `httpx.AsyncClient` pro Aufruf baut jedes Mal eine neue
    Verbindung auf und hat den SELECT-Trigger spuerbar verzoegert (gemessen:
    ~400ms zusaetzlich pro Klick durch den Verbindungsaufbau).

    `keepalive_expiry` explizit hoch gesetzt: httpx' Default (5s) schliesst
    die gepoolte Verbindung nach 5s Inaktivitaet zwischen zwei Triggern,
    danach baut der naechste Trigger wieder neu auf -- exakt die "manchmal
    langsam"-Verzoegerung. Mit langem Expiry bleibt die eine Verbindung
    dauerhaft offen."""
    limits = httpx.Limits(max_keepalive_connections=1, keepalive_expiry=3600)
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, limits=limits)


async def is_reachable(client: httpx.AsyncClient, host: str, port: int) -> bool:
    """Reine Erreichbarkeitspruefung vor dem Speichern der Companion-Config
    (Setup-Seite): prueft nur, ob unter Host:Port ueberhaupt ein HTTP-Server
    antwortet -- bestaetigt NICHT, dass es sich um Companion handelt, da kein
    Companion-spezifischer Status-/Health-Endpunkt in der Spec verifiziert
    ist (siehe Modul-Docstring)."""
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
        # Nutzerbeobachtung 2026-07-20: nach laengerer Inaktivitaet wirkt nur
        # der zweite Klick -- die gepoolte Keep-Alive-Verbindung (siehe
        # build_client()) ist dann serverseitig von Companion bereits
        # geschlossen worden, der Client bemerkt das erst beim naechsten
        # Schreibversuch. Ein einmaliger Retry baut eine frische Verbindung
        # auf (httpx/httpcore entfernt die tote Verbindung automatisch aus
        # dem Pool) und macht den ersten Klick wieder zuverlaessig, ohne dass
        # ein Nutzer das merkt.
        try:
            response = await client.post(url)
        except httpx.HTTPError as exc:
            raise CompanionError(f"Companion nicht erreichbar ({url}): {exc}") from exc
    if response.status_code >= 400:
        raise CompanionError(f"Companion-Fehler ({url}): HTTP {response.status_code}")
