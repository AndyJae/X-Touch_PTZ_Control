# Spezifikation: PTZ Shading Tool (Arbeitstitel)

MIDI-Fader-Controller (Behringer X-Touch Extender) als Blenden-/Shading-Steuerung
für PTZ-Kameras. Erster Kamera-Treiber: Panasonic AW-Serie (referenziert: AW-UE160,
Interface Specification Dec. 2023).

---

## 1. Ziel und Scope v1

**Kernfunktion:**
- 8 Motorfader steuern die Blende (Iris) von bis zu 8 Kameras absolut.
- Buttons (Rec/Solo/Mute pro Kanal) frei belegbar: Gain-Step, ND-Filter, Shutter,
  AWB-Trigger, Bars, Preset-Recall.
- Encoder pro Kanal belegbar: Gain, Master Pedestal oder R/B-Gain (umschaltbar per Encoder-Push).
- Scribble Strips zeigen Kameraname (Zeile 1) und F-Nummer (Zeile 2).
- Motorfader-Feedback: Iris-Änderungen von außen (Auto-Iris, Web-UI der Kamera,
  anderer Controller) fahren den Fader nach.
- Bank-Switching für mehr als 8 Kameras (v1: optional, Struktur vorsehen).

**Transport v1 (Variante A):**
- MIDI ausschließlich über System-MIDI-Ports (`mido` + `python-rtmidi`).
- USB und Netzwerk (rtpMIDI-Treiber) sind damit transparent identisch —
  der User wählt in der UI nur den MIDI-Port.
- Natives RTP-MIDI ist NICHT Teil von v1 (Roadmap, siehe §12).

**Nicht in v1:**
- Pan/Tilt/Zoom-Steuerung (bewusst: Shading-Tool, kein PTZ-Controller).
- VISCA-/Sony-/BirdDog-Treiber (Interface aber dafür ausgelegt).
- Natives RTP-MIDI, mDNS-Discovery.

---

## 2. Technologie-Stack

| Komponente | Wahl | Begründung |
|---|---|---|
| Sprache | Python 3.11+ | Konsistenz mit smart-reset |
| MIDI | `mido` + `python-rtmidi` | Class-compliant USB & rtpMIDI-Ports identisch nutzbar |
| HTTP zu Kameras | `httpx` (async) | Async, Timeouts, Connection-Handling |
| Web-UI | FastAPI + HTMX + WebSocket | Konsistenz mit smart-reset-Stack |
| Config | YAML (`pydantic` v2 Models zur Validierung) | Lesbar, versionierbar |
| Logging | `logging` stdlib, strukturiert | Ein Logfile pro Session |
| Paketierung | Single-Prozess, `uvicorn`-Start | Minimal-Infrastruktur |

Keine Datenbank. Zustand lebt im Prozess; Config auf Disk.

---

## 3. Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                        Core / EventBus                       │
│  Mapping-Engine · State-Store · Rate-Limiter (pro Kamera)    │
└───────┬──────────────────────┬───────────────────┬──────────┘
        │                      │                   │
┌───────┴────────┐   ┌─────────┴─────────┐   ┌─────┴──────────┐
│  MIDI-Layer    │   │  Camera-Drivers   │   │  Web-UI        │
│  (MC-Protokoll │   │  (abstrakte Basis │   │  (FastAPI/HTMX │
│   Encoder/     │   │   + PanasonicAW)  │   │   + WebSocket) │
│   Decoder)     │   │                   │   │                │
└────────────────┘   └───────────────────┘   └────────────────┘
```

**Datenfluss Fader → Kamera:**
1. MIDI-Layer decodiert Pitchbend (Kanal n) → normalisierter Wert 0.0–1.0
2. Mapping-Engine: Kanal n → Kamera X, Funktion `iris`
3. Rate-Limiter der Kamera X entscheidet: senden / verwerfen / queuen
4. Driver skaliert 0.0–1.0 → Geräte-Range und sendet HTTP

**Datenfluss Kamera → Fader (Feedback):**
1. Driver empfängt Update-Notification oder Lens-Info
2. State-Store aktualisiert, EventBus publiziert `camera.X.iris_changed`
3. MIDI-Layer sendet Pitchbend an Fader n (nur wenn Fader nicht gerade berührt wird
   → Touch-Detection, siehe §5.4)
4. Web-UI erhält dasselbe Event via WebSocket

**Verzeichnisstruktur:**
```
ptz-shading/
├── main.py                  # Entry: Config laden, Komponenten starten, uvicorn
├── config.yaml              # User-Config
├── core/
│   ├── bus.py               # Async EventBus (pub/sub, asyncio)
│   ├── state.py             # StateStore: Soll-/Ist-Werte pro Kamera
│   ├── mapping.py           # Mapping-Engine (MIDI-Element ↔ Kamera/Funktion)
│   └── ratelimit.py         # Rate-Limiter pro Kamera
├── midi/
│   ├── transport.py         # Port-Auswahl, Open/Close, Reconnect
│   ├── mackie.py            # MC-Protokoll: Encode/Decode Fader, Buttons,
│   │                        #   Encoder, LEDs, Scribble Strips (SysEx)
│   └── surface.py           # Logische Sicht: "Fader 3", "Button Mute 5" …
├── drivers/
│   ├── base.py              # Abstrakte Driver-Basis (Interface §6)
│   └── panasonic_aw.py      # AW-UE160 u. a. (CGI + Update-Notifications)
├── web/
│   ├── app.py               # FastAPI-App, Routen, WebSocket
│   ├── templates/           # HTMX-Templates
│   └── static/
└── tests/
    ├── test_mackie.py       # MC-Encode/Decode gegen bekannte Byte-Folgen
    ├── test_mapping.py
    ├── test_ratelimit.py
    └── test_panasonic.py    # Gegen Mock-HTTP-Server
```

---

## 4. Config-Schema (YAML)

```yaml
midi:
  transport: system          # v1: nur "system" (USB oder rtpMIDI-Port)
  input_port: ""             # leer = UI-Auswahl beim Start; sonst Portname-Substring
  output_port: ""            # i. d. R. identisch zum Input benennen
  device_profile: xtouch_extender

cameras:
  - id: cam1
    name: "CAM 1"            # max. 7 Zeichen sinnvoll (Scribble Strip)
    driver: panasonic_aw
    host: 192.168.0.10
    port: 80
    feedback:
      update_notifications: true
      notify_listen_port: 31004   # lokaler TCP-Port; pro Kamera eindeutig
      lens_info: true             # #LPC1 → 300ms-Zyklus Zoom/Fokus/Iris
  - id: cam2
    name: "CAM 2"
    driver: panasonic_aw
    host: 192.168.0.11
    port: 80
    feedback:
      update_notifications: true
      notify_listen_port: 31005
      lens_info: true

banks:
  - name: "Bank A"
    channels:                # Index 0–7 = Kanalzug 1–8
      - camera: cam1
      - camera: cam2
      # nicht belegte Kanäle weglassen → Fader unten, Strip leer

channel_defaults:            # gilt für jeden Kanalzug, überschreibbar pro Kanal
  fader: iris                # v1 fix: iris
  encoder:
    functions: [gain, pedestal]   # Encoder-Push schaltet zyklisch durch
  buttons:
    rec:  { action: awb_trigger }
    solo: { action: gain_step, step_db: 3 }     # LED an wenn Gain > 0dB
    mute: { action: nd_cycle }                  # THROUGH → 1/4 → 1/16 → 1/64

global:
  rate_limit_hz: 15          # max. Befehle/s pro Kamera (Fader-Bewegung)
  send_final_on_release: true
  log_level: INFO
  web_port: 8600
```

Validierung strikt über pydantic; bei Fehlern klare Meldung mit Pfad ins YAML.
Doppelte `notify_listen_port`-Werte → Startabbruch mit Fehlermeldung.

---

## 5. MIDI-Layer (Mackie-Control-Protokoll)

### 5.1 Gerät und Modus
- Zielgerät: Behringer X-Touch Extender im **MC-Mode** (Setup: Select Kanal 1
  beim Einschalten halten).
- Das Tool agiert als MC-Host. Kein DAW-Handshake nötig; das Gerät sendet/empfängt
  direkt nach Port-Open.

### 5.2 Message-Mapping (MC-Standard)

| Element | MIDI Rx (vom Pult) | MIDI Tx (zum Pult) |
|---|---|---|
| Fader 1–8 | Pitchbend Ch 1–8, 14 Bit (0–16383) | Pitchbend Ch 1–8 (Motorposition) |
| Fader-Touch 1–8 | Note On/Off, Note 104–111 (0x68–0x6F) | — |
| Encoder 1–8 (drehen) | CC 16–23 (0x10–0x17), relativ: Wert 1–7 = +, 65–71 = − | — |
| Encoder-Push 1–8 | Note 32–39 (0x20–0x27) | — |
| Encoder-LED-Ring 1–8 | — | CC 48–55 (0x30–0x37), Modus+Position im Wert |
| Rec 1–8 | Note 0–7 | Note 0–7 (LED: Velocity 0=aus, 127=an) |
| Solo 1–8 | Note 8–15 | Note 8–15 (LED) |
| Mute 1–8 | Note 16–23 | Note 16–23 (LED) |
| Select 1–8 | Note 24–31 | Note 24–31 (LED) |

Buttons senden Note On Velocity 127 (gedrückt) / Note On Velocity 0 (losgelassen).

**Hinweis für Implementierung:** Die Note-/CC-Belegung ist MC-Standard, aber vor
Release gegen das reale Gerät verifizieren (Behringer-Doku ist stellenweise
fehlerhaft, siehe Nutzerberichte). `midi/mackie.py` kapselt alle Konstanten an
einer Stelle; ein Debug-Modus (`--midi-monitor`) loggt alle Rx-Messages roh.

### 5.3 Scribble Strips (SysEx)
- MC-SysEx-Header: `F0 00 00 66 14 12 <offset> <ascii…> F7`
  - `<offset>`: 0x00–0x37 obere Zeile (7 Zeichen × 8 Strips),
    0x38–0x6F untere Zeile.
- Pro Strip 7 Zeichen. Zeile 1: Kameraname. Zeile 2: F-Nummer (z. B. `F 4.0`)
  oder Status (`AUTO`, `NC` bei Verbindungsverlust, `----` unbelegt).
- Farbsteuerung der Strips (X-Touch-spezifisches SysEx) in v1 weglassen —
  Behringer-Doku dazu unzuverlässig; Roadmap.

### 5.4 Touch-Detection und Motorfader-Regeln
- Solange Touch aktiv (Note 104+n On): eingehende Iris-Feedbacks für diesen
  Kanal NICHT an den Motorfader senden (Kampf Motor vs. Finger vermeiden).
  Feedback nur in State/UI.
- Bei Touch-Release: `send_final_on_release` → letzten Soll-Wert einmal absolut
  senden UND Fader auf bestätigten Ist-Wert der Kamera stellen (nach Response).
- Nach (Re-)Connect des MIDI-Ports: alle Faderpositionen, LEDs und Strips
  komplett neu schreiben (Full-Resync aus dem State-Store).

### 5.5 Port-Handling
- Beim Start: verfügbare Ports listen. Wenn `input_port` gesetzt →
  Substring-Match; sonst Auswahl in Web-UI erzwingen (Tool startet, MIDI wartet).
- Hotplug: Port-Verlust erkennen (rtmidi-Callback/Fehler), alle 2 s Reconnect
  versuchen, nach Erfolg Full-Resync (§5.4). UI zeigt MIDI-Status.

---

## 6. Camera-Driver-Interface (`drivers/base.py`)

```python
class CameraDriver(ABC):
    """Alle Methoden async. Werte normalisiert 0.0–1.0 wo sinnvoll."""

    # --- Lifecycle ---
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...

    # --- Steuerung ---
    async def set_iris(self, value: float) -> None:        # 0.0=close, 1.0=open
    async def set_auto_iris(self, on: bool) -> None: ...
    async def set_gain_db(self, db: int) -> None: ...
    async def step_gain(self, delta_db: int) -> int: ...   # gibt neuen Wert zurück
    async def set_pedestal(self, value: int) -> None: ...  # Geräte-Range, siehe Driver
    async def set_rb_gain(self, r: int | None, b: int | None) -> None: ...
    async def set_nd(self, index: int) -> None: ...        # 0..3
    async def cycle_nd(self) -> int: ...
    async def set_shutter(self, mode: str, value: int | None) -> None: ...
    async def trigger_awb(self) -> None: ...
    async def set_bars(self, on: bool) -> None: ...
    async def recall_preset(self, number: int) -> None: ...

    # --- Status ---
    async def get_state(self) -> CameraState: ...          # Vollabzug (Startup)
    def subscribe(self, callback: Callable[[CameraEvent], None]) -> None: ...

@dataclass
class CameraState:
    iris: float | None            # 0.0–1.0
    iris_f_number: str | None     # "F4.0", "CLOSE"
    auto_iris: bool | None
    gain_db: int | None
    nd_index: int | None
    shutter: str | None
    bars: bool | None
    error: str | None             # letzter Kamerafehler (rER/OER)
```

Events (`CameraEvent`): `iris_changed`, `gain_changed`, `nd_changed`,
`awb_done` (aus OWS-Notification), `error`, `connection_changed`.

---

## 7. Panasonic-AW-Driver (`drivers/panasonic_aw.py`)

Alle Befehle per HTTP GET. Kein Keep-Alive möglich (Kamera trennt pro Request) —
`httpx.AsyncClient` trotzdem wiederverwenden, er handhabt das transparent.

### 7.1 Befehls-Endpunkte
- Pan/Tilt-Typ (`ptz`): `http://{host}/cgi-bin/aw_ptz?cmd={cmd}&res=1`
  — `#` im Befehl als `%23` encoden.
- Kamera-Typ (`cam`): `http://{host}/cgi-bin/aw_cam?cmd={cmd}&res=1`

### 7.2 Verwendete Befehle (aus AW-UE160 Interface Spec)

| Funktion | Befehl | Range/Werte | Endpunkt |
|---|---|---|---|
| Iris absolut | `#AXI[Data]` | 555h–FFFh (close→open) | aw_ptz |
| Iris absolut (alt.) | `ORV:[Data]` | 000h–3FFh | aw_cam |
| Iris-Position lesen | `#GI` → `gi[Pos][Mode]` | Pos 555h–FFFh; Mode 0=man, 1=auto | aw_ptz |
| F-Nummer lesen | `QIF` → `OIF:[Data]` | 0Eh(F1.4)–A0h(F16)–FFh(CLOSE) | aw_cam |
| Auto-Iris | `ORS:[0/1]` (oder `#D3`) | 0=off, 1=on | aw_cam |
| Gain | `OGU:[Data]` | 02h(−6dB)–08h(0dB)–14h(+12dB), 80h=AGC | aw_cam |
| ND-Filter | `OFT:[0–3]` | THROUGH, 1/4, 1/16, 1/64 | aw_cam |
| Shutter-Mode | `OSJ:03:[0–3]` | OFF/STEP/SYNCHRO/ELC | aw_cam |
| Shutter-Speed | `OSJ:06:[Data]` | 0001h–07D0h (1/1–1/2000, siehe Spec-Tabelle) | aw_cam |
| AWB auslösen | `OWS` | Ergebnis kommt als Notification `OWS` | aw_cam |
| ABB auslösen | `OAS` | Notification `OAS` | aw_cam |
| Bars | `DCB:[0/1]` | 0=off, 1=on | aw_cam |
| Master Pedestal | `OSJ:0F:[Data]` | 738h–800h–8C8h (−200…+200) | aw_cam |
| R Gain (Preset) | `OSL:36:[Data]` | 418h–800h–BE8h (−1000…+1000) | aw_cam |
| B Gain (Preset) | `OSL:38:[Data]` | wie R | aw_cam |
| Preset-Recall | `#R[00–99]` | Antwort `s[n]`, fertig = Notification `q[n]` | aw_ptz |
| Modell abfragen | `QID` → `OID:AW-UE160` | Identifikation beim Connect | aw_cam |
| Fehlerstatus | `QER` / `QSI:46` | Startup-Check | aw_cam |
| Lens-Info an/aus | `#LPC1` / `#LPC0` | 300ms-Zyklus `lPI[ZZZ][FFF][III]` | aw_ptz |

**Iris-Skalierung:** normalisiert 0.0–1.0 ↔ 555h–FFFh (linear).
`0x555 + round(value * (0xFFF - 0x555))`.

**Achtung `OGU` bei AGC:** Wenn AGC aktiv (Antwortwert 80h), Gain-Steps ignorieren
und Solo-LED blinken lassen (UI-Hinweis "AGC aktiv").

### 7.3 Feedback-Kanal
1. **Update-Notifications (bevorzugt):**
   - Registrieren: `http://{host}/cgi-bin/event?connect=start&my_port={p}&uid=0`
     → `204 No Content`.
   - Tool öffnet TCP-Listener auf `{p}` (asyncio). Empfangsformat pro Paket:
     22 B Reserve, 2 B Size, 4 B Reserve, Payload (`Size − 8` Bytes), 24 B Reserve.
     Payload: `\r\n<Befehlsantwort>\r\n` (z. B. `\r\nOAW:1\r\n`, `\r\nOWS\r\n`).
   - Beim Beenden IMMER deregistrieren: `…event?connect=stop&my_port={p}&uid=0`
     (Kamera erlaubt max. 5 gleichzeitige Empfänger; Leichen blockieren Slots).
   - Nach Netzwerkunterbrechung: erneut registrieren (Spec-Vorgabe).
   - Periodische `QSV`-Notifications (60 s) als Heartbeat nutzen: bleiben sie
     > 90 s aus → Verbindung als gestört markieren, Re-Register.
2. **Lens-Info:** `#LPC1` → `lPI[ZZZ][FFF][III]` alle 300 ms (Zoom/Fokus/Iris,
   je 3 Hex-Digits, Iris 555h–FFFh). Primäre Quelle für Fader-Feedback,
   da Iris-Bewegungen NICHT als Update-Notification kommen (`#AXI` hat laut
   Spec kein Update-Notification-Flag).
3. **F-Nummer für Scribble Strip:** `QIF` pollen, aber nur gedrosselt
   (1×/s, und nur wenn sich `lPI`-Iriswert geändert hat).

### 7.4 Fehlerbehandlung
- Kamera-Fehlercodes: `ER1:` (Befehl unbekannt), `ER2:` (busy/Standby),
  `ER3:` (Wert außerhalb Range) bzw. `eR1/2/3` bei ptz-Befehlen.
- `ER2` bei Standby: Kamera als `standby` markieren, UI zeigt Status,
  keine Retry-Schleife.
- `ER3`: Bug im eigenen Mapping → ERROR-Log mit gesendetem Befehl.
- HTTP-Timeout (Default 1,5 s): 1 Retry, danach `connection_changed(False)`,
  Reconnect-Loop alle 5 s (nur `QID`-Ping, keine Steuerbefehle queuen —
  veraltete Iris-Werte nach Reconnect nicht "nachschieben", stattdessen
  Ist-Zustand neu lesen und Fader synchronisieren).

---

## 8. Rate-Limiter (`core/ratelimit.py`)

Pro Kamera eine Instanz. Regeln:
- **Nur bei Wertänderung senden** (Delta-Filter, Hysterese 1 Digit der Zielrange).
- **Max. `rate_limit_hz`** (Default 15/s): Token-Bucket. Bei Überlauf wird der
  jeweils NEUESTE Wert gehalten und beim nächsten freien Slot gesendet
  (latest-wins, keine Queue-Bildung).
- **Keine periodischen Sends** (Spec-Vorgabe: Befehle nur bei Änderungsbedarf).
- Bei Touch-Release: finaler Absolutwert wird außerhalb des Buckets priorisiert
  gesendet.
- Button-Aktionen (Gain, ND, AWB …) laufen am Limiter vorbei (Einzel-Events),
  aber mit 100 ms Mindestabstand zum letzten Befehl derselben Kamera.

---

## 9. Mapping-Engine (`core/mapping.py`)

- Lädt `banks` + `channel_defaults` aus Config, baut Lookup:
  `(element_type, index) → (camera_id, function, params)`.
- Bank-Wechsel (v1: über Web-UI; Hardware-Taste gibt es am Extender nicht):
  Full-Resync aller 8 Kanalzüge (Fader, LEDs, Strips).
- Button-Aktionen v1:

| Action | Verhalten | LED |
|---|---|---|
| `awb_trigger` | `trigger_awb()`; LED blinkt bis `awb_done`-Event, dann 1 s an | blink→an |
| `gain_step` | `step_gain(+step_db)`, bei Max → Wrap auf Min | an wenn ≠ 0dB |
| `nd_cycle` | `cycle_nd()` | an wenn ND ≠ THROUGH |
| `bars_toggle` | `set_bars(!state)` | = Zustand |
| `auto_iris_toggle` | `set_auto_iris(!state)`; bei ON Fader-Feedback weiter aktiv | = Zustand |
| `preset_recall` | `recall_preset(n)`; LED blinkt bis `q`-Notification | blink→aus |
| `shutter_cycle` | Shutter-Modes durchschalten | an wenn ≠ OFF |

- Encoder v1: relativer Modus. `gain`: ±1 Klick = ±1 Step lt. Gerätetabelle.
  `pedestal`: ±1 Digit, mit Beschleunigung (Klicks/100 ms > 3 → ×5).
  LED-Ring zeigt Position innerhalb der Range (Modus "Fan").
- Select-Button: markiert Kamera als "aktiv" für die Web-UI-Detailansicht.

---

## 10. Web-UI (FastAPI + HTMX, Port 8600)

Seiten/Funktionen v1 — bewusst schlank:
1. **Setup:** MIDI-Port-Auswahl (Dropdown, Liste live), Verbindungsstatus
   MIDI + je Kamera (grün/gelb/rot), Buttons "Resync Surface", "Reconnect".
2. **Übersicht:** 8 Kanalzüge als Karten: Name, Iris (Balken + F-Nummer),
   Gain, ND, Auto-Iris-Badge, Fehlerstatus. Live via WebSocket.
3. **Config-Editor:** v1 nur Anzeige des geladenen YAML + "Reload Config"
   (Datei wird extern editiert — bewusste Entscheidung, kein Formular-Editor).
4. **Log-Ansicht:** letzte 200 Zeilen, Filter nach Level.

Kein Auth in v1 (Betrieb im geschlossenen Produktionsnetz); Bind auf
`0.0.0.0` per Config abschaltbar (`127.0.0.1` Default).

---

## 11. Startup-Sequenz

1. Config laden + validieren (Abbruch bei Fehler mit klarer Meldung).
2. Web-UI starten (immer, auch wenn MIDI/Kameras fehlen — Diagnose-Zugang).
3. MIDI-Port öffnen (falls konfiguriert), sonst auf UI-Auswahl warten.
4. Pro Kamera: `connect()` → `QID` (Modell loggen) → `QER` (Fehlerstatus) →
   `get_state()` (Vollabzug via Einzel-Queries: `#GI`, `QIF`, `QGU`, `QFT`,
   `QRS`, `QBR`) → Notifications registrieren → `#LPC1`.
5. Full-Resync der Surface: Fader auf Ist-Iris, LEDs, Scribble Strips.
6. Ready-Log mit Zusammenfassung (n Kameras online, MIDI-Port).

Shutdown (SIGINT/SIGTERM): `#LPC0` je Kamera, Notification-Deregister,
MIDI-Reset (Fader auf 0, Strips leeren), Ports schließen.

---

## 12. Roadmap (nach v1, nur zur Abgrenzung)

- Natives RTP-MIDI ohne Treiber (Variante B), mDNS-Discovery.
- VISCA-over-IP-Driver (Sony/BirdDog; P200-Einschränkungen dokumentieren).
- Scribble-Strip-Farben (X-Touch-SysEx), Kamera-Tally-Farbe.
- Mehrere Extender im Verbund (16/24 Kanäle).
- Lizenzierung/Tiering analog smart-reset (Open Core).

---

## 13. Tests / Abnahmekriterien v1

- [ ] `test_mackie.py`: Pitchbend↔0–1-Roundtrip, Button-Note-Map, SysEx-Bytes
      für Scribble Strip exakt (Golden Bytes).
- [ ] `test_ratelimit.py`: latest-wins bei Burst, kein Send ohne Delta,
      Final-Send bei Release.
- [ ] `test_panasonic.py` gegen Mock-HTTP: korrekte URLs/Encoding (`%23`),
      Iris-Skalierung Randwerte (0.0→`555`, 1.0→`FFF`), ER2/ER3-Handling,
      Notification-Paket-Parsing (Size-Feld, CRLF-Framing).
- [ ] Manuell am Gerät: Fader-Fahrt glatt ohne ER2, Touch-Verhalten korrekt,
      Feedback bei Auto-Iris sichtbar, Reconnect USB-Kabel-Ziehen,
      Reconnect Kamera-LAN-Ziehen, Shutdown räumt Notification-Slot auf
      (`man_session?command=get` vor/nach prüfen).

---

## 14. Offene Punkte (vor/bei Implementierung klären)

1. Reale Note-/CC-Belegung des X-Touch Extender im MC-Mode am Gerät
   verifizieren (§5.2) — `--midi-monitor` zuerst bauen.
2. `QGU`-Query-Kommando für Gain-Ist-Wert gegen Gerät prüfen (Spec listet
   Request `QGU` → `OGU:[Data]`).
3. Verhalten `#AXI` bei aktivem Auto-Iris testen (wird ignoriert oder
   schaltet Auto ab?) → bestimmt, ob Fader-Bewegung Auto-Iris deaktivieren soll
   (empfohlen: ja, explizit `ORS:0` vor erstem `#AXI` nach Touch).
4. Scribble-Strip-Offsets beim Extender identisch zum X-Touch? (Extender ist
   in MC-Welt "Extender-Gerät", ggf. eigene Device-ID im SysEx-Header: 0x15
   statt 0x14 testen.)
