# PTZ Control

MIDI-Blenden-/Shading-Controller für PTZ-Kameras (Behringer X-Touch Extender).
Primäre Quelle der Wahrheit für Verhalten und Scope ist
[ptz-shading-tool-spec.md](ptz-shading-tool-spec.md); dieses README beschreibt
nur, wie der Code aktuell strukturiert ist.

**Aktueller Stand:** Iris-Steuerung läuft Ende-zu-Ende über das Web-UI
(Setup verbindet Kamera, Control-Seite steuert Iris live). Kameras werden
nicht mehr extern in `config.yaml` eingetragen, sondern über den "Connect
Camera"-Button pro Kanal auf der Setup-Seite (Name/IP/Port) registriert —
die App persistiert das selbst; erneutes Klicken bei bereits verbundener
Kamera trennt sie wieder (Registrierung bleibt erhalten), Umbenennen läuft
über ein eigenes, vom Verbindungsstatus unabhängiges Feld. Kamera-Feature-
Buttons (Spec §9a, z. B. DRS/Knee/Auto-Iris für AW-UE160) sind Button 2/3
pro Kanal zuweisbar (ebenfalls Setup-Seite) und über die Control-Seite
auslösbar. Der SELECT-Button pro Kanal löst optional einen
Bitfocus-Companion-Button fern aus (v3 HTTP-API, `core/companion.py`) —
bewusste Erweiterung über v1 hinaus, siehe Spec §9. Kopfzeile trägt auf
allen Seiten ein Logo (`web/static/images/`).

Der X-Touch-Extender ist für den Fader/Iris-Pfad und für Rec+Encoder
verdrahtet (`midi/fader.py`): physisches Fader-Ziehen steuert die Iris live
(Rx, Note-/CC-Belegung gegen das reale Gerät verifiziert, siehe CLAUDE.md),
und der Motorfader folgt Iris-Änderungen aus **jeder** Quelle zurück (Tx) —
inklusive Änderungen, die nicht von PTZ_Control selbst ausgelöst wurden (z. B.
Kamera-eigenes Web-UI), über das Lens-Info-Feedback (`#LPC1`, Spec §7.3) in
`drivers/panasonic_aw.py`.

Rec (Button 1) schaltet pro Kanal fest durch drei Encoder-Funktionen:
**Gain → Pedestal → Camera Status** (nicht mehr über `config.yaml`
konfigurierbar, siehe `core/application.py._ENCODER_FUNCTIONS`). Drehen
sendet bei Gain/Pedestal **sofort live** einen Kamerabefehl (über eine eigene
Rate-Limiter-Instanz je Kamera, `apply_encoder_turn` in `core/application.py`,
geclampt auf den Bereich des verbundenen Kameramodells, siehe
`drivers/panasonic_models/*.py` und Spec §7.2 — z. B. AW-UE160 -6…+12dB/
-200…+200, AW-HE50 0…18dB/-10…+10) — Encoder-Push sendet seitdem nichts mehr an die Kamera,
sondern markiert den Wert nur noch visuell als "gespeichert" (rote Anzeige in
der Web-UI, bis zum nächsten Dreh-Tick).

Es gibt pro Kanal genau **eine** Anzeige (Web-UI und physisches Scribble-
Strip zeigen exakt denselben Text, `channel_line1_text()`/
`channel_display_text()` in `core/application.py`): bei `camera_status`
Zeile 1 Kameraname + Zeile 2 Iris-% (Platzhalter bis zur Klärung der
F-Nummer-Tabelle, siehe Spec §14 Punkt 10); bei Gain/Pedestal zeigt Zeile 1
stattdessen den Funktionsnamen (GAIN/PEDESTAL) und Zeile 2 den unitlosen
Rohwert (z. B. Pedestal `-45`, kein Prozentwert, kein zusätzliches
Funktions-Präfix — das übernimmt jetzt Zeile 1). Nicht verbundene Kanäle
zeigen `NC`/`----`. Solo/Mute/Select-Buttons sind Rx-seitig
verifiziert, aber noch nicht an Kamera-Aktionen/Companion-SELECT angebunden
(siehe CLAUDE.md, Offene Punkte).

## Stack

- Python 3.11+
- mido + python-rtmidi (MIDI-Layer — Fader/Touch/Scribble-Strips sowie
  Rec+Encoder (Gain/Pedestal) verdrahtet, siehe `midi/fader.py`; Solo/Mute/
  Select noch nicht)
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
5. Für den X-Touch Extender: `midi.input_port`/`midi.output_port` in
   `config.yaml` auf einen Substring des tatsächlichen Portnamens setzen
   (z. B. `X-Touch-Ext`, siehe `mido.get_input_names()`/`get_output_names()`)
   — ohne gesetzten Port bleibt MIDI unverbunden (Spec §5.5), kein Fehler.

Ohne reale Kamera zum Testen: `python tools/panasonic_emulator.py` startet
einen lokalen AW-UE160-CGI-Emulator (Control-UI unter `--ui-port`, Default
8080). Ohne echten X-Touch Extender zum Prüfen der rohen MIDI-Belegung:
`python tools/midi_monitor.py` loggt alle eingehenden Rx-Nachrichten roh
(Dev-Werkzeug, siehe Spec §5.2 "Debug-Modus").

## Architektur

Schichtenaufbau, damit ein späterer MIDI/X-Touch-Anschluss keine bestehende
Logik anfassen muss (Spec §3):

```
Interface        web/app.py            FastAPI-Routen, WebSocket, Templates
                  midi/fader.py         X-Touch-Extender-Fader (Rx: Pitchbend/Touch->Iris,
                                         Tx: Iris->Motorfader + Scribble Strips)
                  midi/mackie.py        Mackie-Control-Protokoll-Konstanten/-Helfer
                  midi/surface.py       Scaffold, nicht an AppState angebunden (siehe Text)

Anwendung         core/application.py   AppState, Use-Cases (connect_camera,
                                         apply_iris, channel_snapshot, ...)

Domain/Core       core/config.py        Typisiertes Config-Schema (pydantic v2)
                  core/bus.py           EventBus (Pub/Sub-Rückgrat)
                  core/mapping.py       Kanal->Kamera-Zuordnung
                  core/ratelimit.py     Token-Bucket + Delta-Filter
                  core/state.py         StateStore (Kamera-/Kanal-Zustand)
                  core/companion.py     Bitfocus-Companion-HTTP-Trigger

Treiber           drivers/base.py       CameraDriver-Interface (ABC)
                  drivers/panasonic_aw.py  AW-UE160-Referenzimplementierung
                  drivers/panasonic_models/  Button-Feature-Katalog je Modell
                                         (17 Panasonic-Modelle) + Registry
```

- **Config**: `config.yaml` wird strikt über `core/config.py`s pydantic-Modelle
  validiert (`load_config()` wirft `ConfigError` mit Pfad ins YAML bei
  Fehlern, Spec §4).
- **EventBus**: Domain-Events (`iris_changed`, `connection_changed`, `error`,
  `feature_changed`, `config_changed`) laufen über `core/bus.py`. Web-UI und
  MIDI sind gleichwertige Consumer desselben Bus — der WebSocket-Broadcast
  und `midi/fader.py`s Motorfader-/Scribble-Strip-Feedback abonnieren
  dieselben Topics unabhängig voneinander.
- **Anwendungsschicht**: `core/application.py` kennt FastAPI nur an der
  einen Stelle, an der WebSocket-Clients benachrichtigt werden — Routing und
  Templates gehören nicht hierher. Dadurch ist die eigentliche
  Steuerungslogik (Mapping → Rate-Limiter → Driver → StateStore → EventBus)
  unabhängig vom HTTP/WebSocket-Interface testbar (siehe
  `tests/test_application.py`).
- **Driver-Interface**: `drivers/base.py` definiert die Kamera-Schnittstelle
  (Spec §6); `drivers/panasonic_aw.py` ist die einzige v1-Implementierung
  (Spec §7). Weitere Kameratypen kämen als zusätzliche Module hinzu.
- **MIDI-Fader** (`midi/fader.py`, Spec §5): `XTouchFader` pollt den
  Eingangsport (kein rtmidi-Callback-Thread, siehe Moduldocstring) und ruft
  bei Fader-/Touch-Nachrichten dieselbe `apply_iris()`-Funktion wie das
  Web-UI. Umgekehrt sendet sie bei `iris_changed` die Motorfader-Position
  (außer während aktivem Touch, Spec §5.4) und aktualisiert die
  Scribble-Strip-Displays (SysEx, Spec §5.3, Device-ID `0x15` verifiziert).
  Port kommt aus `config.yaml midi.input_port`/`output_port`
  (Substring-Match, Spec §5.5); ohne gesetzten Port bleibt MIDI unverbunden,
  kein Fehler. `midi/surface.py` ist ein früherer Scaffold-Versuch, der
  nirgends mehr eingebunden ist.
- **Lens-Info-Feedback** (`drivers/panasonic_aw.py::start_lens_feedback`,
  Spec §7.3): registriert den Update-Notification-TCP-Kanal der Kamera und
  aktiviert `#LPC1` (Zoom/Fokus/Iris alle 300ms) — die einzige Quelle, über
  die Iris-Änderungen erkannt werden, die nicht von PTZ_Control selbst
  ausgelöst wurden (z. B. Kamera-eigenes Web-UI), da `#AXI` laut Spec kein
  Update-Notification-Flag hat. Frame-Layout und Device-Verhalten live gegen
  eine reale AW-UE160 verifiziert. Kein Teil der `CameraDriver`-ABC (wie
  `BUTTON_FEATURES`) — ein Treiber ohne Unterstützung liefert einfach keine
  externen Iris-Updates.
- **Kamera-Feature-Buttons** (Spec §9a): Katalog (`BUTTON_FEATURES`/
  `BUTTON_FEATURE_LABELS`) lebt nicht mehr fest auf `PanasonicAWDriver`,
  sondern in `drivers/panasonic_models/` — eine Datei pro Kameramodell
  (17 Panasonic-Modelle, portiert aus `C:\smart_reset_work`s
  `camera_plugins/panasonic/*.py`), aufgelöst über eine kleine Registry
  (`drivers/panasonic_models/registry.py`) anhand des per `QID` erkannten
  Modells (`PanasonicAWDriver.connect()` → `_apply_model_catalog()`). Nicht
  Teil der `CameraDriver`-ABC — ein nicht erkanntes Modell bietet einfach
  keine Optionen an (leere Kataloge, kein erfundener Fallback). Zustand wird
  nur lokal getrackt (kein Kamera-Query für diese Kommandos verfügbar, siehe
  Kommentar dort). Gain-/Pedestal-Bereich und -Kommando werden über dieselbe
  Registry mitaufgelöst (`GAIN_MIN_DB`/`GAIN_MAX_DB`/`GAIN_STEP_DB`,
  `PEDESTAL_COMMAND` u. ä. je Modell-Datei, siehe Spec §7.2) — nur Iris
  bleibt weiterhin modellunabhängig nur für AW-UE160 verifiziert (siehe
  `drivers/panasonic_aw.py`-Klassendocstring).
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
prüft das Wire-Format des AW-UE160-Treibers (inkl. Notification-Frame-Parsing
gegen echte, live mitgeschnittene Bytes) und das Lens-Info-Feedback,
`tests/test_companion.py` das von `core/companion.py`, beide gegen
`httpx.MockTransport`. `midi/fader.py` hat keine dedizierten Unit-Tests (nur
live gegen das reale Gerät verifiziert, siehe CLAUDE.md) — reine
MIDI-I/O-Verdrahtung ohne eigene Entscheidungslogik jenseits dessen, was
`core/ratelimit.py`/`core/application.py` bereits abdecken.

## Dev-Werkzeug

- `tools/panasonic_emulator.py` bildet die AW-UE160-CGI-Strecke lokal nach
  (kein Produktionscode) — für manuelles Testen ohne reale Kamera. Kennt
  aktuell keine Update-Notifications/`#LPC1` (Emulator liefert dafür `ER1`/
  `404`, PTZ_Control loggt das nur als Warnung, siehe `connect_camera`).
- `tools/midi_monitor.py` loggt alle rohen Rx-MIDI-Nachrichten eines
  Eingangsports mit einer Interpretation gegen die in Spec §5.2 angenommene
  Belegung — für manuelles Verifizieren gegen einen realen X-Touch Extender.
