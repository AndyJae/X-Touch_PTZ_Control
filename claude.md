# Claude Project Instructions for PTZ_Control

## Projektkontext

Dieses Repository beschreibt ein PTZ-Shading-Tool für den Behringer X-Touch Extender als MIDI-Blenden-/Shading-Controller für PTZ-Kameras.

Die primäre Quelle der Wahrheit ist die Datei:
- [ptz-shading-tool-spec.md](ptz-shading-tool-spec.md)

Alle Implementierungs- und Änderungsentscheidungen müssen sich auf diese Spezifikation stützen. Wenn etwas in der Spezifikation nicht eindeutig ist, darf nicht geraten oder „aus dem Stand“ ergänzt werden.

## Verbindliche Arbeitsregeln

### 1) Keine Halluzinationen
- Keine Annahmen über APIs, Protokolle, Gerätebefehle, Dateistrukturen oder Konfigurationen machen, die nicht in der Spezifikation stehen.
- Wenn etwas unklar ist, explizit auf den offenen Punkt verweisen oder nach Rückfrage handeln.
- Nicht „eine plausible Lösung“ implementieren, nur weil sie logisch klingt.
- **Uneingeschränkte harte Regel:** niemals halluzinieren — auch außerhalb von Geräte-/Protokolldetails, z. B. bei Architektur-, Scope- oder Anforderungsfragen. Bei jeder Unklarheit nachfragen statt raten.

### 2) Nur aus verifizierbaren Quellen arbeiten
- Relevante Implementierungen und Entscheidungen müssen auf der vorhandenen Spezifikation, vorhandenen Dateien und echten Laufzeit-/Testbelegen basieren.
- Vor Aussagen wie „funktioniert“, „passt“, „ist implementiert“ immer die jeweilige Bestätigung durch Datei, Test oder Ausführung einholen.
- Unbestätigte Behauptungen sind nicht zulässig.

### 3) Scope strikt einhalten
- Fokus auf v1-Scope der Spezifikation.
- Keine Zusatzfunktionen aufnehmen, die nicht in der Spec beschrieben sind.
- Pan/Tilt/Zoom-Steuerung, native RTP-MIDI, mDNS-Discovery und andere Roadmap-Themen sind nicht Teil von v1.

### 4) Tests zuerst und realitätsnah
- Änderungen sollten, wo möglich, durch kleine, reale Tests abgesichert werden.
- Keine Test-Only-Methoden in Production-Code einbauen.
- Mocking nur dann, wenn es die echte Interaktion korrekt abbildet und der Zweck nachvollziehbar ist.

### 5) Keine Erfindung von „gebräuchlichen“ Strukturen
- Neue Module, Methoden, Konfigurationsfelder oder Befehle nur dann hinzufügen, wenn sie in der Spezifikation ausdrücklich vorgesehen oder unmittelbar nötig für ein bereits spezifiziertes Verhalten sind.
- Neue Dateien oder Architekturelemente sind nur dann sinnvoll, wenn sie die vorhandene Struktur sauber ergänzen.

### 6) Minimal-invasiv arbeiten (harte Regel)
- Wo immer möglich die kleinstmögliche, gezielte Änderung wählen statt eines größeren Umbaus.
- Bestehenden Code, Stil oder Struktur nicht „nebenbei“ verbessern, umformatieren oder umbenennen, wenn das nicht Teil der eigentlichen Aufgabe ist.
- Vor einer größeren Änderung prüfen, ob ein chirurgischer, lokal begrenzter Fix denselben Effekt erzielt — wenn ja, diesen Weg wählen.

## Technischer Rahmen aus der Spezifikation

### Stack
- Python 3.11+
- `mido` + `python-rtmidi`
- `httpx` für Kamera-HTTP
- FastAPI + HTMX + WebSocket
- YAML + `pydantic` v2

### Kernarchitektur
- Core/EventBus
- MIDI-Layer
- Camera-Drivers
- Web-UI
- State-Store / Mapping-Engine / Rate-Limiter

### Referenz-Driver
- Panasonic AW-Serie, besonders AW-UE160 — Iris/Gain/Pedestal-Wertebereiche
  und -Kodierung sind weiterhin NUR für AW-UE160 verifiziert (siehe
  `drivers/panasonic_aw.py`-Klassendocstring), unabhängig davon, welches
  Modell über die Button-Feature-Registry (siehe unten) erkannt wird.
- HTTP-basierte Befehle per CGI
- Feedback über Update-Notifications, Lens-Info und Polling
- Externe Referenzquelle für Button-Funktionen: verifizierte `UI_BUTTONS`/
  `UI_BUTTON_LABELS` pro Kameramodell aus `C:\smart_reset_work\camera_plugins\
  panasonic\*.py` (lokal gelesen und als eigene Kopie nach
  `drivers/panasonic_models/*.py` portiert — nicht importiert, siehe Spec §9a
  und Offene Punkte unten). `C:\smart_reset_work` ist die aktiv gepflegte
  Arbeitsversion des Nutzers und die maßgebliche Quelle für künftige Ports;
  `C:\smart-reset-browser` ist nur die veröffentlichte, seltener aktualisierte
  Public-Version desselben Projekts — bei künftigen Portierungen aus dieser
  Quelle also `C:\smart_reset_work` verwenden, nicht `C:\smart-reset-browser`.

## Arbeitsweise bei Codeänderungen

1. Spezifikation lesen und relevante Teile identifizieren.
2. Minimalen, Root-Cause-basierten Fix oder Aufbau wählen.
3. Nur das Nötigste ändern.
4. Nach der Änderung verifizieren:
   - passende Tests oder Reproduktion ausführen
   - Fehler/Diagnostics prüfen
   - Konformität zur Spezifikation gegenprüfen
5. Ergebnisse sauber und faktenbasiert zusammenfassen.

## Hinweise zur Kommunikation

- Jede Abschlussaussage muss sich auf echte Evidenz stützen.
- Wenn beim Arbeiten ein Punkt nicht ausreichend belegt ist, explizit sagen:
  - „Das ist in der Spezifikation nicht definiert.“
  - „Ich benötige eine Verifikation, bevor ich das behaupten würde.“
- Keine Vermutungen über reale Gerätebelegung, SysEx-Offsets oder unbekannte Responses formulieren.

## Offene Punkte

Die Spezifikation enthält eine eigene Liste offener Punkte. Diese sind als verbindliche Grenze zu behandeln:
- ~~reale MC-Belegung des X-Touch Extender verifizieren~~ **Verifiziert** (Kanal 1, echtes
  Gerät): Pitchbend Kanal 1 = Fader 1, Note 104 = Fader-Touch 1, CC 16 = Encoder 1 drehen,
  Note 32 = Encoder-Push 1, Note 0/8/16/24 = Rec/Solo/Mute/Select 1 — exakt wie Spec §5.2
  angenommen. Kanäle 2–8 nicht einzeln geprüft (gleiches Offset-Schema angenommen).
- `QGU`-Abfrage gegen Gerät prüfen (weiterhin nur Dokumentenbeleg, siehe Spec §14 Punkt 2)
- Verhalten von `#AXI` bei aktivem Auto-Iris testen
- ~~Scribble-Strip-Offsets / Device-ID des Extenders verifizieren~~ **Verifiziert**: Device-ID
  `0x15` (nicht `0x14` wie beim regulären X-Touch) — mit `0x14` blieb das Display leer, mit
  `0x15` erscheint der Text. Offsets (0x00–0x37 obere Zeile, 0x38–0x6F untere Zeile) bestätigt.
- ~~Integrationsmechanismus für die Button-Funktionsquelle aus der externen
  Referenzquelle (§9a) — Abhängigkeit/Import der Modell-Module vs. eigene
  Kopie/Adapter; noch nicht festgelegt.~~ **Umgesetzt (Nutzerentscheid):**
  eigene Kopie, kein Import der externen Quelle zur Laufzeit. Jedes
  Kameramodell ist eine eigene Datei unter `drivers/panasonic_models/*.py`
  (`CAMERA_ID`, optional `CAMERA_ID_ALIASES`, `BUTTON_FEATURES`,
  `BUTTON_FEATURE_LABELS`), eine kleine Registry
  (`drivers/panasonic_models/registry.py`, angelehnt an
  `C:\smart_reset_work\core\registry.py`s `PluginRegistry`) laedt sie beim
  ersten Zugriff per `pkgutil` und indiziert sie nach `CAMERA_ID`.
  `PanasonicAWDriver.connect()` loest darüber nach der `QID`-Erkennung den
  passenden Katalog auf (`_apply_model_catalog()`) und ersetzt damit die
  vormals fest auf AW-UE160 hartkodierten Klassenattribute — 17 Modelle
  portiert (siehe `drivers/panasonic_models/__init__.py`). Physische
  Auslösung über den X-Touch Extender ist für den Fader/Iris-Pfad und für
  Rec+Encoder (Funktionsauswahl, Gain/Pedestal live, siehe unten) verdrahtet
  (`midi/fader.py`), aber Solo/Mute/Select sind weiterhin nur Rx-seitig
  verifiziert und noch nicht an `apply_button_action`/
  `trigger_companion_select` angebunden (siehe unten)
- ~~Verhalten bei erkanntem Kameramodell ohne Plugin-Modul (§9a)~~
  **Umgesetzt:** `_apply_model_catalog()` liefert dann leere
  `BUTTON_FEATURES`/`BUTTON_FEATURE_LABELS` und keine Gain-/Pedestal-Werte
  (kein erfundener Fallback) -- die Kamera bleibt trotzdem verbunden, da nur
  Iris modellunabhängig verdrahtet ist; Button 2/3 zeigen für diesen Kanal
  dann einfach keine zuweisbaren Optionen und der Encoder keinen
  Wertebereich für Gain/Pedestal. Getestet in
  `tests/test_panasonic.py::test_apply_model_catalog_empty_for_unrecognized_model`.
- ~~Modellabhängige Gain-/Pedestal-Werte (Bereiche, Schrittweiten, Kommando)
  waren bisher fest auf AW-UE160 hartkodiert~~ **Umgesetzt (2026-07-17):**
  `GAIN_MIN_DB`/`GAIN_MAX_DB`/`GAIN_STEP_DB` sowie
  `PEDESTAL_COMMAND`/`PEDESTAL_QUERY_COMMAND`/`PEDESTAL_MIN`/`PEDESTAL_MAX`/
  `PEDESTAL_CENTER_DATA`/`PEDESTAL_SCALE`/`PEDESTAL_DATA_WIDTH` stehen jetzt
  je Modell in `drivers/panasonic_models/*.py` (Quelle:
  `HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/§3.2.14),
  `PanasonicAWDriver._apply_model_catalog()` löst sie zusammen mit dem
  Button-Katalog auf. Pedestal hat DREI unterschiedliche Kommandofamilien
  (`OSJ:0F` bei AW-UE150/UE160, `OTP`/`QTP` bei AW-HE50/60/120/130/HR140/
  HE40/UE70/HE42, `OSG:4A` bei AK-UB300) -- `set_pedestal()`/
  `step_pedestal()`/`_query_pedestal()` lesen Kommando und Kodierung jetzt
  aus dem Modell statt fest `OSJ:0F` zu senden. AK-UB300 hat bewusst KEINE
  Gain-Werte (strukturell anderes `OGS`-Schema, siehe `ak_ub300.py`).
  Modelle ohne Eintrag in einer der beiden PDFs (AW-UE100/UE80/UE30/40/50/
  UE145) haben bewusst weder Gain- noch Pedestal-Werte (kein erfundener
  Wert). `core/application.py._encoder_value_range()` ersetzt die frühere
  statische `_ENCODER_RANGES`-Konstante und liest den Bereich jetzt vom
  verbundenen Treiber. Getestet in `tests/test_panasonic.py` (u. a.
  `test_apply_model_catalog_resolves_gain_pedestal_for_*`,
  `test_set_pedestal_uses_otp_command_for_he50`,
  `test_step_gain_clamps_to_he50_range`) und `tests/test_panasonic_models.py`.
  **Weiterhin offen:** die per-Tick-Schrittweite des Encoders (±1 Digit,
  ×5-Beschleunigung) berücksichtigt `GAIN_STEP_DB` noch nicht -- bei den
  3dB-Stufen-Modellen (AW-HE50/60/HE40/UE70/HE42) sendet ein einzelner Tick
  weiterhin ±1dB (bzw. ±5dB beschleunigt), nicht zwingend ein gültiges
  Vielfaches von 3. Verhalten der Kamera bei einem solchen Zwischenwert
  (z. B. `OGU:09`) ist nicht dokumentiert/verifiziert.
- Umfang etwaiger PTZ-Control-eigener Zusatzfunktionen über den portierten
  Katalog hinaus (§9a)
- ~~Encoder-Funktion (Gain/Pedestal, §9) hat noch keine Anwendungslogik in
  `core/application.py`/`core/mapping.py` — nur `fader`->Iris ist gemappt~~
  **Umgesetzt, Nutzerentscheid 2026-07-17 (ersetzt das anfängliche Preview/
  Commit-Verhalten):** Rec schaltet fest durch eine Liste `gain`/`pedestal`/
  `camera_status` (`core/application.py._ENCODER_FUNCTIONS`, nicht mehr über
  `config.yaml` konfigurierbar). Drehen sendet bei `gain`/`pedestal` SOFORT
  einen Kamerabefehl (`apply_encoder_turn`, über eine eigene
  `RateLimiter`-Instanz je Kamera, `state.encoder_rate_limiters`, analog zum
  Iris-Fader) statt nur lokal einen Vorschauwert zu sammeln; ein vom Limiter
  zurückgehaltener Tick sammelt sich in `encoder_pending_delta` und wird beim
  nächsten erlaubten Tick nachgereicht. Encoder-Push (`commit_encoder_value`)
  sendet seitdem **nichts** mehr an die Kamera, sondern setzt nur noch
  `encoder_saved[channel]=True` (rote Anzeige in der Web-UI, `is-saved`-Klasse
  auf `.scribble-strip`, bis zum nächsten Dreh-Tick). `core/mapping.py` kennt
  weiterhin nur den `fader`-Eintrag pro Kanal; der Encoder nutzt dieselbe
  Kanal->Kamera-Zuordnung mit, braucht keinen eigenen Mapping-Typ.
  **Bugfix (noch am selben Tag behoben):** der Vorschauwert war zwischenzeitlich
  ungeclampt und konnte weit über die Gerätetabelle hinauslaufen (UI zeigte
  z. B. "+239dB" bei Gain); jetzt in `apply_encoder_turn` auf denselben
  Bereich begrenzt wie das UI-Display (`_ENCODER_RANGES`: Gain -6…+12dB,
  Pedestal -200…+200 lt. `AW-UE160_InterfaceSpecification_E.pdf` Kap. 9
  `OSL:25`/`OSJ:0F`).
  Außerdem: nur noch **eine** Kanal-Anzeige (Web-UI und physisches
  Scribble-Strip zeigen exakt denselben Text über `channel_display_text()`
  in `core/application.py` — das getrennte `.encoder-display`-Element in
  `web/templates/surface.html` ist entfallen), und die Button-1-Spalte ist
  aus der Setup-Seite entfernt (Button 1 war dort ohnehin nur ein
  deaktiviertes Platzhalter-Dropdown).
- MIDI-Buttons Solo/Mute/Select sind Rx-seitig verifiziert (siehe oben), aber nicht mit
  Kamera-Feature-Aktionen bzw. Companion-SELECT verdrahtet. Rec ist verdrahtet, aber nur
  für die Encoder-Funktionsauswahl (`cycle_encoder_function`) — dafür ist Rec laut Spec §9
  auch vorgesehen, nicht für `apply_button_action`/Companion-SELECT.
- Hotplug/Reconnect für den MIDI-Port (Spec §5.5) nicht implementiert
- Web-UI-Port-Auswahl für MIDI (Setup-Seite) ist weiterhin ein statisches Mockup, nicht mit
  echten `mido`-Ports verbunden — Port kommt aktuell nur aus `config.yaml`
- Update-Notifications für andere Ereignisse als Iris (`OAW`, `OWS` etc., Spec §7.3.1) laufen
  technisch über denselben neuen Notification-Kanal, werden aber nicht ausgewertet
  (`PanasonicAWDriver._handle_notification` reagiert nur auf `lPI`)

## Abschlussregel

Bevor eine Änderung als „fertig“ oder „gelöst“ beschrieben wird, muss sie in der Praxis verifiziert sein: durch Test, Laufzeitausgabe, Log, oder nachvollziehbare Datei-/Code-Evidenz.

Wenn etwas nicht verifiziert werden kann, ist der korrekte Status:
- „noch unbestätigt“
- „nicht verifiziert“
- „in der Spezifikation nicht definiert“

Nicht mit „sollte funktionieren“ oder ähnlichen ungesicherten Formulierungen abschließen.
