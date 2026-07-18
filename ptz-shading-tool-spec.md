# Spezifikation: PTZ Shading Tool (Arbeitstitel)

MIDI-Fader-Controller (Behringer X-Touch Extender) als Blenden-/Shading-Steuerung
für PTZ-Kameras. Erster Kamera-Treiber: Panasonic AW-Serie (referenziert: AW-UE160,
Interface Specification Dec. 2023).

---

## 1. Ziel und Scope v1

**Kernfunktion:**
- 8 Motorfader steuern ausschließlich die Blende (Iris) von bis zu 8 Kameras absolut —
  dem Fader ist in v1 keine andere Funktion zuweisbar.
- Button 1 pro Kanal (physisch Rec am X-Touch Extender) ist in v1 fest für die
  Auswahl der Encoder-Funktion reserviert — NICHT Teil der dynamischen,
  kameramodell-abhängigen Aktionszuordnung aus §9a. Details siehe §9.
- Button 2/3 pro Kanal (physisch Solo/Mute, in der UI generisch als „Button 2/3"
  dargestellt, da frei belegbar) — verfügbare Aktionen werden nach
  Kamera-Modell-Erkennung dynamisch bereitgestellt, siehe §9a.
- Encoder pro Kanal steuert die Funktion, die aktuell über Button 1 desselben
  Kanals ausgewählt ist (zyklisches Durchschalten einer festen Liste: Gain,
  Pedestal, Camera Status, siehe §9 und §14 Punkt 8).
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

**Verzeichnisstruktur** (Stand: siehe README.md „Architektur" für den
tagesaktuellen Code-Stand; hier nur die grobe, spec-seitige Einordnung.
`midi/transport.py` und `tests/test_mackie.py` sind noch nicht angelegt --
das X-Touch-MIDI-Layer selbst ist weiterhin nicht verdrahtet, siehe §14):
```
PTZ_Control/
├── main.py                  # Entry: Config laden, uvicorn starten
├── config.yaml              # User-Config
├── core/
│   ├── config.py            # Typisiertes Config-Schema (pydantic v2, §4)
│   ├── bus.py                # Async EventBus (pub/sub, asyncio)
│   ├── state.py              # CameraState/StateStore: Ist-Werte pro Kamera
│   ├── mapping.py            # Mapping-Engine (Kanal ↔ Kamera/Funktion)
│   ├── ratelimit.py          # Rate-Limiter pro Kamera
│   ├── companion.py          # Bitfocus-Companion-HTTP-Trigger (Erweiterung
│   │                          #   über v1 hinaus, siehe §9)
│   └── application.py        # Anwendungsschicht: AppState + alle Use-Cases
├── midi/
│   ├── mackie.py             # MC-Protokoll-Grundgerüst (noch nicht verdrahtet)
│   └── surface.py            # Logische Sicht, Scaffold (noch nicht verdrahtet)
├── drivers/
│   ├── base.py                # Abstrakte Driver-Basis (Interface §6)
│   └── panasonic_aw.py        # AW-UE160-Referenzimplementierung (§7)
├── web/
│   ├── app.py                 # FastAPI-App, Routen, WebSocket (Interface-Schicht)
│   ├── templates/              # Jinja2-Templates
│   └── static/                 # app.css/app.js, images/ (Logo)
├── tools/
│   └── panasonic_emulator.py  # Lokaler Panasonic-CGI-Emulator, Modell waehlbar (Dev-Werkzeug)
└── tests/
    ├── test_application.py
    ├── test_bus.py
    ├── test_companion.py
    ├── test_config.py
    ├── test_mapping.py
    ├── test_panasonic.py       # Gegen Mock-HTTP-Server
    ├── test_ratelimit.py
    ├── test_web_app.py
    └── fakes.py                 # Gemeinsame Test-Doubles
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
        buttons:              # Button-2/3-Zuordnung pro Kanal, siehe §9a.
          button2: drs         # Feature-Key aus dem Katalog des erkannten
          button3: knee        # Kameramodells (button1 ist unzulässig, siehe §9)
      - camera: cam2
      # nicht belegte Kanäle weglassen → Fader unten, Strip leer
      # `buttons` ist optional; ohne Zuordnung sind Button 2/3 des Kanals inaktiv

channel_defaults:            # gilt für jeden Kanalzug, überschreibbar pro Kanal
  fader: iris                # v1 fix: iris, ausschließlich Blende — keine andere Funktion
  # Encoder-Funktionsliste (gain/pedestal/camera_status, in dieser Reihenfolge)
  # ist per Nutzerentscheid fest im Code verdrahtet (core/application.py.
  # _ENCODER_FUNCTIONS) und daher hier kein Konfigurationsfeld mehr — Button 1
  # (rec) schaltet zyklisch durch, siehe §9.
  buttons:
    # rec (Button 1) hat in v1 keine frei belegbare Aktion mehr —
    # fest reserviert für Encoder-Funktionsauswahl, siehe §9
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

**Modellabhängige Gain-/Pedestal-Daten (`drivers/panasonic_models/*.py`,
Quelle: `HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/§3.2.14,
für AW-UE160 zusätzlich `AW-UE160_InterfaceSpecification_E.pdf` Kap. 9, für
AW-UE100 das dedizierte `AW-UE100_InterfaceSpecification_E.pdf` Kap. 9
"Command List", für AW-UE80/UE50/UE40/UE30 das dedizierte
`AW-UE80UE50UE40_InterfaceSpecification_E.pdf` Kap. 9, für AW-UE150/
AW-HE145 zusätzlich/korrigierend das dedizierte
`AW-UE150HE145_InterfaceSpecification_E.pdf` Kap. 9 sowie (jüngste, 2025,
ausschließlich AW-UE150A) `AW-UE150A_InterfaceSpecification_E.pdf` Kap. 9 —
diese vier zuletzt genannten PDFs wurden erst nachträglich ins Repo gelegt,
siehe CLAUDE.md Offene Punkte, Korrekturen 2026-07-18):** Die obige Tabelle zeigt
nur AW-UE160. `OGU`/`QGU` selbst (Data = 0x08 + dB, 80h = AGC) ist laut
allen PDFs modellübergreifend identisch — nur Bereich/Schrittweite variieren
und kommen per Modell-Registry aus `GAIN_MIN_DB`/`GAIN_MAX_DB`/
`GAIN_STEP_DB`:

| Modell(e) | Gain-Bereich | Schrittweite |
|---|---|---|
| AW-UE160 | −6…+12dB | 1dB (kontinuierlich) |
| AW-HE50/AW-HE60 | 0…18dB | 3dB (nur diskrete Stufen) |
| AW-HE120 | 0…18dB | 1dB |
| AW-HE130 | 0…36dB | 1dB |
| AW-HR140 | 0…42dB | 1dB |
| AW-UE150(A)/AW-HE145(+Alias AW-UE145) | −3…+42dB | 1dB (2022er + 2025er dediziertes PDF stimmen ueberein, widersprechen aber dem aelteren 2020er Multi-Modell-PDF, das fuer AW-UE150 0…+42dB nennt — neuere Quellen gewaehlt, siehe `aw_ue150.py`/`aw_he145.py`) |
| AW-UE100/AW-UE80/UE50/UE40/UE30 | 0…42dB | 1dB (nur 0…36dB, wenn "Super Gain" aus ist — Kopplung hier nicht durchgesetzt) |
| AW-HE40/AW-UE70/AW-HE42 | 0…48dB | 3dB (nur diskrete Stufen) |
| AK-UB300 | — | kein `OGU` (siehe unten) |

Damit hat inzwischen jedes registrierte Modell Gain-Daten — ausser AK-UB300
(strukturell anderes `OGS`-Schema, siehe unten).

Pedestal ist dagegen NICHT dasselbe Kommando für alle Modelle — drei
Kommandofamilien (`PEDESTAL_COMMAND`/`PEDESTAL_QUERY_COMMAND` je Modell-Datei):

| Kommando | Modell(e) | Bereich | Data-Formel |
|---|---|---|---|
| `OSJ:0F`/`QSJ:0F` (Master Pedestal) | AW-UE160, AW-UE150(A), AW-HE145, AW-UE100, AW-UE80/UE50/UE40/UE30 | −200…+200 | 0x800 + Wert |
| `OTP`/`QTP` | AW-HE50/HE60/HE40/UE70/HE42 | −10…+10 | 0x96 + Wert×15 |
| `OTP`/`QTP` | AW-HE120/HE130/HR140 | −150…+150 | 0x96 + Wert |
| `OSG:4A`/`QSG:4A` | AK-UB300 | −99…+99 | 0x80 + Wert |

Bei Pedestal hat jedes registrierte Modell (inkl. AK-UB300) Daten — hier gibt
es also keine Luecke mehr.

`PanasonicAWDriver.set_pedestal()`/`step_pedestal()`/`_query_pedestal()`
lesen Kommando, Zentraldatenwert, Skalierung und Hex-Breite aus dem per
Modell-Registry aufgelösten Modul (`_apply_model_catalog()`) statt fest
`OSJ:0F` zu verwenden. Ein (aktuell nicht mehr vorkommendes, aber weiterhin
moeglich, falls ein noch unbekanntes Modell auftaucht) Modell ohne Eintrag
in einer der lokalen PDFs haette weder Gain- noch Pedestal-Konstanten —
Encoder zeigt dafür keinen Wertebereich (kein erfundener Fallback); Zeile 2
der Kanal-Anzeige zeigt in diesem Fall explizit "n/a" statt stillschweigend
auf die Camera-Status-
Anzeige zurückzufallen (`_encoder_function_unsupported()` in
`core/application.py`, Bugfix 2026-07-18).

**Gain-Sonderfall AK-UB300:** hat kein `OGU`/`QGU` — stattdessen `OGS`
(Gain-Auswahl LOW/MID/HIGH/S.GAIN1-3) + `OSA:50`/`OSA:51`/`OSA:52` (dB-Werte
je Bereich, −6…+36dB), strukturell inkompatibel mit `set_gain_db(db)`/
`step_gain(delta)` — bewusst nicht implementiert (kein Encoder-Gain für
dieses Modell). Pedestal (`OSG:4A`) ist davon unabhängig und implementiert.

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
- Button 1 (physisch Rec) je Kanal ist von der folgenden Tabelle ausgenommen —
  seine Funktion ist fest die Encoder-Funktionsauswahl (siehe unten).
- Button-Aktionen v1 für Button 2/3 (vorläufig — wird durch den dynamischen
  Mechanismus aus §9a abgelöst):

| Action | Verhalten | LED |
|---|---|---|
| `awb_trigger` | `trigger_awb()`; LED blinkt bis `awb_done`-Event, dann 1 s an | blink→an |
| `gain_step` | `step_gain(+step_db)`, bei Max → Wrap auf Min | an wenn ≠ 0dB |
| `nd_cycle` | `cycle_nd()` | an wenn ND ≠ THROUGH |
| `bars_toggle` | `set_bars(!state)` | = Zustand |
| `auto_iris_toggle` | `set_auto_iris(!state)`; bei ON Fader-Feedback weiter aktiv | = Zustand |
| `preset_recall` | `recall_preset(n)`; LED blinkt bis `q`-Notification | blink→aus |

### Encoder-Funktionsauswahl über Button 1

- Der Encoder eines Kanals steuert immer die Funktion, die aktuell über Button 1
  (physisch Rec) desselben Kanals ausgewählt ist. Ein Druck auf Button 1 sendet
  keinen Kamerabefehl, sondern schaltet nur lokal um, welche Funktion der Encoder
  als Nächstes steuert. Button 1 zeigt (Web-UI) den Namen der aktiven Funktion
  an, statt eines statischen Labels — es gibt daher auch kein eigenes
  Konfigurations-UI für Button 1 auf der Setup-Seite (Nutzerentscheid).
- Jeder Druck auf Button 1 schaltet die aktive Encoder-Funktion zyklisch durch
  eine **feste** Liste (Nutzerentscheid, nicht mehr über `config.yaml`
  konfigurierbar, siehe `core/application.py._ENCODER_FUNCTIONS`): **Gain →
  Pedestal → Camera Status → (wrap)**.
  Treiber-Methoden: `gain`→`step_gain`, `pedestal`→`step_pedestal` (Panasonic-
  Terminologie "Master Pedestal", §7.2); `camera_status` ist ein reiner
  Anzeige-Eintrag ohne Kamera-Aktion (zeigt Kameraname + Iris-%).
- Encoder v1, relativer Modus, **Nutzerentscheid (Live-Senden statt
  Preview/Commit)**: Drehen sendet bei `gain`/`pedestal` SOFORT einen
  Kamerabefehl (`apply_encoder_turn` in `core/application.py`) — ±1 Klick =
  ±1 Digit, Beschleunigung ×5 nach >3 Klicks/100 ms. Das läuft über eine
  eigene Rate-Limiter-Instanz je Kamera (dieselbe Idee wie beim Iris-Fader,
  §8), damit nicht jeder MIDI-Tick einen eigenen HTTP-Request auslöst; ein
  vom Limiter zurückgehaltener Tick geht nicht verloren, sondern sammelt sich
  auf und wird beim nächsten erlaubten Tick als Gesamt-Delta nachgereicht.
  Der vorgeschlagene Wert wird dabei auf den bestätigten Gerätebereich
  geclampt (`_encoder_value_range()` in `core/application.py`, liest
  `gain_min_db`/`gain_max_db` bzw. `pedestal_min`/`pedestal_max` vom
  verbundenen Treiber — modellabhängig seit dem Umbau in §9a, siehe §7.2 für
  die Werte je Modell) — **Bugfix 2026-07-17:** vor diesem Clamping lief ein
  noch nicht gesendeter Vorschauwert unbegrenzt weiter (Anzeige zeigte z. B.
  "+239dB"). LED-Ring zeigt Position innerhalb der Range (Modus "Fan").
- Encoder-Push (physischer Druckknopf des Encoders, Note 32–39, §5.2) sendet
  seit der Umstellung auf Live-Senden **keinen** Kamerabefehl mehr — der Wert
  ist zu diesem Zeitpunkt bereits aktuell. Er markiert den Kanal nur visuell
  als "gespeichert" (`commit_encoder_value()`): die Anzeige wird rot, bis der
  nächste Dreh-Tick sie zurücksetzt (Nutzerentscheid, Web-UI-only — keine
  verifizierte Hintergrundfarben-Ansteuerung für das physische Scribble-Strip).
- Select-Button: markiert Kamera als "aktiv" für die Web-UI-Detailansicht.

**EINE Kanal-Anzeige (Nutzerentscheid, Abkehr von der ursprünglichen
"2 Displays in der Web-UI"-Entscheidung):** Das physische Scribble-Strip und
die Web-UI zeigen exakt denselben Text über dieselben Funktionen
(`channel_line1_text()`/`channel_display_text()` in `core/application.py`).
Bei `camera_status`: Zeile 1 Kameraname, Zeile 2 Iris-% (Platzhalter bis zur
F-Nummer-Tabelle, §14 Punkt 10). Bei `gain`/`pedestal` (Nutzerentscheid):
Zeile 1 zeigt stattdessen den Funktionsnamen (GAIN/PEDESTAL) statt des
Kameranamens, Zeile 2 den unitlosen Rohwert im bestätigten Gerätebereich
(Pedestal z. B. `-45`, **kein** Prozentwert und kein zusätzliches
Funktions-Präfix mehr — das übernimmt Zeile 1). Die Web-UI ergänzt nur das
rote "gespeichert"-Feedback, das es auf dem physischen Gerät nicht gibt.

**Bewusste Erweiterung über v1 hinaus (Nutzerentscheid):** Der SELECT-Button
löst zusätzlich einen Bitfocus-Companion-Button (v3, Location-Adressierung
Page/Row/Column) fern aus, z. B. für eine Kreuzschienen-Schaltung. Eine
Companion-Instanz gilt global für alle Kanäle (Host/Port, Setup-Seite, an
der Stelle des ehemaligen "Camera Status"-Blocks); pro Kanal wird optional
ein Page/Row/Column-Ziel hinterlegt (Setup-Tabelle, Spalte "Select
(Companion)"). Endpunkt verifiziert gegen die offizielle Companion-Doku
(`companion.free/user-guide/v5.0/remote-control/http-remote-control`,
aktuellste verfügbare Version -- eine archivierte v3-Seite war nicht
erreichbar, aber das Location-Schema wurde laut Doku mit v3 eingeführt und
löste das dortige "legacy"-Bank-Nummern-Schema ab, gilt also unverändert ab
v3): `POST http://<host>:<port>/api/location/<page>/<row>/<column>/press`.
PTZ_Control kennt den eigentlichen Companion-Befehl (z. B. die
Kreuzschiene) nicht, nur die Adresse -- die Aktion selbst ist in Companion
konfiguriert. Implementierung: `core/companion.py`.

---

## 9a. Button-Funktionsquelle: Kamera-Modell-Erkennung (extern: `C:\smart_reset_work`)

**Status: Modell-Registry mit 17 Panasonic-Modellen umgesetzt (Nutzerentscheid).
Physische X-Touch-Auslösung für Button 2/3 (Solo/Mute) weiterhin offen (siehe §14).**

Externe Referenzquelle: `C:\smart_reset_work\camera_plugins\panasonic\*.py`
(`UI_BUTTONS`/`UI_BUTTON_LABELS` pro Kameramodell, dort gegen reale
Panasonic-Interface-Specs verifiziert, siehe deren eigene `CLAUDE.md`, Regel
„Do not invent camera API commands or response formats"). `C:\smart_reset_work`
ist die aktiv gepflegte Arbeitsversion des Nutzers (maßgeblich für künftige
Ports); `C:\smart-reset-browser` ist nur die veröffentlichte, seltener
aktualisierte Public-Version desselben Projekts — für Portierungen aus dieser
Quelle gilt daher `C:\smart_reset_work`, nicht `C:\smart-reset-browser`.

**Umsetzung — Modell-Registry (`drivers/panasonic_models/`):** jedes
Kameramodell ist eine eigene Datei (`CAMERA_ID`, optional
`CAMERA_ID_ALIASES`, `BUTTON_FEATURES`, `BUTTON_FEATURE_LABELS`) — wörtlich
aus der jeweiligen `UI_BUTTONS`/`UI_BUTTON_LABELS`-Definition der Referenz-
quelle portiert (Toggle-Struktur `{"on"/"off"}` → `{"kind":"toggle",
"on"/"off"}`, Trigger `{"cmd"}` → `{"kind":"trigger","cmd"}`, Cycle
`{"cycle"}` → `{"kind":"cycle","cycle"}`, analog zur bisherigen AW-UE160-
Portierung). `RESET_COMMANDS`/`UI_LAYOUT`/`UI_DROPDOWNS` aus der Quelle
gehören zu deren eigenem Reset-Tool und haben in PTZ_Control keine
Entsprechung — Button 2/3 sind hier frei aus dem Katalog zuweisbar, kein
fester Grid-/Dropdown-Aufbau. Alias-Modelle (z. B. AW-HE60 zu AW-HE50)
re-exportieren `BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS` vom Basismodell,
genau wie in der Quelle.

Eine kleine Registry (`drivers/panasonic_models/registry.py`, angelehnt an
`C:\smart_reset_work\core\registry.py`s `PluginRegistry`, aber ohne dessen
Transport-Registry-Hälfte — PTZ_Control hat nur einen Treiber für alle diese
Modelle) lädt alle Modell-Dateien beim ersten Zugriff per `pkgutil` und
indiziert sie nach `CAMERA_ID` (inkl. Aliases). Kein Cross-Repo-Import zur
Laufzeit — die Modell-Dateien sind eine eigene Kopie in diesem Repo (gleiches
Muster wie `tools/panasonic_emulator.py`).

Beim Verbinden einer Kamera wird das Kameramodell per `QID` erkannt (Teil des
bestehenden Schritts in der Startup-Sequenz, §11); `PanasonicAWDriver.
connect()` löst danach über die Registry den passenden Katalog auf
(`_apply_model_catalog()`) und setzt ihn als Instanzattribute
`BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS` — nicht mehr fest auf AW-UE160
hartkodierte Klassenattribute wie vor diesem Umbau. Die Zuordnung Button 2/3
→ Feature-Key ist weiterhin pro Kanal in `config.yaml` persistiert
(`banks[].channels[].buttons`, §4), über die Setup-Seite editierbar.
Ausgelöst wird die Aktion aktuell **nur** über die Button-2/3-Elemente der
Übersicht-Seite (Web-UI) — **nicht** über den physischen X-Touch Extender
(Solo/Mute sind laut CLAUDE.md nur Rx-seitig verifiziert, nicht an
`apply_button_action` angebunden). Zustand (an/aus bzw. Cycle-Stufe) wird wie
in der Referenzquelle nur lokal getrackt, nicht durch Kamera-Rückfrage
verifiziert — für die genutzten Kommandos existiert kein Query-Gegenstück.

**Scope-Grenze:** Der Modell-Registry-Umbau deckt inzwischen sowohl den
Button-2/3-Katalog als auch Gain/Pedestal ab (`GAIN_MIN_DB`/`GAIN_MAX_DB`/
`GAIN_STEP_DB`/`PEDESTAL_COMMAND` u. ä. je Modell-Datei, siehe §7.2 für die
Werte) — `_apply_model_catalog()` löst beides gemeinsam auf. Nur Iris
(`_IRIS_DATA_MIN/MAX` in `drivers/panasonic_aw.py`) bleibt unabhängig vom
erkannten Modell weiterhin nur für AW-UE160 verifiziert, das ist ein
separater, noch offener Punkt (§14).

Portierte Modelle (`drivers/panasonic_models/`, CAMERA_ID — Aliases in
Klammern): AW-UE160; AW-HE50 (AW-HE50H/E/S); AW-HE60 (AW-HE60H/E/S, Katalog
= AW-HE50); AW-HE40 (viele Aliases, u. a. AW-HE65/70, AW-HN38/40/65/70);
AW-HE42 (AW-HE75/68, Katalog = AW-HE40); AW-UE70 (AW-UN70, AW-UE65/63,
Katalog = AW-HE40); AW-HE120 (AW-HE125, AW-HE120W/K); AW-HE130 (AW-HE135,
AW-HE130W/K); AW-HR140 (AW-HR140E/N); AW-UE100 (keine Aliases); AW-UE150A
(AW-UE150, AW-UE155, AW-UN145 — CAMERA_ID ist bewusst "AW-UE150A", "AW-UE150"
ist dort nur ein Alias, kein Tippfehler); AW-HE145 (AW-UE145/AW-UE150HE/
AW-UE150HE145 — CAMERA_ID war urspruenglich faelschlich "AW-UE145", per
`docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf` auf die echte
QID-Antwort "AW-HE145" korrigiert (2026-07-18), "AW-UE145" blieb als Alias
erhalten; Katalog = AW-UE150A); AW-UE80 (keine Aliases); AW-UE30/UE40/UE50 (je Katalog =
AW-UE80); AK-UB300 (AK-UB300GJ/EJ — AK-Serie, nicht AW; weicht beim
Gain-Befehl ab, siehe §7.2, betrifft aber nicht diesen Katalog).

Beispiel AW-UE160 (`drivers/panasonic_models/aw_ue160.py`): Auto Focus, Auto
Iris, ABB (Black), AWW (White), DRS, Flare, Gamma, Knee (Cycle:
Off/Manual/Auto), Linear Matrix, Matrix, OSD, White Clip.

Wird ein Kameramodell erkannt, für das keine Datei registriert ist, liefert
`_apply_model_catalog()` leere `BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS` und
keine Gain-/Pedestal-Werte (kein erfundener Fallback) — die Kamera bleibt
trotzdem verbunden (Iris ist modellunabhängig verdrahtet), Button 2/3 zeigen
für diesen Kanal einfach keine zuweisbaren Optionen und der Encoder zeigt für
Gain/Pedestal keinen Wertebereich.

Zusätzliche, PTZ-Control-eigene Funktionen über den portierten Katalog
hinaus (z. B. aus der bisherigen Aktionsliste in §9) sind möglich, aber
Umfang und Auswahl sind noch nicht festgelegt (§14).

---

## 10. Web-UI (FastAPI + HTMX, Port 8600)

Seiten/Funktionen v1 — bewusst schlank:
1. **Setup:** MIDI-Port-Auswahl (Dropdown, Liste live), Verbindungsstatus
   MIDI + je Kamera (grün/gelb/rot), Buttons "Resync Surface", "Reconnect".
   Kamera-Registrierung pro Kanal (Name/IP/Port, "Connect Camera"-Button in
   der Kanal-/Tastenbelegungs-Tabelle) — **Nutzerentscheid, Abkehr von der
   ursprünglichen §10.3-Entscheidung**: Kameras werden nicht mehr extern in
   `config.yaml` eingetragen, sondern ausschließlich über diesen Button;
   die App persistiert Name/IP/Port selbst in `config.yaml` und verbindet
   sofort. Kamera-ID intern deterministisch `cam{Kanalnummer}` — erneutes
   Klicken in derselben Zeile aktualisiert dieselbe Kamera (z. B. bei
   IP-Wechsel) statt eine zweite anzulegen.
2. **Übersicht:** 8 Kanalzüge als Karten: Name, Iris (Balken + F-Nummer),
   Gain, ND, Auto-Iris-Badge, Fehlerstatus, sowie aktive Encoder-Funktion
   (per Button 1 gewählt, siehe §9) und deren aktueller Wert. Live via WebSocket.
3. **Config-Editor:** v1 nur Anzeige des geladenen YAML + "Reload Config"
   (freies YAML wird weiterhin extern editiert — bewusste Entscheidung, kein
   allgemeiner Formular-Editor). Kamera-Stammdaten sind davon ausgenommen,
   siehe Punkt 1 oben — die "kein Formular-Editor"-Entscheidung bezieht sich
   nur noch auf die restliche, generische YAML-Struktur (Bänke abseits der
   Kamera-Zuordnung, `channel_defaults`, `global`, `midi`).
4. **Log-Ansicht:** letzte 200 Zeilen, Filter nach Level.

Kein Auth in v1 (Betrieb im geschlossenen Produktionsnetz); Bind auf
`0.0.0.0` per Config abschaltbar (`127.0.0.1` Default).

---

## 11. Startup-Sequenz

1. Config laden + validieren (Abbruch bei Fehler mit klarer Meldung).
2. Web-UI starten (immer, auch wenn MIDI/Kameras fehlen — Diagnose-Zugang).
3. MIDI-Port öffnen (falls konfiguriert), sonst auf UI-Auswahl warten.
4. Pro Kamera: `connect()` → `QID` (Modell erkennen — bestimmt u. a. die
   verfügbaren Button-Aktionen, siehe §9a; Modell wird zusätzlich geloggt) →
   `QER` (Fehlerstatus) →
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

1. ~~Reale Note-/CC-Belegung des X-Touch Extender im MC-Mode am Gerät
   verifizieren (§5.2) — `--midi-monitor` zuerst bauen.~~ **Verifiziert**
   (Kanal 1, echtes Gerät, via `tools/midi_monitor.py`): Pitchbend Kanal 1 =
   Fader 1, Note 104 = Fader-Touch 1, CC 16 = Encoder 1 drehen (relativ +),
   Note 32 = Encoder-Push 1, Note 0/8/16/24 = Rec/Solo/Mute/Select Kanal 1 —
   exakt wie oben angenommen, keine Abweichung. Kanäle 2–8 nicht einzeln
   geprüft (gleiches Offset-Schema angenommen, nicht verifiziert).
2. ~~`QGU`-Query-Kommando für Gain-Ist-Wert gegen Gerät prüfen~~ **Bestätigt durch
   Herstellerdoku** (AW-UE160_InterfaceSpecification_E.pdf, Kap. 9, Tabelle „GAIN", S. 47):
   `Request: QGU` → `Response: OGU:[Data]`, gleiche Kodierung wie Control-Befehl. Auch in
   der Multi-Modell-Spec für dieselbe Befehlsfamilie bestätigt (HDIntegratedCamera-Spec,
   Kap. 3.2.6, S. 68) — gilt für Modelle mit `OGU` (nicht AK-UB300, siehe §7.2-Hinweis).
   **Noch unbestätigt gegen echtes Gerät** — nur Dokumenten-Beleg, kein Laufzeittest.
3. Verhalten `#AXI` bei aktivem Auto-Iris testen (wird ignoriert oder
   schaltet Auto ab?) → bestimmt, ob Fader-Bewegung Auto-Iris deaktivieren soll
   (empfohlen: ja, explizit `ORS:0` vor erstem `#AXI` nach Touch).
   **Geprüft, weiterhin offen:** Weder AW-UE160_InterfaceSpecification_E.pdf noch
   die Multi-Modell-Spec (HDIntegratedCamera_InterfaceSpecifications-E.pdf) dokumentieren
   dieses Verhalten. Bleibt ein Punkt, der nur per echtem Gerätetest zu klären ist.
4. ~~Scribble-Strip-Offsets beim Extender identisch zum X-Touch? (Extender ist
   in MC-Welt "Extender-Gerät", ggf. eigene Device-ID im SysEx-Header: 0x15
   statt 0x14 testen.)~~ **Verifiziert**: Device-ID ist `0x15` (nicht `0x14`,
   das ist der reguläre X-Touch) — mit `0x14` blieb das Display leer, mit
   `0x15` erschien der Text (`F0 00 00 66 15 12 <offset> <text> F7`).
   Offsets (0x00–0x37 obere Zeile, 0x38–0x6F untere Zeile, je 7 Zeichen ×
   8 Strips) unverändert bestätigt. Siehe `midi/fader.py`.
5. ~~Integrationsmechanismus für die Button-Funktionsquelle aus der externen
   Referenzquelle (§9a) — Abhängigkeit/Import der Modell-Module vs. eigene
   Kopie/Adapter; noch nicht festgelegt.~~ **Umgesetzt (Nutzerentscheid):**
   eigene Kopie (`drivers/panasonic_models/*.py`, 17 Modelle), kein Import
   der externen Quelle zur Laufzeit; Registry laedt/indiziert per `pkgutil`
   nach `CAMERA_ID` (siehe §9a).
6. ~~Verhalten wenn ein erkanntes Kameramodell kein Plugin-Modul besitzt
   (§9a) — noch nicht spezifiziert.~~ **Umgesetzt:** leere
   `BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS`, kein erfundener Fallback,
   Verbindung bleibt bestehen (siehe §9a).
7. Umfang etwaiger PTZ-Control-eigener Zusatzfunktionen über den
   portierten Katalog hinaus (§9a) — auf später verschoben.
8. ~~Vollständige Liste der über Button 1 wählbaren Encoder-Funktionen (v1
   vorläufig: Gain, Shutter, Master Black, siehe §9) — inkl. verbindlicher
   Zuordnung zu Treiber-Methoden und Encoder-Skalierung/Beschleunigung pro
   Funktion.~~ **Final festgelegt (Nutzerentscheid):** feste Liste Gain →
   Pedestal → Camera Status, nicht mehr konfigurierbar (`core/application.py.
   _ENCODER_FUNCTIONS`). `gain`→`step_gain`, `pedestal`→`step_pedestal` sind
   verdrahtet, Skalierung ±1 Digit/Klick mit ×5-Beschleunigung >3 Klicks/100 ms
   implementiert. Shutter ist per Nutzerentscheid (2026-07-17) komplett aus
   dem Scope entfernt — kein Treiber-Code (`set_shutter`), kein Config-Feld,
   kein Encoder-Eintrag mehr.
9. ~~Verwendung des Encoder-Push (Note 32–39, §5.2), nachdem die
   Funktionsauswahl auf Button 1 verlagert wurde — aktuell ungenutzt.~~
   **Umgesetzt, dann per Nutzerentscheid am 2026-07-17 geändert:** Encoder-
   Push sendet keinen Kamerabefehl mehr (Gain/Pedestal senden seit diesem
   Datum schon beim Drehen live, siehe §9) — er markiert den Kanal nur noch
   visuell als "gespeichert" (`commit_encoder_value()` in
   `core/application.py`, verdrahtet in `midi/fader.py`).
10. F-Nummer-Dekodiertabelle (`QIF`/`OIF:[Data]`, §7.2): **Geprüft, weiterhin offen —
    genauere Analyse nötig, bevor eine echte F-Zahl (z. B. „F 4.0") angezeigt werden kann.**
    AW-UE160_InterfaceSpecification_E.pdf (Kap. 9, S. 67, „REQUEST IRIS F NO.") nennt für
    AW-UE160 nur drei Ankerpunkte: 0Eh=F1.4, A0h=F16, FFh=CLOSE. Die Multi-Modell-Spec
    (HDIntegratedCamera_InterfaceSpecifications-E.pdf, S. 48/279) hat eine feinere
    4-Punkte-Tabelle (0Eh=F1.4, 1Ch=F2.8, 38h=F5.6, A0h=F16), die aber ausdrücklich nur für
    AK-UB300/AW-UE150 gilt, nicht AW-UE160. Diese vier Punkte sind zudem nicht gleichmäßig
    gestuft (0Eh→1Ch und 1Ch→38h verdoppeln den Hex-Wert je 1 Blendenstufe, 38h→A0h aber nur
    ~2,86× für 3 Blendenstufen) — eine Interpolation zwischen den Ankerpunkten wäre also
    keine verlässliche Berechnung, sondern eine Annahme. **In der Spezifikation nicht
    definiert; bis zur genaueren Analyse (z. B. Messung gegen eine echte Kamera) bleiben
    Web-UI und Scribble-Strip-Zeile 2 (`midi/fader.py`) bei einer Iris-Prozentanzeige statt
    einer erfundenen F-Zahl.**
    `drivers/panasonic_aw.py` gibt den Rohwert unverändert zurück, dekodiert nicht.
11. ~~Response-Format von `QBR` (Bars-Status)~~ **Bestätigt:** `QBR` → `OBR:[Data]`
    (0=Off, 1=On), identisch zur Control-Kodierung von `DCB`
    (AW-UE160_InterfaceSpecification_E.pdf, Kap. 9, S. 34, „BAR"); laut Multi-Modell-Spec
    konsistent über die gesamte AW-Familie (HDIntegratedCamera, Kap. 3.2.2). `get_state()`
    liefert den Wert weiterhin `None`, bis er im Treiber implementiert wird (kein
    Code-Änderung in diesem Schritt).
