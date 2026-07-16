# PTZ Control

MIDI-Blenden-/Shading-Controller für PTZ-Kameras (Behringer X-Touch Extender).
Primäre Quelle der Wahrheit für Verhalten und Scope ist
[ptz-shading-tool-spec.md](ptz-shading-tool-spec.md); dieses README beschreibt
nur, wie der Code aktuell strukturiert ist.

**Aktueller Stand:** Iris-Steuerung läuft Ende-zu-Ende über das Web-UI
(Setup verbindet Kamera, Übersicht steuert Iris live). Kameras werden nicht
mehr extern in `config.yaml` eingetragen, sondern über den "Connect
Camera"-Button pro Kanal auf der Setup-Seite (Name/IP/Port) registriert —
die App persistiert das selbst. Kamera-Feature-Buttons (Spec §9a, z. B.
DRS/Knee/Auto-Iris für AW-UE160) sind Button 2/3 pro Kanal zuweisbar
(ebenfalls Setup-Seite) und über die Übersicht auslösbar. Der
SELECT-Button pro Kanal löst optional einen Bitfocus-Companion-Button fern
aus (v3 HTTP-API, `core/companion.py`) — bewusste Erweiterung über v1
hinaus, siehe Spec §9. Der X-Touch-Extender-Pfad (`midi/`) ist als Scaffold
vorhanden, aber noch nicht verdrahtet — MIDI ist als zweite Event-Quelle
vorgesehen, siehe Architektur unten.

## Stack

- Python 3.11+
- mido + python-rtmidi (MIDI-Layer, noch nicht verdrahtet)
- httpx (Kamera-HTTP)
- FastAPI + Jinja2 + WebSocket (Web-UI)
- pydantic v2 + YAML (Config)

## Quick start

1. Virtualenv anlegen und aktivieren.
2. Dependencies installieren: `pip install -r requirements.txt`
   (für `tools/panasonic_emulator.py`s Control-UI zusätzlich `python-multipart`,
   siehe `pyproject.toml`-Extra `dev`)
3. Starten: `python main.py` → Web-UI unter `http://127.0.0.1:8600/`
   (`config.yaml` startet leer, `cameras: []` ist gültig).
4. Kameras über die Setup-Seite registrieren (Name/IP/Port pro Kanal,
   "Connect Camera") — nicht mehr von Hand in `config.yaml` eintragen.

Ohne reale Kamera zum Testen: `python tools/panasonic_emulator.py` startet
einen lokalen AW-UE160-CGI-Emulator (Control-UI unter `--ui-port`, Default
8080).

## Architektur

Schichtenaufbau, damit ein späterer MIDI/X-Touch-Anschluss keine bestehende
Logik anfassen muss (Spec §3):

```
Interface        web/app.py            FastAPI-Routen, WebSocket, Templates
                  midi/                 Scaffold für X-Touch (noch nicht verdrahtet)

Anwendung         core/application.py   AppState, Use-Cases (connect_camera,
                                         apply_iris, channel_snapshot, ...)

Domain/Core       core/config.py        Typisiertes Config-Schema (pydantic v2)
                  core/bus.py           EventBus (Pub/Sub-Rückgrat)
                  core/mapping.py       Kanal->Kamera-Zuordnung
                  core/ratelimit.py     Token-Bucket + Delta-Filter
                  core/state.py         StateStore (Kamera-/Kanal-Zustand)

Treiber           drivers/base.py       CameraDriver-Interface (ABC)
                  drivers/panasonic_aw.py  AW-UE160-Referenzimplementierung
```

- **Config**: `config.yaml` wird strikt über `core/config.py`s pydantic-Modelle
  validiert (`load_config()` wirft `ConfigError` mit Pfad ins YAML bei
  Fehlern, Spec §4).
- **EventBus**: Domain-Events (`iris_changed`, `connection_changed`, `error`)
  laufen über `core/bus.py`. Web-UI ist ein Consumer wie jeder andere — der
  WebSocket-Broadcast abonniert dieselben Topics, die später ein
  MIDI-Consumer (Motorfader-/LED-Feedback) ebenfalls abonnieren würde.
- **Anwendungsschicht**: `core/application.py` kennt FastAPI nur an der
  einen Stelle, an der WebSocket-Clients benachrichtigt werden — Routing und
  Templates gehören nicht hierher. Dadurch ist die eigentliche
  Steuerungslogik (Mapping → Rate-Limiter → Driver → StateStore → EventBus)
  unabhängig vom HTTP/WebSocket-Interface testbar (siehe
  `tests/test_application.py`).
- **Driver-Interface**: `drivers/base.py` definiert die Kamera-Schnittstelle
  (Spec §6); `drivers/panasonic_aw.py` ist die einzige v1-Implementierung
  (Spec §7). Weitere Kameratypen kämen als zusätzliche Module hinzu.
- **Kamera-Feature-Buttons** (Spec §9a): Katalog (`BUTTON_FEATURES`/
  `BUTTON_FEATURE_LABELS`) lebt treiberspezifisch auf `PanasonicAWDriver`,
  nicht in der `CameraDriver`-ABC — ein Treiber ohne Katalog bietet einfach
  keine Optionen an. Zustand wird nur lokal getrackt (kein Kamera-Query für
  diese Kommandos verfügbar, siehe Kommentar dort).
- **Kamera-Registrierung** (`core/application.py::register_camera`): einzige
  Stelle, die `AppState.cameras/drivers/rate_limiters/mapping` zur Laufzeit
  erweitert (alle anderen Use-Cases arbeiten nur mit dem beim Start
  gebauten Zustand). Kamera-ID ist deterministisch `cam{Kanalnummer}`.
- **Bitfocus Companion** (`core/companion.py`): eigenständige Funktion, kein
  `drivers/`-Treiber (Companion ist keine Kamera). Eine globale Instanz
  (Host/Port) für alle Kanäle, pro Kanal optional ein Page/Row/Column-Ziel.
  Kein Dauerzustand -- SELECT ist eine einmalige Aktion, Fehler werden nur
  als HTTP-Antwort zurückgegeben, nicht im Snapshot gespeichert.

## Tests

```
python -m pytest tests/
```

`tests/test_web_app.py` prüft die Interface-Schicht (HTTP/WebSocket) über
`TestClient`; `tests/test_application.py` prüft dieselbe Steuerungslogik
direkt gegen `core/application.py`, ohne FastAPI. Beide nutzen
`tests/fakes.py`s `FakeCameraDriver` statt echtem HTTP. `tests/test_panasonic.py`
prüft das Wire-Format des AW-UE160-Treibers gegen `httpx.MockTransport`.

## Dev-Werkzeug

`tools/panasonic_emulator.py` bildet die AW-UE160-CGI-Strecke lokal nach
(kein Produktionscode) — für manuelles Testen ohne reale Kamera.
