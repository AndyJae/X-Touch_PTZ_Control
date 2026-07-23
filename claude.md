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
- **Nutzerentscheid 2026-07-19:** für manuelle/Live-Verifikation gegen einen simulierten
  Kamera-CGI-Server zuerst den externen Emulator unter `C:\Panasonic_PTZ_Emulator` verwenden
  (siehe „Externer Test-Emulator" unten), nicht mehr zuerst das eingebaute
  `tools/panasonic_emulator.py`. Das eingebaute Tool bleibt vorerst bestehen (siehe dortiges
  `TODO.md` Abschnitt 6: Umstellung/Entfernen ist ein eigener, noch nicht erfolgter Schritt in
  diesem Repo, erst wenn das externe Tool nachweislich alle bisher genutzten Testfälle
  abdeckt) — bei Bedarf oder wenn der externe Emulator eine benötigte Kameramodell-/
  Kommandokombination (noch) nicht abbildet, darf weiterhin auf `tools/panasonic_emulator.py`
  zurückgegriffen werden, das dann aber explizit als Ausweichlösung benennen.

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
- `pystray` + `Pillow` für den System-Tray-Prozesseinstieg (`main.py`, Nutzerentscheid
  2026-07-19, siehe Spec §11 und Offene Punkte)

### Kernarchitektur
- Core/EventBus
- MIDI-Layer
- Camera-Drivers
- Web-UI
- State-Store / Mapping-Engine / Rate-Limiter

### Externer Test-Emulator
- Eigenständiges Repo `C:\Panasonic_PTZ_Emulator` (separat von PTZ_Control, keine
  Laufzeit-Abhängigkeit in beide Richtungen) — soll laut dessen eigenem `CLAUDE.md`
  künftig sowohl von `PTZ_Control` als auch von `smart_reset_work`/`smart-reset-browser`
  als gemeinsamer externer Test-Prozess genutzt werden, statt dass jede App ihre eigene
  Emulator-Kopie pflegt.
- Start: `python main.py [--host 127.0.0.1] [--ui-port 8080] [--port 8081] [--model AW-UE160]`
  (im `.venv` des Emulator-Repos) startet die Control-UI unter `http://127.0.0.1:8080/`.
  Der eigentliche Kamera-CGI-Server (Standard-Port `8081`, passend zu den in `config.yaml`
  üblicherweise verwendeten Testkameras) läuft NICHT automatisch mit, sondern muss über die
  Control-UI (Modell wählen, „Server starten") oder per `POST /start` (Form-Felder
  `model_id`, `port`) einzeln gestartet werden.
- Deckt laut dessen `CLAUDE.md`/`TODO.md` sowohl das Doppelpunkt-Protokoll
  (`O<sub>:addr:value`/`Q<sub>:addr`) als auch die doppelpunktlosen `#AXI`/`#GI`/`#R`-Befehle
  ab, inkl. modellabhängiger Gain-/Pedestal-Simulation und Update-Notification-Push — Stand
  2026-07-19 durch 43 eigene Tests des Emulator-Repos abgedeckt (dort verifizieren, nicht
  hier annehmen, falls sich das ändert).

### Referenz-Driver
- Panasonic AW-Serie, besonders AW-UE160 — Iris-Wertebereich/-Kodierung ist
  weiterhin NUR für AW-UE160 verifiziert (siehe `drivers/panasonic_aw.py`-
  Klassendocstring). Gain/Pedestal sind dagegen inzwischen für praktisch
  jedes registrierte Modell einzeln PDF-verifiziert (siehe Offene Punkte),
  nicht mehr nur für AW-UE160.
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
  `drs`/`knee` sind seit 2026-07-18 zusätzlich gegen die lokalen PDFs
  gegengeprüft (und korrigiert, wo smart_reset_work sie falsch als Toggle
  statt Cycle führte) — der Rest des Katalogs pro Modell (`auto_focus` u.
  Ä.) ist weiterhin nur gegen smart_reset_work verifiziert, nicht gegen PDF.

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
  angenommen. ~~Kanäle 2–8 nicht einzeln geprüft (gleiches Offset-Schema angenommen).~~
  **Kanäle 2–8 vollständig verifiziert (2026-07-20, echtes Gerät, via
  `tools/midi_monitor.py`, drei Durchläufe):** Solo 1–8 = Note 8–15, Mute 1–8 = Note
  16–23, Select 1–8 = Note 24–31, Rec 1–8 = Note 0–7, Fader-Touch 1–8 = Note 104–111,
  Encoder 1–8 drehen = CC 16–23, Encoder-Push 1–8 = Note 32–39 — jeweils alle 8 Kanäle
  einzeln betätigt, alles exakt wie angenommen, keine Abweichung. Damit ist die
  komplette MC-Belegung aus Spec §5.2 über alle 8 Kanäle hardwareverifiziert (vorher
  nur Kanal 1).
- ~~`QGU`-Abfrage gegen Gerät prüfen (weiterhin nur Dokumentenbeleg, siehe Spec §14
  Punkt 2)~~ **Verifiziert (2026-07-20, reale AW-UE160 `192.168.0.10`):** `QGU` liefert
  `OGU:08`, dekodiert zu 0dB (Default-Gain) — Format und Dekodierung bestätigt.
- ~~Verhalten von `#AXI` bei aktivem Auto-Iris testen~~ **Verifiziert (2026-07-20, reale
  AW-UE160 `192.168.0.10`, siehe Spec §14 Punkt 3):** `#AXI` wird bei aktivem Auto-Iris
  (`ORS:1`) stillschweigend ignoriert (kein Fehler, aber keine Wirkung auf die Iris-
  Position; Auto-Iris bleibt aktiv). ~~Daraus folgender, noch offener Implementierungs-
  punkt: Fader-Touch löst aktuell kein automatisches `ORS:0` aus — eine Fader-Bewegung
  bei aktivem Auto-Iris ist deshalb derzeit wirkungslos, ohne dass die UI das anzeigt.~~
  **UI-Teil behoben (Nutzerauftrag 2026-07-23, Bugreport "Fader springt beim Ziehen
  waehrend Auto-Iris nicht automatisch auf die korrekte Position zurueck"):**
  `core/application.py::apply_iris()` uebernimmt den Fader-Zielwert nicht mehr blind in
  `cam_state.iris`, wenn `cam_state.auto_iris` (zuletzt bekannter Stand) `True` ist --
  stattdessen wird `driver.query_iris()` (neu, oeffentliche Umbenennung der bisherigen
  `PanasonicAWDriver._query_iris()`, liest weiterhin `#GI`, jetzt auch Teil der
  `CameraDriver`-ABC in `drivers/base.py`) erneut abgefragt und die daraus gelesene
  ECHTE Position + der ECHTE Auto-Iris-Modus verwendet -- Web-Slider und Motorfader
  springen damit auf jedem weiterhin durchgelassenen Tick zurueck auf die tatsaechliche
  Position, solange Auto-Iris aktiv bleibt (und uebernehmen dabei auch gleich mit, wenn
  die Kamera zwischenzeitlich selbst auf Auto-Iris AUS gewechselt hat). Ist Auto-Iris
  (soweit bekannt) aus, bleibt das bisherige, guenstigere Verhalten (Zielwert direkt
  uebernehmen, keine zusaetzliche Abfrage) unveraendert -- kein zusaetzlicher
  Netzwerk-Overhead im Normalfall. `tests/fakes.py::FakeCameraDriver` simuliert das
  reale Ignorieren jetzt ebenfalls (`set_iris()` laesst `iris` unveraendert, wenn
  `auto_iris=True`), neue `query_iris()`-Methode. Getestet in
  `tests/test_application.py` (`test_apply_iris_snaps_back_to_real_position_while_
  auto_iris_active`, `test_apply_iris_publishes_real_position_while_auto_iris_active`,
  `test_apply_iris_detects_auto_iris_turned_off_via_query`,
  `test_apply_iris_normal_behavior_unaffected_when_auto_iris_off`). 319 Tests bestehen
  (vorher 315), keine Regression. **Weiterhin unveraendert offen (bewusst NICHT Teil
  dieses Fixes, Nutzerauftrag war nur die Anzeige-Korrektur):** Fader-Touch loest
  weiterhin kein automatisches `ORS:0` aus -- ein Fader-Zug bei aktivem Auto-Iris bleibt
  also weiterhin wirkungslos auf die Kamera, springt jetzt aber wenigstens sofort
  sichtbar auf die echte Position zurueck, statt optisch falsch stehen zu bleiben.
  **Nicht live gegen eine reale Kamera verifiziert** -- nur unittest-abgesichert
  (`FakeCameraDriver`), das reale `#AXI`-Ignorierverhalten selbst war zuvor bereits
  hardwareverifiziert (s. o.), aber der neue Korrektur-Codepfad (erneute `#GI`-Abfrage
  nach einem ignorierten `#AXI`) wurde nicht erneut an echter Hardware durchgespielt.
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
  (`OSJ:0F` bei AW-UE150/UE160/AW-UE100/AW-UE80/UE50/UE40/UE30, `OTP`/`QTP`
  bei AW-HE50/60/120/130/HR140/HE40/UE70/HE42, `OSG:4A` bei AK-UB300) --
  `set_pedestal()`/`step_pedestal()`/`_query_pedestal()` lesen Kommando und
  Kodierung jetzt aus dem Modell statt fest `OSJ:0F` zu senden. AK-UB300 hat
  bewusst KEINE Gain-Werte (strukturell anderes `OGS`-Schema, siehe
  `ak_ub300.py`). Modelle ohne Eintrag in einer der lokalen Referenz-PDFs
  (nur noch AW-UE145) haben bewusst weder Gain- noch Pedestal-Werte (kein
  erfundener Wert; AW-UE100 und AW-UE80/UE50/UE40/UE30 hatten hier
  ursprünglich auch dazugehört, siehe Korrekturen 2026-07-18 unten).
  `core/application.py._encoder_value_range()` ersetzt die frühere
  statische `_ENCODER_RANGES`-Konstante und liest den Bereich jetzt vom
  verbundenen Treiber. Getestet in `tests/test_panasonic.py` (u. a.
  `test_apply_model_catalog_resolves_gain_pedestal_for_*`,
  `test_set_pedestal_uses_otp_command_for_he50`,
  `test_step_gain_clamps_to_he50_range`) und `tests/test_panasonic_models.py`.
  ~~**Weiterhin offen:** die per-Tick-Schrittweite des Encoders (±1 Digit,
  ×5-Beschleunigung) berücksichtigt `GAIN_STEP_DB` noch nicht -- bei den
  3dB-Stufen-Modellen (AW-HE50/60/HE40/UE70/HE42) sendet ein einzelner Tick
  weiterhin ±1dB (bzw. ±5dB beschleunigt), nicht zwingend ein gültiges
  Vielfaches von 3. Verhalten der Kamera bei einem solchen Zwischenwert
  (z. B. `OGU:09`) ist nicht dokumentiert/verifiziert.~~ **Behoben
  (2026-07-18):** `apply_encoder_turn()` in `core/application.py`
  multipliziert das Tick-Delta bei `gain` zusätzlich mit
  `driver.gain_step_db` (Default 1, wenn unbekannt) -- ein Tick bewegt jetzt
  bei den 3dB-Modellen um 3dB, beschleunigt um 15dB (5 Schritte × 3dB), statt
  immer um 1dB/5dB. `pedestal` hat kein Schrittweiten-Feld und bleibt
  unverändert bei 1 pro Klick. Da `GAIN_MIN_DB`/`GAIN_MAX_DB` bei allen
  3dB-Modellen selbst Vielfache von 3 sind (HE50/60: 0–18, HE40/UE70/HE42:
  0–48), bleibt auch der geclampte Wert immer ein gültiges Vielfaches -- kein
  zusätzliches Snapping an den Rändern nötig. Getestet in
  `tests/test_application.py`
  (`test_apply_encoder_turn_respects_gain_step_db_for_3db_step_models`,
  `test_apply_encoder_turn_gain_step_combines_with_acceleration`,
  `test_apply_encoder_turn_pedestal_ignores_gain_step_db`). Volle Testsuite
  jetzt 214 Tests (vorher 211), keine Regression.
- ~~AW-UE100 wurde faelschlich als "in keiner der beiden PDFs dokumentiert"
  gefuehrt~~ **Korrigiert (2026-07-18):** ein drittes lokales Referenz-PDF
  (`docs/specs/AW-UE100_InterfaceSpecification_E.pdf`, dediziertes
  Modell-Dokument) wurde nachtraeglich ins Repo gelegt und war beim
  urspruenglichen Gain/Pedestal-Umbau (Eintrag oben) noch nicht bekannt.
  `drivers/panasonic_models/aw_ue100.py` hat jetzt echte Werte: Gain
  kontinuierlich 0-42dB (`OGU`, gleiche Ankerpunkte wie AW-HR140/AW-UE150A,
  aber unabhaengig aus der eigenen PDF verifiziert; Kamera deckelt auf 36dB
  wenn "Super Gain" aus ist -- diese Kopplung wird hier nicht durchgesetzt),
  Pedestal ueber `OSJ:0F`/`QSJ:0F` -200..+200 (identisch zu AW-UE150A/
  AW-UE160). "Super Gain" (`OSI:28`) bewusst NICHT als Button-Feature
  ergaenzt -- der Button-Katalog bleibt laut Projektkonvention allein aus
  `C:\smart_reset_work` portiert, nicht aus dieser PDF.
  Ausserdem dabei behoben: Button 1 (Encoder-Funktionsauswahl) wechselte bei
  Modellen ohne Gain-/Pedestal-Daten (damals u. a. faelschlich AW-UE100, nach
  wie vor z. B. AW-UE145) sichtbar auf GAIN/PEDESTAL, aber die Wertanzeige
  blieb stumm beim Camera-Status-Inhalt haengen (Bugreport). Neue Funktion
  `core/application.py._encoder_function_unsupported()` zeigt jetzt explizit
  "n/a" in Zeile 2, wenn die aktive Funktion vom verbundenen Modell gar nicht
  unterstuetzt wird -- unterschieden von "Wert nur gerade nicht bekannt"
  (Kamera nicht verbunden o. ae.), das weiterhin auf die bisherige Anzeige
  zurueckfaellt. Getestet in `tests/test_panasonic.py::
  test_apply_model_catalog_resolves_gain_pedestal_for_ue100` und
  `tests/test_panasonic_emulator.py::test_gain_and_pedestal_work_for_ue100`;
  live gegen `tools/panasonic_emulator.py` + `main.py` verifiziert (Button 1
  zeigte vor dem Fix "2 KAM"/"50%" statt "GAIN"/"n/a" bei AW-UE100, jetzt
  korrekt "GAIN"/"+0dB" da AW-UE100 nun unterstuetzt wird).
  **Zusaetzlich live gegen eine echte AW-UE100 verifiziert (2026-07-20,
  `192.168.0.11`):** `QID`→`OID:AW-UE100` bestaetigt das Modell; `QGU`→
  `OGU:80` (Data 0x80 = AGC-Ankerpunkt, Kamera steht aktuell auf Auto-Gain)
  bestaetigt erstmals an echter Hardware, dass der modell-uebergreifend
  angenommene AGC-Ankerpunkt (0x80) auch bei AW-UE100 gilt, nicht nur bei
  AW-UE160 (dort schon vorher per `QGU`→`OGU:08`=0dB verifiziert, siehe
  Offene Punkte); `QSJ:0F`→`OSJ:0F:800` bestaetigt den Pedestal-Center-Wert
  (`PEDESTAL_CENTER_DATA=0x800`) exakt wie in `aw_ue100.py` hinterlegt. Reine
  Lesebefehle, keine Aenderung an der Kamera vorgenommen.
- ~~AW-UE80/UE50/UE40/UE30 wurden faelschlich als "in keiner der Referenz-
  PDFs dokumentiert" gefuehrt~~ **Korrigiert (2026-07-18):** ein viertes
  lokales Referenz-PDF (`docs/specs/AW-UE80UE50UE40_InterfaceSpecification_
  E.pdf`, "applicable models" deckt laut eigener Angabe alle vier Modelle
  gemeinsam ab -- trotz Dateiname ohne "UE30") wurde nachtraeglich ins Repo
  gelegt. `drivers/panasonic_models/aw_ue80.py` hat jetzt echte Werte
  (identisch zu AW-UE100, aber eigenstaendig aus dieser PDF verifiziert):
  Gain kontinuierlich 0-42dB (`OGU`, gleiche 36dB/Super-Gain-Kopplung wie
  AW-UE100, nicht durchgesetzt), Pedestal ueber `OSJ:0F`/`QSJ:0F` -200..+200.
  `aw_ue30.py`/`aw_ue40.py`/`aw_ue50.py` re-exportieren diese Konstanten von
  `aw_ue80.py` (gleiches Muster wie `aw_he60.py`/`aw_he42.py`/`aw_ue70.py`
  fuer `aw_he50.py`/`aw_he40.py`). Getestet in
  `tests/test_panasonic.py::test_apply_model_catalog_resolves_gain_pedestal_
  for_ue80_and_aliases` und `tests/test_panasonic_emulator.py::
  test_gain_and_pedestal_work_for_ue80_and_aliases`.
- ~~AW-UE145 war die CAMERA_ID fuer das letzte "undokumentierte" Modell~~
  **Korrigiert (2026-07-18):** ein fuenftes lokales Referenz-PDF
  (`docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf`, dediziert fuer
  "AW-UE150/AW-HE145") wurde nachtraeglich ins Repo gelegt. Dessen "Model
  Number"-Tabelle zeigt die echten `QID`-Antworten `OID:AW-UE150` UND
  `OID:AW-HE145` fuer zwei im selben Dokument gefuehrte, aber unterschied-
  liche Modelle -- "AW-UE145" (die bisherige CAMERA_ID, aus dem Dateinamen
  der `smart_reset_work`-Quelle uebernommen) passte zu KEINEM der beiden
  echten QID-Strings. `drivers/panasonic_models/aw_ue145.py` wurde deshalb
  zu `aw_he145.py` umbenannt: CAMERA_ID ist jetzt "AW-HE145" (verifiziert),
  "AW-UE145" bleibt als Alias erhalten (Nutzerentscheid, statt eines
  komplett neuen separaten Modell-Eintrags). Button-Katalog unveraendert
  (weiterhin von `aw_ue150.py` re-exportiert). Gain/Pedestal aus diesem
  PDF: Gain -3..+42dB (Anker 05h/08h/32h) -- **widerspricht dabei dem
  aelteren Multi-Modell-PDF, das fuer AW-UE150 0..+42dB nennt**
  (Nutzerentscheid: neueres, dediziertes PDF gilt als massgeblich, daher
  wurde `aw_ue150.py`s GAIN_MIN_DB ebenfalls von 0 auf -3 korrigiert). Ein
  sechstes, noch neueres PDF (`docs/specs/AW-UE150A_InterfaceSpecification_
  E.pdf`, 2025, explizit nur fuer "AW-UE150A") wurde direkt danach ebenfalls
  gefunden und bestaetigt denselben -3..+42dB-Bereich (Anker 05h/08h/2Ch/32h)
  -- 2 von 3 Quellen stimmen jetzt ueberein, nur die aelteste (2020) weicht
  ab, was die Korrektur zusaetzlich untermauert. Pedestal `OSJ:0F`/-200..+200
  (identisch in allen drei Quellen, kein Widerspruch). Damit hat jetzt JEDES
  registrierte Modell Gain-Daten
  (ausser AK-UB300, strukturell) und Pedestal-Daten (auch AK-UB300, ueber
  OSG:4A) -- die `_encoder_function_unsupported()`/"n/a"-Anzeige (Eintrag
  oben) hat aktuell keinen Modell-Fall mehr, der sie auslöst (nur noch der
  generische "unbekanntes Modell"-Pfad). Getestet in
  `tests/test_panasonic_models.py::test_he145_resolves_gain_pedestal_from_
  dedicated_pdf`, `tests/test_panasonic.py::test_apply_model_catalog_
  resolves_gain_pedestal_for_he145_via_ue145_alias`,
  `tests/test_panasonic_emulator.py::test_gain_and_pedestal_work_for_he145_
  and_ue145_alias`.
- ~~Button-Kataloge (BUTTON_FEATURES) waren für alle Modelle außer AW-UE160
  nur gegen smart_reset_work verifiziert, nicht gegen die lokalen PDFs~~
  **Teilweise umgesetzt (2026-07-18, Nutzerauftrag):** `drs`/`knee` für alle
  Modelle mit vorhandener PDF gegen deren Kapitel 8/9 geprüft — dabei
  mehrere echte Fehler gefunden und korrigiert:
  - `drs` (`OSE:33`) war überall als einfacher Toggle geführt, ist aber ein
    Mehrwert-Cycle: 3 Werte (0=Off/1=Low/3=High, Data-Wert 2 nicht belegt)
    bei AW-HE50/HE60/HE40/UE70/HE42; 4 Werte (0=Off/1=Low/2=Mid/3=High) bei
    AW-HE120/HE130/HR140/AW-UE150A/AW-HE145/AW-UE100/AW-UE80/UE50/UE40/UE30.
    AK-UB300s `drs` bewusst NICHT angefasst (PDF nennt AK-UB300 in keiner
    der beiden DRS-Gruppen, weder Bestätigung noch Widerspruch).
  - `knee` (`OSA:2D`) ist laut §3.2.30 "Knee settings" explizit **"Only
    supported by the AW-HE130/AW-HR140/AW-UE150/AK-UB300"** — bei AW-HE120
    war er fälschlich vorhanden (jetzt entfernt), bei AW-HE130/AW-HR140/
    AK-UB300 als falscher Toggle statt 3-Werte-Cycle (0=OFF/1=MANUAL/2=AUTO)
    geführt (jetzt korrigiert). AW-UE100 ebenso (eigenes PDF, gleiche
    Kodierung). AW-UE150A/AW-HE145 hatten `knee` bereits korrekt als Cycle.
  - AW-UE80/UE50/UE40/UE30: Kap. 8 bestätigt "Knee mode OSA:2D" existiert,
    aber die Werte-/Label-Tabelle ließ sich aus dieser PDF nicht sauber
    extrahieren — bewusst NICHT ergänzt (kein erfundener Wert), bleibt
    offener Punkt.
  - AW-UE160 gegengecheckt (eigene PDF, `OSA:0D`): dort tatsächlich ein
    echter 0/1-Toggle, keine Korrektur nötig.
  Emulator (`tools/panasonic_emulator.py`) brauchte keine Änderung — er
  liest `BUTTON_FEATURES` bereits vollständig dynamisch aus dem
  aufgelösten Modell-Modul. Live gegen Emulator verifiziert (HE50 lehnt
  `OSE:33:2` ab, HE120 lehnt jedes `OSA:2D`-Kommando ab, UE100 akzeptiert
  `OSA:2D:2`). **Hinweis:** das hier beschriebene "cycle"-Feature (Druck
  schaltet rundenweise durch alle Werte) wurde noch am selben Tag durch
  Toggle-pro-Zielzustand ersetzt, siehe nächster Punkt — die Test-Namen in
  diesem Punkt sind daher historisch, nicht mehr im Code vorhanden.
  ~~**Weiterhin offen:** der Rest des Katalogs (`auto_focus`, `auto_iris`,
  `awb_black`, `aww_white`, `osd`, `white_clip`, `matrix`, `gamma`, `flare`,
  `linear_matrix`, `adaptive_matrix`, `night_mode`, `super_gain` u. Ä.) ist
  weiterhin nur gegen smart_reset_work verifiziert, nicht gegen die PDFs;
  ebenso die genauen Knee-Werte für AW-UE80/UE50/UE40/UE30.~~ **Teilweise
  fortgesetzt (2026-07-18, Nutzerauftrag "mit Punkt 2 weitermachen"):**
  `auto_focus` (`OAF`/`QAF`, 0=Manual/1=Auto), `auto_iris` (`ORS`/`QRS`,
  0=Manual/1=Auto -- Query laeuft weiterhin ueber die separate, bereits
  verifizierte `#GI`-Abfrage, nicht `QRS`), `awb_black`/`aww_white`
  (`OAS`/`OWS`) und `osd` (`DUS`/`QUS`) sind jetzt direkt gegen
  `HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.1/3.2.9/3.2.22
  geprueft -- alle korrekt, keine Aenderung noetig. Dabei zwei echte Fehler
  gefunden und korrigiert:
  - **`white_clip`** (`OSA:2E`) war bei AW-HE50/AW-HE60/AW-HE40/AW-UE70/
    AW-HE42/AW-HE120/AK-UB300 fälschlich vorhanden -- §3.2.31 "White Clip
    settings" nennt explizit nur **"AW-HE130/AW-HR140/AW-UE150"** als
    unterstützt. Bei diesen sieben Modellen komplett entfernt (dieselbe Art
    Fehler wie zuvor bei `knee`/AW-HE120, aus smart_reset_work uebernommen,
    dort nie gegen diese PDF geprueft). AW-UE100/AW-UE150A/AW-HE145/
    AW-UE160/AW-UE80-Gruppe behalten es -- eigene, dedizierte PDFs
    dokumentieren es dort unabhaengig und ohne Modell-Einschraenkung.
  - **`night_mode`** (nur AW-HE40/AW-HE42/AW-UE70) nutzte faelschlich
    `OSI:1A`/`QSI:1A` -- laut PDF gehoert das zu einer CROP-Marker-
    Farbauswahl fuer AK-UB300/AW-UE150, nicht zu Night Mode. Das echte
    Kommando steht in §3.2.27 "Night mode settings": `OSD:B2`/`QSD:B2`
    (0=Manual/1=Auto), Modellzuordnung war schon korrekt. Korrigiert.
  Getestet in `tests/test_panasonic_models.py`
  (`test_white_clip_absent_where_not_supported_per_pdf`,
  `test_white_clip_present_where_supported_per_pdf`,
  `test_night_mode_uses_correct_command_not_crop_marker_command`),
  `tests/test_panasonic_emulator.py`
  (`test_white_clip_rejected_for_models_without_pdf_support`,
  `test_night_mode_uses_osd_b2_not_osi_1a`). 219 Tests bestehen (vorher 214).
  **Weiterhin offen (in dieser Runde geprüft, aber nicht abschließend
  klärbar):** `matrix`/`gamma`/`flare`/`linear_matrix` (AW-UE160-exklusiv,
  `OSA:84`/`OSA:0A`/`OSA:11`/`OSL:6C`) -- die betreffende PDF-Seite (dichte
  Menü-Baum-Tabelle rund um Gain/Matrix/Gamma/Flare) liefert bei
  `pdftotext` in JEDEM Extraktionsmodus (Standard/`-layout`/`-table`/`-raw`)
  in sich widersprüchliche Zuordnungen (z. B. `OSA:11` mal als "RGB GAIN
  ACH/BCH", mal als "FLARE", `OSJ:D7` mal als "FLARE", mal als "GAMMA MODE
  SELECT") -- zu unzuverlässig fuer eine Korrektur oder Bestätigung ohne
  visuelle PDF-Ansicht (`pdftoppm`/Poppler ist auf dieser Maschine nicht
  installiert, daher kein Seiten-Rendering moeglich). Bleibt bei den
  bisherigen, nur ueber die Query-Existenz (nicht die Modell-/
  Wert-Korrektheit) geprüften Werten -- naechster Schritt fuer eine
  kuenftige Session: `pdftoppm`/Poppler installieren (oder die PDF-Seite
  anderweitig visuell pruefen) und Kap. 3.2.6 ff. der
  `HDIntegratedCamera_InterfaceSpecifications-E.pdf` (Seiten ~69-75 laut
  aktueller Extraktion) manuell gegenlesen.
  **Teilweise verifiziert (2026-07-20, reale AW-UE160 `192.168.0.10`):**
  `QSA:11`/`QSA:0A`/`QSL:6C`/`QSA:84` (flare/gamma/linear_matrix/matrix)
  sowie `QSA:2D`/`QSA:0D` (knee/drs) liefern alle gueltige `O...:[Wert]`-
  Antworten ohne Fehlercode (`OSA:11:1`, `OSA:0A:1`, `OSL:6C:0`, `OSA:84:0`,
  `OSA:2D:2`, `OSA:0D:0`) -- bestaetigt also erstmals gegen echte Hardware
  (vorher nur Emulator/PDF), dass diese Query-Kommandos auf einer echten
  AW-UE160 existieren und beantwortet werden. **Loest die eigentliche
  Ambiguitaet NICHT:** ob `OSA:11` semantisch wirklich "Flare" ist (statt
  z. B. "RGB Gain ACH/BCH", siehe widerspruechliche PDF-Extraktion oben)
  bleibt offen, da das nur durch visuellen Abgleich mit dem Kamera-eigenen
  OSD-Menu waehrend eines Toggles zu klaeren ist, nicht durch die reine
  Query-Antwort.
  `super_gain` (AK-UB300, `OSI:28`) weiterhin ohne Query -- jetzt genauer
  begründet: Kommando steht strukturell im AK-UB300-exklusiven
  Bereichs-Gain-Block (`OSA:50/51/52`/`OSA:60`), hat aber selbst keine
  eigene "Only supported by AK-UB300"-Kennzeichnung, und dieselbe PDF-Stelle
  ist ebenfalls spaltenverschoben (widersprüchliche Testextraktion). `drs`
  bei AK-UB300 weiterhin unbestätigt (unverändert). Knee-Werte für
  AW-UE80/UE50/UE40/UE30 weiterhin nicht extrahierbar (unverändert).
  `adaptive_matrix` (AW-HE145/AW-UE150A) in dieser Runde nicht erneut
  geprüft, Stand von vorher unverändert übernommen.
- ~~Cycle-Features (Knee, DRS) auf Button 2/3 waren rundenweise durchschalt-
  bar, aber ihr aktueller Zustand war nirgends ablesbar (Bugreport
  2026-07-18: Button-Text zeigt nur den statischen Feature-Namen, `is-on`
  ist bei einem Cycle-Index nur binär truthy/falsy, unterscheidet nicht
  zwischen z. B. "Manual" und "Auto")~~ **Umgesetzt (Nutzerentscheid
  2026-07-18):** kein `"kind":"cycle"`-Feature-Typ mehr auf Button 2/3 —
  jeder sinnvolle Zielzustand bekommt stattdessen einen eigenen, normalen
  Toggle-Eintrag (`knee_manual`/`knee_auto` statt `knee`; `drs_low`/
  `drs_mid`/`drs_high` statt `drs`). Grund: Button 2/3 haben nur eine
  einzelne, nicht mehrfarbige LED und können echt nur an/aus zeigen, kein
  rundenweises Durchschalten sinnvoll darstellen — das Cycle-Konzept bleibt
  exklusiv bei Button 1 (Encoder-Funktionsauswahl, komplett getrennter
  Mechanismus). `drivers/panasonic_aw.py::trigger_button_feature()`
  akzeptiert seither für "on"/"off" auch eine Liste von Kommandos (nicht
  nur einen String) — AW-UE160s Knee braucht z. B. zwei Kommandos je
  Zielzustand (`["OSL:45:1", "OSA:2D:2"]` für Auto). `cycle_button_feature()`
  (Treiber) sowie der `"cycle"`-Zweig in `core/application.py::
  apply_button_action()` wurden komplett entfernt (kein Feature nutzt sie
  mehr). Betroffen: alle Modelle mit `drs`/`knee` im Katalog (praktisch
  jedes AW-Modell) -- AK-UB300s `drs` blieb unberührt, da nie als Cycle
  gefuehrt (weiterhin ein einfacher Toggle). AW-UE80/UE50/UE40/UE30 haben
  weiterhin kein `knee_*` (unveränderter offener Punkt, siehe oben). Getestet in
  `tests/test_panasonic_models.py` (`test_drs_is_three_value_toggles_for_
  he_low_tier_group`, `test_drs_is_four_value_toggles_for_higher_tier_
  group`, `test_knee_absent_from_he120_not_supported_per_pdf`,
  `test_knee_is_toggle_pair_where_supported`,
  `test_ue160_knee_toggle_uses_command_list_for_on_side`),
  `tests/test_panasonic.py` (`test_trigger_button_feature_toggle_on_sends_
  command_list`), `tests/test_panasonic_emulator.py`
  (`test_button_feature_toggle_with_command_list_accepts_every_command`) --
  dabei einen echten Bug im Emulator gefunden und behoben: `_model_button_
  commands()` versuchte `set.add()` auf eine Liste (TypeError) fuer
  Toggle-Kommandos mit Listen-"on"/"off", jetzt behoben.
- ~~Button-2/3-Funktion konnte nur auf der Setup-Seite zugewiesen werden --
  Bugreport 2026-07-18: kein Weg, auf der Übersicht-Seite direkt eine
  Funktion zu waehlen, ohne die Seite zu wechseln~~ **Umgesetzt (Nutzer-
  auftrag 2026-07-18, ueber einen Zahnrad-Prototyp iterativ entstanden):**
  Zahnrad-Icon (⚙) neben Button 2/3 auf der Übersicht-Seite oeffnet ein
  Popover mit dem echten, dynamischen Funktionskatalog des verbundenen
  Kameramodells (`GET /api/channels/{i}/available-buttons`, neue Route,
  liest `available_button_features()` -- bisher nur von der Setup-Seite
  serverseitig gerendert). Auswahl ruft denselben
  `POST /api/channels/{i}/buttons/{slot}` wie die Setup-Seite auf, keine
  zweite Zuweisungs-Logik.
  **Zusaetzlich (Nutzerauftrag):** `assign_channel_button()` fragt bei
  verbundener Kamera sofort den Ist-Zustand des neu zugewiesenen Toggle-
  Features ab (`PanasonicAWDriver.query_button_feature()`, neu), damit der
  Button in der Web-UI sofort korrekt beleuchtet/unbeleuchtet erscheint,
  statt erst nach dem ersten Druck einen (dann nur lokal geratenen)
  Zustand zu haben. Dafuer wurden ALLE Kommandos des aktuellen Button-
  Katalogs gegen die lokalen PDFs auf ein Query-Gegenstueck geprueft
  (Nutzerauftrag "mit den vorhandenen PDFs verifizieren, bei Unklarheiten
  fragen") -- Ergebnis: `query`/`query_on_value` jetzt bei praktisch jedem
  Toggle gesetzt (`auto_focus`→`QAF`, `osd`→`QUS` [Antwort als `OUS:
  [Data]`, einziger Fall mit abweichendem Antwort-Praefix], `white_clip`→
  `QSA:2E`, `drs*`→`QSE:33` bzw. AW-UE160 `QSA:0D`, `knee_manual`/
  `knee_auto`→`QSA:2D`, AW-UE160-exklusiv `flare`→`QSA:11`, `gamma`→
  `QSA:0A`, `linear_matrix`→`QSL:6C`, `matrix`→`QSA:84`, `adaptive_matrix`
  [AW-UE150A/AW-HE145]→`QSJ:4F`, `night_mode` [AW-HE40-Gruppe]→`QSI:1A`).
  **Bewusst OHNE Query gelassen** (Nutzerentscheid, kein erfundener Wert):
  AW-UE160s `knee_manual`/`knee_auto` (Zustand haengt an zwei Kommandos,
  `OSL:45` + `OSA:2D` -- ob `OSA:2D` seinen Wert behaelt, wenn `OSL:45`
  auf 0 steht, ist nicht dokumentiert) sowie AK-UB300s `super_gain`
  (`QSI:28` ist bei anderen Modellen belegt, AK-UB300 selbst kommt aber in
  keiner PDF vor) und `drs` (schon vorher unbestaetigt, siehe oben).
  `trigger_button_feature()` akzeptiert seit dieser Arbeit fuer "on"/"off"
  auch eine Liste von Kommandos (nicht nur einen String) -- unveraendert
  fuer alle bestehenden Ein-Kommando-Toggles, nur fuer AW-UE160s Knee
  genutzt (siehe oben, frueherer Punkt).
  Emulator (`tools/panasonic_emulator.py`) erweitert: `_model_query_
  command_map()` leitet aus `feature["query"]` eine Kontroll-Praefix->
  Query-Kommando-Zuordnung ab und beantwortet Query-Kommandos jetzt mit
  dem zuletzt gesetzten Rohwert (Default "0", der in jedem Modell
  durchgaengige Grundzustand) -- Response-Praefix ist immer "O" + Query-
  Kommando ohne das fuehrende "Q" (bestaetigtes Muster ueber alle PDFs,
  einzige Ausnahme `QUS`→`OUS` folgt demselben Muster trotz
  abweichendem Control-Praefix `DUS`).
  Getestet in `tests/test_panasonic.py` (`test_query_button_feature_*`),
  `tests/test_application.py` (`test_assign_channel_button_queries_state_
  when_camera_connected` u. a.), `tests/test_web_app.py`
  (`test_available_channel_buttons_endpoint_*`,
  `test_assign_channel_button_endpoint_persists_and_queries_state`),
  `tests/test_panasonic_emulator.py` (`test_toggle_feature_query_*`).
  203 Tests bestehen (vorher 187).
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
- ~~MIDI-Buttons Solo/Mute/Select sind Rx-seitig verifiziert (siehe oben), aber nicht mit
  Kamera-Feature-Aktionen bzw. Companion-SELECT verdrahtet. Rec ist verdrahtet, aber nur
  für die Encoder-Funktionsauswahl (`cycle_encoder_function`) — dafür ist Rec laut Spec §9
  auch vorgesehen, nicht für `apply_button_action`/Companion-SELECT.~~ **Umgesetzt
  (Nutzerauftrag 2026-07-18):** `midi/fader.py` mapt Note 8–15 (Solo) auf
  `apply_button_action(..., "button2")` und Note 16–23 (Mute) auf `"button3"` — exakt
  dieselbe bereits fertige/getestete Anwendungslogik, die auch der Web-UI-Button-Klick
  (`POST /api/channels/{i}/buttons/{slot}/trigger`) auslöst. Note 24–31 (Select) mapt auf
  `trigger_companion_select()`; `CompanionError` wird hier (anders als in der Web-Route)
  nur geloggt statt weitergeworfen, damit ein Verbindungsfehler den MIDI-Poll-Loop nicht
  abbricht. LED-Tx (neu, Nutzerentscheid: rein binär OFF=Licht aus/ON=Licht an, kein
  Blinken) für Solo/Mute läuft über `_refresh_button_leds()`, ausgelöst durch dieselben
  Events wie der bestehende Scribble-Strip-Vollabzug (`feature_changed`/`config_changed`/
  `connection_changed`) — kein neues Event nötig, da `apply_button_action()`/
  `assign_channel_button()` bereits publizieren. Zustand kommt aus derselben
  `_channel_button_snapshot()`-Quelle wie die `is-on`-Klasse der Web-UI. Select hat
  bewusst keine LED-Ansteuerung — SELECT ist laut `trigger_companion_select()`-Docstring
  eine einmalige Aktion ohne Dauerzustand, es gibt nichts anzuzeigen. LED-Farben (Rec/Mute
  rot, Solo gelb, Select grün, je Tastentyp hardwarefest, nicht per MIDI wählbar) laut
  `github.com/Aldaviva/BehringerXTouchExtender` (Extender-spezifische Community-Referenz,
  bereits als Quelle für Device-ID 0x15 genutzt) — **keine** offizielle Behringer-Doku und
  nicht gegen reale Hardware verifiziert; ändert nichts an der Velocity-0/127-Ansteuerung.
  Ohne Zuweisung eines Feature-Keys auf Button 2/3 bleibt Solo/Mute wie beim physischen
  Knopf ohne Funktion ein No-Op (kein Kamerabefehl, LED aus).
  **Verifiziert:** neue `tests/test_fader.py` (8 Tests, gefakter Output-Port statt echtem
  MIDI-Port) deckt die Notenbereich→Kanal/Slot-Zuordnung und die LED-Velocity-Logik ab
  (Solo-Press → `apply_button_action`/LED an, zweiter Press → LED aus, Mute ohne Zuordnung
  → No-Op, Note-Release wird ignoriert, ungemapptes Kanal 8 → kein Crash, Select-Press →
  `trigger_companion_select` mit korrektem Page/Row/Column, `CompanionError` wird geloggt
  statt den Poll-Loop zu crashen, unbekannter Feature-Zustand zeigt LED aus). Volle
  Testsuite jetzt 211 Tests (vorher 203), keine Regression.
  ~~**Nicht verifiziert:** LED-Tx (Note-On/Off zurück ans Gerät) sowie die Note-Rx-Bereiche
  für Solo/Mute/Select auf Kanal 2–8 wurden noch nicht gegen die reale Hardware getestet —
  nur Kanal 1 Rx ist bisher hardwareverifiziert (siehe oben), Tx für keinen der vier
  Tastentypen bisher überhaupt.~~ **Rx für Kanal 2–8 seither vollständig verifiziert**
  (s. o., 2026-07-20). **LED-Tx für Solo teilverifiziert (2026-07-20, echtes Gerät,
  Kanal 1, `auto_focus` auf Button 2):** erster Druck schaltete Kamera-`auto_focus`
  echt von `OAF:0` auf `OAF:1` und die Solo-LED ging an; zweiter Druck schaltete zurück
  auf `OAF:0` und die LED ging aus — beide Richtungen live gegen die Kamera
  gegengeprüft (nicht nur LED beobachtet, auch `QAF` direkt abgefragt), binäres
  Verhalten (kein Blinken) wie dokumentiert. Mute/Select-LED sowie LED-Tx auf Kanal
  2–8 weiterhin nicht getestet.
- ~~Hotplug/Reconnect für den MIDI-Port (Spec §5.5) nicht implementiert~~ **Teilweise
  behoben (2026-07-22, Bugreport: "nach ca. 1h Inaktivität reagieren weder Web-UI noch
  physisches Gerät mehr wie gewohnt"):** Root Cause per Live-Traceback des Nutzers
  bestätigt (`_rtmidi.SystemError: MidiOutWinMM::sendMessage: error sending MIDI
  message.`) und per Code-Lesen verifiziert (nicht nur vermutet) — `midi/fader.py` rief
  `self._out_port.send(...)` an fünf Stellen ohne jede Fehlerbehandlung auf, und
  `core/bus.py::EventBus.publish()` fängt ebenfalls nichts ab (`for callback in
  subscribers: await callback(payload)`, keine Isolation). Da Web-UI-Aktionen
  (`apply_iris()`/`apply_button_action()` in `core/application.py`) über denselben
  EventBus dieselben MIDI-Tx-Subscriber (`_on_iris_changed`/
  `_on_scribble_relevant_event`) auslösen wie physische Tastendrücke, riss ein einzelner
  fehlgeschlagener Send sowohl den `_poll_loop()`-Hintergrund-Task dauerhaft ab (kein
  Supervisor/Neustart — physisches Gerät danach komplett tot) als auch jeden
  Web-Request, der einen dieser Events publiziert (Exception propagiert bis in den
  FastAPI-Handler). Deckt sich mit dem Fehlen jeglicher ERROR-Zeile im
  `/logs`-Ringpuffer: die Exception lief als "Task exception was never retrieved" über
  den `asyncio`-Root-Logger, nicht über den vom Ringpuffer abgehörten
  `ptz_control`-Logger. Neue zentrale `XTouchFader._send()`-Methode (ersetzt alle
  direkten `self._out_port.send(...)`-Aufrufe) fängt `rtmidi.RtMidiError` (gemeinsame
  Basisklasse aller `_rtmidi`-Fehlertypen inkl. `SystemError`, per `.__mro__` verifiziert)
  ab, versucht einmalig `_reconnect_output()` (`mido.open_output()` auf denselben
  Portnamen) und wiederholt den Send; schlägt auch das fehl, wird geloggt und verworfen
  statt weitergereicht. Getestet in `tests/test_fader.py`
  (`test_send_reconnects_and_retries_after_transient_rtmidi_error`,
  `test_send_swallows_error_when_reconnect_also_fails`,
  `test_button_action_does_not_raise_when_midi_send_fails` — letzterer reproduziert den
  eigentlichen Bugreport: `apply_button_action()` darf trotz kaputtem MIDI-Ausgang nicht
  abbrechen). 270 Tests bestehen (vorher 267), keine Regression. **Bewusst NICHT
  Teil dieses Fixes** (Nutzerentscheid: Scope war "Fix + Reconnect-Versuch bei
  Send-Fehler", nicht die volle Hotplug-Spec): ~~die Rx-Seite (`_poll_loop()`s
  `self._in_port.iter_pending()`) hat weiterhin keine eigene Fehlerbehandlung/
  Reconnect-Logik — ein direkter Fehler beim Lesen (statt beim Senden) würde den
  Poll-Loop nach wie vor dauerhaft abreißen. Das ist ein anderer, bisher nicht
  beobachteter/bestätigter Fehlerpfad, kein Teil dieses Bugreports.~~ **Der Fehlerpfad
  wurde am 2026-07-23 tatsaechlich beobachtet und behoben, siehe eigener Eintrag weiter
  unten ("Button 1 liess sich nach einem Fader-Zug bei aktivem Auto-Iris nicht mehr
  umschalten") -- `_poll_loop()` faengt Ausnahmen einzelner Handler jetzt ab, statt sich
  von ihnen mitreissen zu lassen. **Nicht verifiziert:**
  ob Windows-USB-Energieverwaltung tatsächlich der externe Auslöser für den fehlgeschlagenen
  Send ist (plausibelste Erklärung, aber nicht am Gerät nachgestellt) und ob der Fix live
  gegen das reale Gerät nach einer echten Inaktivitätsphase greift (nur unittest-verifiziert,
  mit `FailingOutPort`/gemocktem `mido.open_output`).
- ~~Web-UI-Port-Auswahl für MIDI (Setup-Seite) ist weiterhin ein statisches Mockup, nicht mit
  echten `mido`-Ports verbunden — Port kommt aktuell nur aus `config.yaml`~~ **Nutzerentscheid
  2026-07-23: nicht umgesetzt, Mockup entfernt statt ausgebaut.** Eine volle Implementierung
  (echte `mido`-Port-Enumeration, Live-Reconnect ohne App-Neustart) wurde durchgeplant, aber
  verworfen — PTZ_Control ist ein Ein-Geräte-Tool (nur der X-Touch Extender), der reale
  Anwendungsfall ("Portname hat sich geändert") ist bereits durch `config.yaml`-Bearbeitung +
  Neustart (seit dem Startup-Geschwindigkeits-Fix weiter oben schnell) abgedeckt, und es besteht
  kein Bedarf, den X-Touch waehrend einer laufenden Session zu wechseln — faellt er aus, laeuft
  die Software per Web-UI trotzdem weiter. Da das Panel (Port-Dropdown mit zwei fest
  einprogrammierten Fake-Optionen, unwirksame "Resync Surface"/"Reconnect"-Buttons) ohne
  Umsetzung nur vortäuschte, etwas zu tun, wurde es aus `web/templates/setup.html` entfernt statt
  als Mockup stehen zu bleiben (die umschließende `grid-2`-Section wurde dabei zu `panel` auf dem
  verbleibenden Companion-Config-Panel vereinfacht, damit keine leere zweite Spalte übrig bleibt).
  Keine JS-/Backend-Aenderung noetig (war nie verdrahtet). Spec §5.5 ("Port-Handling",
  insbesondere die dort beschriebene automatische Hotplug-Erkennung/-Reconnect) bleibt damit
  ebenfalls unimplementiert -- weiterhin ein offener Punkt, falls sich der Anwendungsfall
  (z. B. Mehrgeräte-Betrieb oder Live-Wechsel während einer Show) künftig doch ergibt.
- ~~Update-Notifications für andere Ereignisse als Iris (`OAW`, `OWS` etc., Spec §7.3.1) laufen
  technisch über denselben neuen Notification-Kanal, werden aber nicht ausgewertet
  (`PanasonicAWDriver._handle_notification` reagiert nur auf `lPI`)~~ **Umgesetzt (2026-07-19,
  Nutzerauftrag nach Beleg durch `RemoteControllerInterfaceSpecifications-E.pdf` §4/Fig. 4-5,
  die auf Kap. 4 "Camera information update notification" der
  `HDIntegratedCamera_InterfaceSpecifications-E.pdf` verweist):** Kap. 4 dieser PDF bestätigt,
  dass der bereits registrierte Update-Notification-Kanal (`/cgi-bin/event?connect=start`, siehe
  `start_lens_feedback()`) JEDE Kommandoänderung meldet — im selben `Command:Value`-Format wie
  die CGI-Antwort (z. B. `OGU:08`) — unabhängig davon, ob sie von PTZ_Control selbst oder einem
  anderen Terminal (z. B. Kamera-eigenes Web-UI) ausgelöst wurde (Fig. 4-5). Ausnahmen laut
  Kap. 4.3.1 (keine Notification): OSD-Menü-Navigation, Pan/Tilt/Zoom/Focus/Iris-Kommandos,
  `OSE:69`/`OSD:48`/`ORV` — ~~betrifft keinen der ausgewerteten Katalog-Einträge~~ **live
  widerlegt (2026-07-20, siehe unten):** betrifft sehr wohl `auto_focus`/`auto_iris`.
  `PanasonicAWDriver._handle_notification()` gleicht die Payload jetzt zusätzlich zu `lPI` gegen
  drei weitere Fälle ab (kein neues Parsing nötig, da der Payload-String bereits bekannten
  Kommandos entspricht): Toggle-Features aus `BUTTON_FEATURES` (`_match_toggle_feature()`,
  exakter String-Abgleich gegen `on`/`off`), Gain (`OGU:[Data]`, geteilte Dekodierung
  `_decode_gain_data()` mit `_query_gain_db()`) und Pedestal (`self.pedestal_command:[Data]`,
  geteilte Dekodierung `_decode_pedestal_data()` mit `_query_pedestal()`). Neue Callback-Typen
  `feature_changed`/`gain_changed`/`pedestal_changed` werden in `core/application.py
  ._wire_camera_events()` auf gleichnamige EventBus-Topics gebrückt (aktualisieren
  `cam_state.feature_states`/`gain_db`/`pedestal`) — beide Topics sind in
  `_subscribe_snapshot_broadcast()` (WS-Broadcast) sowie in `midi/fader.py`s
  `_on_scribble_relevant_event`-Abonnements (Scribble-Strip- und Button-LED-Vollabzug) ergänzt.
  Getestet in `tests/test_panasonic.py` (u. a. `test_handle_notification_fires_feature_changed_
  for_single_command_toggle`, `test_handle_notification_fires_feature_changed_for_command_list_
  toggle`, `test_handle_notification_fires_gain_changed`, `test_handle_notification_gain_agc_
  fires_no_callback`, `test_handle_notification_fires_pedestal_changed`,
  `test_handle_notification_pedestal_ignored_for_model_without_pedestal_command`) und
  `tests/test_application.py` (`test_driver_feature_changed_event_updates_state_and_publishes`,
  `test_driver_gain_changed_event_updates_state_and_publishes`,
  `test_driver_pedestal_changed_event_updates_state_and_publishes`). Volle Testsuite jetzt 236
  Tests (vorher 225), keine Regression. ~~**Nicht verifiziert:** live gegen eine reale Kamera (nur
  gegen die synthetischen Notification-Frames in den Unit-Tests)~~ **Teilweise live verifiziert,
  mit negativem Ergebnis (2026-07-20, Nutzerauftrag, echte AW-UE160 `192.168.0.10`):**
  `auto_focus` (`OAF`) und `auto_iris` (`ORS`) wurden per CGI direkt umgeschaltet (Kamera-eigene
  UI bestätigte den neuen Wert), aber weder Solo- noch Mute-LED (beide auf Kanal 1 auf diese
  Features gemappt) reagierten — die Kamera sendet für diese beiden Kommandos KEINE Notification,
  deckungsgleich mit der "Focus/Iris"-Ausnahme aus Kap. 4.3.1 (s. o., dort ebenfalls korrigiert).
  Betroffene Features bekommen einen aktuellen Wert nur noch beim expliziten Query (Zuweisung
  über die Web-UI, App-Neustart/Reconnect), nie push-basiert bei externer Änderung. Ob andere
  Katalog-Einträge (weiter unten getestet: white_clip, drs, knee, matrix/gamma/flare/
  linear_matrix, night_mode — siehe eigene Einträge) von derselben Ausnahme betroffen sind, ist
  NICHT einzeln geprüft — nur auto_focus/auto_iris wurden hier live getestet. Noch unverifiziert:
  ob die Kamera bei Mehrfach-Kommando-Toggles (z. B. AW-UE160 Knee, zwei Kommandos pro
  Zielzustand) für die NICHT ausgenommenen Kommandos tatsächlich je eine separate Notification
  pro Kommando sendet, wie angenommen.
- ~~Setup-Seite zeigte den Companion-Button als "Saved"/`is-connected` rein anhand von
  `companion.host` (Config-Vorhandensein) -- Bugreport 2026-07-18: Button zeigte "Saved"
  auch dann, wenn Companion beim App-Start gar nicht lief~~ **Behoben (2026-07-18):** neues
  `AppState.companion_connected`-Flag (Default `False`), das eine echte `is_reachable()`-
  Pruefung widerspiegelt statt nur `companion.host`-Truthiness. Zwei Stellen setzen es:
  `web/app.py` lifespan prueft beim App-Start (analog zum bestehenden Kamera-Connect-Block
  direkt darueber), und `configure_companion()` (`core/application.py`, neuer optionaler
  `connected`-Parameter, Default `False`) wird von der `POST /api/companion/config`-Route mit
  dem Ergebnis der dort ohnehin schon vorhandenen `is_reachable()`-Pruefung aufgerufen.
  `web/templates/setup.html` nutzt jetzt `companion_connected` statt `companion.host` für
  Klasse/Label des Save-Buttons. Wie beim Kamera-`connected`-Flag keine kontinuierliche
  Hintergrundpruefung -- der Zustand wird nur beim App-Start und bei explizitem Speichern neu
  ermittelt, nicht laufend nachgehalten. Getestet in `tests/test_application.py`
  (`test_configure_companion_defaults_to_not_connected`,
  `test_configure_companion_sets_connected_when_caller_confirmed_reachability`),
  `tests/test_web_app.py` (`test_companion_config_endpoint_marks_connected_when_reachable`,
  `test_companion_config_endpoint_rejects_unreachable_and_stays_disconnected`,
  `test_companion_disconnect_clears_connected_flag`,
  `test_setup_page_does_not_show_saved_when_companion_configured_but_unreachable_at_startup`).
  225 Tests bestehen (vorher 219). Zusaetzlich live gegen die laufende App verifiziert: mit
  `companion.host: localhost, port: 8888` in `config.yaml` und keinem Listener auf 8888 zeigte
  `GET /setup` nach Neustart `<button ... class="" data-companion-save>Save</button>` und der
  Log die neue Warnung `Companion (localhost:8888) nicht erreichbar`; nach Start eines
  Test-Listeners auf 8888 und erneutem Speichern über `POST /api/companion/config` zeigte die
  Seite korrekt `class="is-connected"` / `Saved`.
- ~~`web/templates/logs.html` (Spec §10 Punkt 4: "Log-Ansicht: letzte 200 Zeilen, Filter nach
  Level") war ein reines Mockup mit fest einprogrammierten Beispielzeilen, ohne Verbindung zu
  echten Log-Ausgaben~~ **Umgesetzt (2026-07-19):** neues `core/log_buffer.py` mit
  `RingBufferHandler` (`logging.Handler`, `deque(maxlen=200)`) haengt sich beim Modul-Import an
  den `ptz_control`-Elternlogger (erfasst damit alle `ptz_control.*`-Logger im Projekt) und
  haelt dessen letzte 200 Eintraege (Zeit/Level/Message) im Speicher vor -- unabhaengig davon,
  ob die App ueber `main.py` oder direkt als `web.app.app` (Tests) laeuft. `GET /logs`
  (`web/app.py`) akzeptiert jetzt `?level=`, filtert serverseitig auf diesen Level und
  schwerwiegendere (Standard-Logging-Semantik, `ALL` zeigt alles; unbekannter Wert faellt auf
  `ALL` zurueck) und rendert die echten Eintraege statt der bisherigen Festwerte.
  `web/static/app.js` (`initLogLevelFilter()`) laedt die Seite bei Level-Auswahl mit dem neuen
  Query-Parameter neu (kein AJAX, konsistent mit dem bisher rein serverseitig gerenderten
  Charakter dieser Seite). Wie bei `log_level` in `config.yaml` filtert die Level-Auswahl nur,
  was der jeweilige Logger ueberhaupt durchlaesst (effektiver Logger-Level, i. d. R. durch
  `main.py`s `logging.basicConfig(level=config.global_.log_level)` gesetzt) -- die Ansicht kann
  keine Eintraege unterhalb dieses konfigurierten Levels zeigen, selbst wenn `DEBUG` im Filter
  ausgewaehlt ist. Getestet in `tests/test_web_app.py`
  (`test_logs_page_shows_captured_log_entries`, `test_logs_page_filters_by_level`,
  `test_logs_page_unknown_level_falls_back_to_all`); zusaetzlich per TestClient-Skript live
  gegen echte Startup-/Test-Log-Zeilen verifiziert (INFO-Startzeile + WARNING erschienen bei
  `ALL`, ERROR-Filter zeigte korrekt "Keine Log-Eintraege" ohne vorhandene ERROR-Zeile). 239
  Tests bestehen (vorher 236), keine Regression. **Nicht Teil dieser Aenderung:** "Ein Logfile
  pro Session" (Spec §2, Begruendungsspalte) -- es gibt weiterhin keine Datei-basierte
  Persistenz, nur den In-Memory-Ringpuffer; dafuer existiert kein Config-Feld fuer einen
  Dateipfad (weder in Spec §4 noch im bisherigen Code), daher hier bewusst nicht erfunden.
- **System-Tray-Icon beim App-Start (Nutzerauftrag 2026-07-19):** `main.py` 1:1 nach dem
  bereits umgesetzten Vorbild in `C:\smart_reset_work\web_main.py` portiert (siehe Spec §11
  für die volle Beschreibung) -- Mutex-Singleton-Check, uvicorn im Hintergrund-Thread statt
  blockierend, automatisches Öffnen des Standardbrowsers, `pystray`-Icon
  (`Images/Icon.ico`) im Hauptthread mit „Open" (Linksklick/Default) und „Quit"
  (Rechtsklick-Menü, stoppt Server + `os._exit(0)`), Windows-11-Rechtsklick-Patch aus dem
  Vorbild übernommen. Neue Abhängigkeiten `pystray>=0.19.0`/`Pillow>=11.0.0` in
  `requirements.txt`/`pyproject.toml` ergänzt und im `.venv` installiert (`pystray==0.19.5`,
  `Pillow==12.3.0`). **Verifiziert:** Icon lädt via PIL (`Images/Icon.ico`, 64×64 PNG-in-ICO),
  Live-Start gegen die echte `config.yaml` (5 konfigurierte Kameras, MIDI-Port
  „X-Touch-Ext") -- Web-UI unter `127.0.0.1:8600` erreichbar (`GET /` → 200), Companion-/
  MIDI-Warnungen liefen wie erwartet ins Log statt den Start abzubrechen, `webbrowser.open()`
  öffnete nachweislich einen neuen Chrome-Prozess (Prozessliste: zwei neue `chrome`-Prozesse
  direkt nach dem `python`-Start), kein Absturz/keine Tray-Fehler-MessageBox während der
  Laufzeit. Mutex-Kollisionslogik isoliert verifiziert (`CreateMutexW` mit demselben Namen
  während die echte Instanz lief lieferte `GetLastError() == 183`
  `ERROR_ALREADY_EXISTS`, exakt der Pfad, der die "läuft bereits"-Meldung auslöst) --
  ein echter zweiter Prozessstart wurde bewusst NICHT ausgelöst, da `MessageBoxW` dabei
  einen blockierenden Dialog auf dem Desktop der Nutzerin/des Nutzers öffnet. Prozess danach
  sauber gestoppt (Port 8600 wieder frei). **Nicht verifiziert:** das per-Klick-Verhalten des
  Tray-Icons selbst (Open/Quit-Menüeintrag tatsächlich anklicken) sowie der Windows-11-
  Rechtsklick-Patch -- beides erfordert eine echte Nutzerinteraktion mit dem sichtbaren
  Tray-Icon, nicht headless prüfbar.
- **App-Anzeigename „X-Touch PTZ Control" (Nutzerauftrag 2026-07-20):** rein
  kosmetische Umbenennung aller nutzerseitig sichtbaren Strings von „PTZ
  Control“ auf „X-Touch PTZ Control“ — Fenstertitel und `<h1>` in
  `web/templates/base.html`, FastAPI-`title` in `web/app.py`, Tray-Tooltip/
  Menü/MessageBoxen und Log-Zeilen in `main.py`, `pyproject.toml`s
  `description`, README-Überschrift, Spec-Titel (Zeile 1, vorher „PTZ
  Shading Tool (Arbeitstitel)"). Bewusst **unverändert** gelassen (interne,
  nicht sichtbare Bezeichner, kein Teil der UI): Verzeichnisname
  `PTZ_Control`, Python-Paketname `ptz-control` in `pyproject.toml`,
  Logger-Name `ptz_control`, Mutex-Name `PTZControlApp_SingleInstance`,
  interne pystray-Icon-ID `"ptz-control"`. Keine Funktionsänderung, daher
  keine neuen Tests — verifiziert per Grep, dass außerhalb der genannten
  internen Bezeichner keine „PTZ Control"-Vorkommen mehr übrig sind.
- **Rec-LED an nur bei verbundener Kamera, Select-LED zeigt zuletzt
  gedrückten Kanal nur bei verbundener Kamera + Companion (Nutzerauftrag
  2026-07-20):** `midi/fader.py::_refresh_button_leds()` erweitert (bisher
  nur Solo/Mute) — Rec (Note 0–7) sendet bei jedem Vollabzug `velocity=127`
  NUR für Kanäle mit `ch["connected"] == True` (kein Feature-Zustand, reine
  Verbindungsabfrage; Begründung des Nutzers: Rec hat keine On/Off-Logik,
  wählt nur die über den Encoder einstellbare Funktion, ohne Kamera gibt es
  nichts zu wählen). Select (Note 24–31) leuchtet nur, wenn zusätzlich zu
  `ch["connected"]` auch `AppState.companion_connected` gesetzt ist, und dann
  exakt auf dem Kanal, dessen Select zuletzt gedrückt wurde
  (`XTouchFader._last_select_channel`, reiner Instanzzustand der Klasse,
  nicht Teil von `AppState` — betrifft nur die LED-Anzeige,
  `trigger_companion_select()` bleibt unverändert eine einmalige Aktion ohne
  Dauerzustand). Der LED-Vollabzug läuft weiterhin über dieselben Events
  (`connection_changed`/`feature_changed`/`config_changed`/`gain_changed`/
  `pedestal_changed`) sowie zusätzlich direkt nach jedem Select-Druck.
  Getestet in `tests/test_fader.py`
  (`test_rec_led_only_on_for_channel_with_connected_camera`,
  `test_select_led_off_when_companion_not_connected`,
  `test_select_led_requires_connected_camera_on_that_channel`,
  `test_select_led_lights_only_last_pressed_channel_when_companion_connected`).
  243 Tests bestehen (vorher 239), keine Regression. **Live gegen die reale
  Hardware verifiziert (2026-07-20, AW-UE160 `192.168.0.10` + X-Touch,
  vor der Verbindungs-Einschränkung):** Rec leuchtete dauerhaft, Select blieb
  bei nicht erreichbarem Companion (`localhost:8888`) unbeleuchtet — beides
  vom Nutzer am Gerät bestätigt. Die anschließende Verbindungs-Einschränkung
  (nur bei `ch["connected"]`) selbst ist bisher nur über die Tests
  abgesichert, noch nicht erneut live nachgeprüft.
- **Externe Änderungen von `auto_focus`/`auto_iris` werden nicht live erkannt
  (live bestätigt 2026-07-20, siehe oben "Generische Update-Notification-
  Auswertung"):** die Kamera sendet für `OAF`/`ORS` keine Update-Notification
  (Kap. 4.3.1 "Focus/Iris" ausgenommen) — Solo-/Mute-LED und
  `cam_state.feature_states`/`auto_iris` bleiben deshalb auf dem zuletzt
  bekannten Stand, bis das jeweilige Feature das nächste Mal explizit
  abgefragt wird (Zuweisung über die Web-UI, Reconnect). **Noch keine
  Lösung entschieden/umgesetzt** — Optionen wären z. B. periodisches Polling
  (`QAF`/`QRS`) für Kanäle mit einem dieser beiden Features auf Button 2/3,
  oder das bewusste Akzeptieren dieser Einschränkung (Auto-Focus/Auto-Iris
  sind vermutlich seltene Umschaltungen im laufenden Betrieb). Rückfrage beim
  Nutzer nötig, bevor hier etwas gebaut wird.
- ~~Select-Taste am X-Touch wirkte nach längerer Inaktivität nur beim zweiten
  Klick (Bugreport 2026-07-20)~~ **Behoben:** `core/companion.py::
  press_button()` retried jetzt einmal automatisch bei einem
  `httpx.HTTPError` auf den ersten Versuch — Ursache war die gepoolte
  Keep-Alive-Verbindung aus `build_client()` (`keepalive_expiry=3600`), die
  Companion serverseitig vermutlich schon vorher schließt; der Client merkt
  das erst beim nächsten Schreibversuch. Ein zweiter Versuch mit derselben
  `client`-Instanz baut automatisch eine frische Verbindung auf (httpx/
  httpcore entfernt die tote Verbindung aus dem Pool). Getestet in
  `tests/test_companion.py`
  (`test_press_button_retries_once_on_stale_connection_and_succeeds`,
  `test_press_button_raises_after_two_failed_attempts` — genau ein Retry,
  kein Retry-Loop). 245 Tests bestehen (vorher 243), keine Regression.
  **Nicht live gegen die reale Hardware/Companion-Instanz nachverifiziert**
  — der Fix ist nur unittest-abgesichert (`httpx.MockTransport`), das
  eigentliche Nutzer-Symptom (Klick nach Inaktivität) lässt sich ohne
  kontrolliertes Warten auf den echten Companion-Server-Timeout nicht direkt
  reproduzieren.
- **Gain "Auto" als dritter Encoder-Zustand + Super-Gain-Kopplung
  (Nutzerauftrag 2026-07-20, live gegen AW-UE160 UND AW-UE100 verifiziert):**
  `OGU:80` (Data=0x80, bisher als "AGC/nicht lesbar" behandelt) ist jetzt ein
  regulärer dritter Gain-Zustand am unteren Rand — Herunterdrehen unter
  `gain_min_db` wechselt in Auto (Sequenz `+2, +1, 0, Auto`), Hochdrehen aus
  Auto verlässt es auf `gain_min_db` (Sequenz `Auto, 0, +1, +2`), weiteres
  Herunterdrehen während Auto ist ein No-Op. Live an BEIDEN Kameras
  bestätigt: `OGU:80` wurde ohne Fehler angenommen, Kamera-UI zeigte danach
  "Gain Auto" (vorher fälschlich angenommen, UE160 hätte das nicht — live
  widerlegt). Neues `CameraState.gain_auto`-Feld (`None`=unbekannt,
  `True`=Auto, `False`=manueller Wert gültig) ergänzt `gain_db`, da `None`
  bisher fuer beides ueberladen war. `drivers/panasonic_aw.py::step_gain()`
  gibt jetzt `tuple[int | None, bool]` zurück (ABC-Signatur in
  `drivers/base.py` angepasst), `_decode_gain_data()` ebenso.
  Update-Notifications für `OGU` feuern jetzt auch bei einer externen
  Umschaltung auf Auto (vorher stillschweigend ignoriert, siehe
  `test_handle_notification_gain_agc_fires_gain_changed_with_auto_flag`).
  **Bugfix waehrend der Live-Tests gefunden:** kraeftiges Hochdrehen aus
  Auto liess den Wert wegen der bestehenden Tick-Beschleunigung (Spec §9,
  ×5 bei >3 Klicks/100ms) auf +42 statt auf einen erwarteten Wert schnellen.
  **Erste Fassung** liess dafuer ein neues `AppState.
  gain_auto_exit_suppress_until`-Feld den Rest derselben Drehbewegung
  verwerfen (garantierte Landung exakt bei `gain_min_db`) -- **beim
  Live-Test wieder verworfen (Nutzerentscheid 2026-07-20):** fuehlte sich
  beim Weiterdrehen direkt nach dem Ausstieg falsch an (jede weitere
  Drehung wurde innerhalb des Zeitfensters verworfen, eine Pause war
  noetig). **Stattdessen jetzt:** `PanasonicAWDriver.step_gain()` behandelt
  Auto beim Ausstieg als virtuelle Position "eine Stufe unter
  `gain_min_db`" und landet proportional bei `gain_min_db + (delta_db-1)`,
  geclampt auf `effective_gain_max_db` -- ein einzelner Tick landet weiter
  exakt bei `gain_min_db`, ein kraeftiger/schneller Dreh-Burst darf
  (genau wie bei jedem anderen Gain-Wert) proportional weiter nach oben
  laufen, nur eben korrekt geclampt. Das urspruengliche "+42"-Symptom war
  in Wahrheit ueberwiegend auf die beiden folgenden Bugs zurueckzufuehren,
  nicht auf fehlendes Verwerfen der Drehbewegung. **Erster echter Bug:**
  ein von der Kamera abgelehnter Wert
  (`ER3`) liess das "pending"-Delta unveraendert stehen, wodurch die naechste
  Vorschau (`encoder_preview()`) einen nie tatsaechlich erreichten Wert
  zeigen konnte (Ursache der zunaechst faelschlich beobachteten "+42"-Anzeige
  bei der AW-UE100) — wird jetzt bei jedem `CameraCommandError` auf 0
  zurueckgesetzt. **Super-Gain-Kopplung (live an der AW-UE100 entdeckt):**
  `GAIN_MAX_DB=42` in `aw_ue100.py`/`aw_ue80.py`(+UE30/40/50)/`aw_ue150.py`/
  `aw_he145.py` gilt nur, wenn Super Gain (`OSI:28`) an ist -- bei AUS (Live-
  Zustand der Test-UE100) liegt die echte Obergrenze bei 36dB, Werte darueber
  wurden per `ER3` abgelehnt. Neue Konstanten `GAIN_MAX_DB_SUPER_GAIN_OFF`/
  `SUPER_GAIN_QUERY_COMMAND` je Modell, `PanasonicAWDriver.
  effective_gain_max_db` liefert die tatsaechlich nutzbare Grenze (36 statt
  42, solange Super Gain nicht als "an" bestaetigt ist -- unbekannter Zustand
  wird konservativ als "aus" behandelt); der Cache (`gain_super_gain_on`)
  wird bei jedem `get_state()`-Aufruf aufgefrischt (Connect UND
  Encoder-Funktionswechsel auf "gain", kein eigenes Wiring noetig). Dabei
  einen echten Dokumentationsfehler in `aw_he145.py` korrigiert: dort stand
  faelschlich "0..36dB/-3..42dB" (aus dem UE100-Muster kopiert, ohne die
  eigene PDF direkt zu pruefen) -- die tatsaechliche PDF-Tabelle
  (`AW-UE150HE145_InterfaceSpecification_E.pdf`) zeigt "-3..36dB/-3..42dB",
  nur die Obergrenze aendert sich. AW-UE160 hat laut seiner PDF KEINE
  Super-Gain-Kopplung (keine Erwaehnung), bleibt unveraendert. Getestet in
  `tests/test_application.py` (u. a.
  `test_apply_encoder_turn_gain_auto_turn_up_exits_to_gain_min_db`,
  `test_apply_encoder_turn_gain_auto_exit_continues_proportionally_like_normal_turning`,
  `test_apply_encoder_turn_rejected_gain_value_clears_stale_pending_delta`),
  `tests/test_panasonic.py` (u. a.
  `test_step_gain_turning_up_while_agc_active_exits_to_gain_min_db`,
  `test_step_gain_turning_up_strongly_while_agc_active_lands_proportionally`,
  `test_effective_gain_max_db_defaults_to_narrower_value_until_super_gain_confirmed_on`,
  `test_step_gain_clamps_to_36db_when_super_gain_off`),
  `tests/test_panasonic_models.py`
  (`test_super_gain_coupling_present_for_documented_models`). 258 Tests
  bestehen (vorher 245), keine Regression. **Live verifiziert (2026-07-20,
  AW-UE100 `192.168.0.11`):** kräftiges Hochdrehen aus Auto landete beim
  ersten Durchlauf korrekt (Anzeige laut Nutzer "korrekt"), danach aber der
  Wunsch geäußert, dass Weiterdrehen direkt danach normal/proportional
  wirken soll statt durch die Burst-Suppression blockiert zu werden — siehe
  Revision oben. Die revidierte Fassung selbst ist noch nicht erneut live
  nachgeprüft.
- ~~Motorfader blieb beim Trennen einer Kamera (Setup-Seite) auf der zuletzt
  bekannten Position stehen~~ **Behoben (2026-07-20):**
  `core/application.py::disconnect_camera()` setzt `cam_state.iris` jetzt
  auf `0.0` zurück (Web-UI-Slider folgt darüber automatisch dem normalen
  Snapshot-Broadcast); `midi/fader.py` abonniert dafür neu
  `connection_changed` (`_on_connection_changed()`, zusätzlich zum
  bestehenden `_on_scribble_relevant_event()` auf demselben Topic) und fährt
  den physischen Motorfader auf diesen Wert — dieselbe Methode fährt beim
  (Re-)Connect auch auf den echten Kamerawert, ohne den Unterschied selbst
  kennen zu müssen (liest nur `cam_state.iris`, das `connect_camera()`
  bereits vorher über `get_state()` aktualisiert hat). `apply_iris()` prüft
  bereits `driver.connected` und verwirft Fader-Bewegungen einer getrennten
  Kamera komplett (kein Kamerabefehl, keine Zustandsänderung) — dieser Teil
  der Anforderung war schon vorher erfüllt, nur der Motor selbst reagierte
  nicht. Getestet in `tests/test_application.py`
  (`test_disconnect_camera_resets_iris_to_zero`), `tests/test_fader.py`
  (`test_disconnecting_camera_drives_motor_fader_to_zero`). 260 Tests
  bestehen (vorher 258), keine Regression. Noch nicht live gegen die reale
  Hardware verifiziert.
- ~~Web-UI-Fader sprang beim Ziehen mit der Maus manchmal unkontrolliert auf
  100%~~ **Behoben (2026-07-20), live über Log-Korrelation diagnostiziert:**
  `web/static/app.js::initFaderDrag()` behandelte `pointercancel`
  (Interaktionsabbruch, z. B. Fokuswechsel/OS-Unterbrechung) bisher genauso
  wie `pointerup` — beide riefen `valueFromEvent(evt)` auf, um daraus den
  finalen Wert zu berechnen. `pointercancel` liefert laut Pointer-Events-Spec
  aber KEINE verlässliche Zeigerposition; die (unzuverlässigen) Koordinaten
  wurden trotzdem als „final“-Wert interpretiert und gesendet — reale
  Live-Reproduktion zeigte im Server-Log einen harten Sprung von `#AXIBB3`
  (~60%) direkt auf `#AXIFFF` (exakt 100%, kein Zwischenschritt), passend zu
  genau diesem Mechanismus. Jetzt: `pointerup` behält die bisherige Logik
  (Koordinaten sind bei einem echten Release verlässlich), `pointercancel`
  verwirft die eigene Position und sendet stattdessen den zuletzt aus
  `pointerdown`/`pointermove` bekannten Wert (`lastValue`) als final. Rein
  clientseitig (kein Server-Neustart nötig, nur Hard-Refresh der Seite) —
  kein Python-Test möglich (kein JS-Test-Setup im Projekt), Ursache aber
  über echte Server-Log-Korrelation (nicht nur Code-Lesen) bestätigt.
  **Dabei zusätzlich entdeckt, noch NICHT behoben:** `connectSurfaceSocket()`s
  Reconnect-Pfad (`ws.addEventListener("close", () => setTimeout(
  connectSurfaceSocket, 2000))`) erzeugt ein neues WebSocket-Objekt, ohne es
  an `initFaderDrag()`/`initEncoderKnob()` (die den alten `ws` behalten)
  weiterzureichen — nach einem WS-Reconnect würden Fader-Drag und
  Encoder-Knopf im Browser dadurch bis zum nächsten Seiten-Reload
  stillschweigend nichts mehr senden (`ws.readyState !== OPEN` in `send()`
  bleibt nach dem Reconnect dauerhaft wahr). Nicht Teil dieses Bugreports,
  daher hier nur dokumentiert, nicht angefasst.
- **`#LPC1`/`#LPC0` (Lens-Info-Push) ist kamera-weit, nicht pro Verbindung
  (live entdeckt, 2026-07-20):** Bugreport des Nutzers ("externe
  Iris-Änderungen an der UE160 werden nicht erkannt, an der UE100 schon")
  hatte KEINE Modellursache — `config.yaml` hat `cam1` UND `cam4` beide auf
  dieselbe physische Kamera (`192.168.0.10`) registriert (bereits früher in
  dieser Session als Risiko geflaggt, aber zunächst nicht behoben). Ein
  Test während dieser Session (Trennen von `cam4` über die Setup-Seite, für
  den Fader-Disconnect-Fix weiter oben) sendete `#LPC0` an die physische
  Kamera — das schaltete den Lens-Info-Push-Kanal für die GESAMTE Kamera ab,
  also auch für `cam1`, obwohl `cam1` nie getrennt wurde. Live verifiziert:
  erneutes `#LPC1` per CGI direkt an die Kamera stellte den Iris-Feedback
  für `cam1` sofort wieder her, ohne dass am Code etwas geändert wurde.
  AW-UE100 (`cam2`, `192.168.0.11`) war nur deshalb nie betroffen, weil kein
  zweiter Kanal auf dieselbe Kamera zeigt. **Kein Code-Fix vorgenommen**
  (Nutzerentscheid): die Dopplung ist eine Config-Fehlkonfiguration, kein
  vom Code unterstütztes Setup (zwei unabhängige `CameraDriver`-Instanzen,
  die sich denselben physischen Zustand — Lens-Feedback, Gain, Pedestal
  usw. — teilen, ohne voneinander zu wissen) — der Nutzer korrigiert das
  über die Setup-Seite (`cam4` auf eine andere Kamera oder keine
  umstellen), statt dass PTZ_Control versucht, geteilte Kamera-Hosts über
  mehrere Kanäle hinweg zu erkennen/koordinieren.
- **Doppelte IP über die Setup-Seite jetzt verboten (Nutzerauftrag
  2026-07-20, direkte Folge des vorigen Punkts):**
  `core/application.py::register_camera()` lehnt eine IP ab, die bereits
  einem ANDEREN Kanal zugeordnet ist (Vergleich rein über `host`, Port
  bewusst ignoriert — dieselbe physische Kamera hört ohnehin nur auf einem
  Port) — derselbe Host für DENSELBEN Kanal (erneutes Connect/Update) bleibt
  erlaubt. Fehlermeldung `"Camera is already connected, please select
  another camera"` (Nutzervorgabe, Grammatik/Rechtschreibung geprüft, keine
  Änderung nötig). `web/static/app.js::initCameraConnectButtons()` zeigt
  diese Meldung jetzt als echtes `alert()`-Popup (vorher nur stumm im
  Button-Text versteckt) und stellt den ursprünglichen Button-Text danach
  wieder her. Rein clientseitig für die Anzeige, serverseitig für die
  eigentliche Validierung — kein neues Popover/Modal-System eingeführt
  (keines vorhanden, `alert()` ist die minimal-invasive Wahl für "Popup").
  **Dabei einen echten, vorbestehenden Test-Isolations-Bug in
  `tests/test_web_app.py` gefunden und behoben:** die dortige `client`-
  Fixture gab bisher dasselbe Modul-Level-`TEST_CONFIG`-Objekt ungekopiert
  an jeden Test weiter — `register_camera()` mutiert `state.config.cameras`
  aber direkt, wodurch z. B. in einem Test registrierte Kameras
  stillschweigend in spätere, unabhängige Tests durchsickerten (erst durch
  den neuen Duplikat-Test aufgefallen: ein früherer Test hatte bereits eine
  zweite Kamera hinterlassen). Jetzt `TEST_CONFIG.model_copy(deep=True)` pro
  Test. Getestet in `tests/test_application.py`
  (`test_register_camera_rejects_duplicate_ip_on_another_channel`,
  `test_register_camera_same_host_on_same_channel_is_allowed`),
  `tests/test_web_app.py`
  (`test_register_camera_endpoint_duplicate_ip_returns_400_with_popup_message`).
  263 Tests bestehen (vorher 260), keine Regression. Noch nicht live gegen
  die echte Setup-Seite verifiziert.
- ~~Externe Gain-/Pedestal-Änderungen (Kamera-eigenes Web-UI) werden nicht
  erkannt~~ **Behoben (2026-07-20), Root Cause per eigenständigem Roh-TCP-
  Probe (nicht nur Code-Lesen) gefunden:** die Kamera sendet für `OGU`/
  `OSJ:0F` (und offenbar auch die PAINT-Menü-Variante `OSL:25`)
  Notifications korrekt — anders als bei den `lPI`/`lPC1`-Frames hat der
  Payload hier aber Null-Byte-Padding NACH dem schließenden `\r\n`
  (`b'\r\nOGU:0D\r\n\x00\x00\x00'`, live mitgeschnitten). Null-Bytes zählen
  in Python nicht als Whitespace, `str.strip()` (ohne Argument) ließ sie
  deshalb stehen — `int(value, 16)` in `_handle_notification()` warf dadurch
  eine `ValueError`, die `gain_changed`/`pedestal_changed` stillschweigend
  nie feuern ließ (fing die Exception ab, aber `gain_auto`/`pedestal` blieb
  `None`, siehe dortige Bedingung). `_parse_notification_payload()` nutzt
  jetzt `strip("\x00\r\n \t")` statt `strip()`. **Wichtig für künftige
  Sessions:** `tests/test_panasonic.py::_build_notification_frame()` baute
  bisher "zu saubere" synthetische Frames ohne `\r\n`/Padding — deshalb
  hatte KEIN existierender Unit-Test diesen Bug gefangen, obwohl die
  Notification-Logik selbst schon lange getestet war. Der Helfer kapselt
  den Payload jetzt genauso wie echte Frames (`\r\n<Kommando>\r\n` + 3
  Null-Bytes), plus ein dediziertes Echtdaten-Fixture
  (`_REAL_OGU_GAIN_NOTIFICATION_FRAME`, per eigenem TCP-Probe-Skript gegen
  die reale AW-UE160 mitgeschnitten). Getestet in `tests/test_panasonic.py`
  (`test_parse_notification_payload_strips_trailing_null_padding`,
  `test_handle_notification_fires_gain_changed_from_real_camera_capture`).
  265 Tests bestehen (vorher 263), keine Regression. **Live gegen die
  laufende App verifiziert (2026-07-20):** nach Neustart mit dem Fix
  externe Gain-Änderung (`OGU:0D`, +5dB) UND Pedestal-Änderung
  (`OSJ:0F:832`, +50) jeweils per CGI direkt an der echten AW-UE160
  gesetzt — Kanal 1 zeigte beide Werte korrekt und ohne manuellen Dreh am
  Encoder an.
- **`config.yaml` sammelte getrennte Kameras dauerhaft an -- "Disconnect"
  entfernt die Registrierung jetzt komplett (Nutzerauftrag 2026-07-20):**
  `core/application.py::disconnect_camera()` entfernte bisher nur die
  Laufzeitverbindung, die Kamera blieb in `config.yaml` + Bank-Kanal-
  Zuordnung stehen -- jedes je verbundene Kamera-Setup sammelte sich so
  unbegrenzt an, ohne Weg, das aufzuräumen (Nutzerfrage: "wie kann ich
  config.yaml zurücksetzen"). Jetzt entfernt Disconnect zusätzlich den
  `CameraConfig`-Eintrag, setzt den Bank-Kanal auf `null` und ruft
  `MappingEngine.unset_channel()` (neu) auf, danach `save_config()` --
  ein erneutes "Connect Camera" braucht wieder Name/IP/Port. Reihenfolge
  bewusst: der bestehende "Fader auf 0 fahren"-Vollabzug (`connection_
  changed`, siehe oben) läuft ZUERST, während die Kanal-Zuordnung noch
  existiert, DANACH erst wird die Zuordnung entfernt und `config_changed`
  published, damit Scribble-Strips/Web-UI den Kanal als komplett unbelegt
  ("----") statt nur "NC" (zugewiesen, aber getrennt) zeigen. Nutzerentscheid,
  keine separate "Remove"-Aktion -- Disconnect und Entfernen sind jetzt
  ein und dieselbe Aktion, kein Reconnect ohne erneute Eingabe möglich.
  **Dabei denselben Test-Isolations-Bug wie zuvor bei `tests/test_web_app.py`
  auch in `tests/test_application.py`s `_build_state()` gefunden und
  behoben** (geteiltes `TEST_CONFIG` ohne Kopie, jetzt `model_copy(deep=True)`
  per Test außer bei explizit übergebener Config). Getestet in
  `tests/test_application.py`
  (`test_disconnect_camera_removes_registration_from_config`,
  `test_disconnect_camera_persists_removal_to_config_file`),
  `tests/test_web_app.py` (angepasster
  `test_disconnect_camera_endpoint_marks_disconnected`). 267 Tests bestehen
  (vorher 265), keine Regression. Noch nicht live gegen die echte
  Setup-Seite verifiziert.
- **ND-Filter als 4. Encoder-Funktion auf Button 1 (Nutzerauftrag
  2026-07-22, "Cam Info, Gain, Pedestal und ND"):** Reihenfolge laut
  Nutzerentscheid `gain → pedestal → nd → camera_status` (`core/
  application.py._ENCODER_FUNCTIONS`), Anschlag statt Wraparound am Rand
  der Werteliste, nicht unterstützte Modelle zeigen "n/a" im Zyklus (kein
  Überspringen). Kommando `OFT`/`QFT` selbst ist modellübergreifend
  identisch, die gültigen Data-Werte wurden aber aus den lokalen Referenz-
  PDFs modellabhängig neu erhoben (`HDIntegratedCamera_
  InterfaceSpecifications-E.pdf` §3.2.1.4, für Modelle mit eigenem PDF
  zusätzlich dort verifiziert) -- neue Konstante `ND_FILTER_OPTIONS`
  (geordnete `(Data, Label)`-Liste statt reinem Zahlenbereich) je
  Modell-Datei, aufgelöst in `PanasonicAWDriver.nd_options` über
  `_apply_model_catalog()`. Dabei drei bisher unbekannte, teils
  überraschende Befunde:
  - **AW-HE130/AW-HR140** haben NUR die Data-Werte 0/3/4 (Through/1/64/
    1/8) -- 1 und 2 existieren für diese Gruppe laut PDF nicht, anders als
    beim bisher angenommenen durchgängigen 0-3-Bereich.
  - **AW-UE70/AW-HE42** haben einen fünften Wert, 8=Auto ND, den keine
    andere Modellgruppe hat.
  - **AW-HE40/AW-HE50/AW-HE60 haben gar keinen physischen ND-Filter** --
    die PDF-Menü-Tabelle für AW-HE40/UE70/HE42 annotiert `OFT` explizit
    "*only AW-UE70/AW-HE42", die separate HE50/HE60-Tabelle führt `OFT`
    überhaupt nicht auf. `aw_he42.py`/`aw_ue70.py` haben deshalb eine
    eigene, lokale `ND_FILTER_OPTIONS`-Konstante statt sie (wie den Rest
    ihres Katalogs) von `aw_he40.py` zu re-exportieren.
  **Dabei einen echten, bisher unbemerkten Bug in `PanasonicAWDriver.
  cycle_nd()` gefunden und behoben:** die Methode rechnete hartkodiert
  `(current + 1) % 4`, unabhängig vom verbundenen Modell -- für AW-HE130/
  AW-HR140 hätte das ungültige Zwischenwerte (Data 1/2) erzeugt, für
  Modelle ganz ohne ND-Filter einen sinnlosen Befehl gesendet. War bisher
  folgenlos, weil `cycle_nd()`/das zugehörige `config.yaml`-Feld
  `channel_defaults.buttons.mute.action: nd_cycle` (Spec §9-Tabelle)
  **nirgends aus der Anwendungsschicht aufgerufen wird** -- weder
  `nd_cycle` noch die anderen dort gelisteten Aktionen (`awb_trigger`,
  `gain_step`, `bars_toggle`, `auto_iris_toggle`, `preset_recall`) sind
  bisher verdrahtet, das ist ein separates, hier nicht angefasstes Thema.
  `set_nd()` validiert seit dieser Änderung gegen `nd_options` statt einen
  festen `0-3`-Bereich anzunehmen; `cycle_nd()` wrapt jetzt korrekt durch
  die tatsächliche Modell-Liste (mit Wraparound, für den weiterhin nicht
  verdrahteten Mute-Anwendungsfall) -- die neue Encoder-Funktion selbst
  nutzt bewusst eine eigene, nicht-wrappende Listenpositions-Logik in
  `apply_encoder_turn()` (Anschlag statt Wrap, Nutzerentscheid). Anzeige
  (`channel_display_text()`/Scribble-Strip) zeigt bei `nd` das Label
  (z. B. "1/64", "AUTO ND") statt eines Zahlenwerts -- alle Labels passen
  ins 7-Zeichen-Limit. Getestet in `tests/test_panasonic_models.py` (6 neue
  Tests für die Modell-Gruppen), `tests/test_panasonic.py` (`set_nd`/
  `cycle_nd`-Validierung, inkl. Regressionstest für den Sparse-Wrap-Bug),
  `tests/test_application.py` (Zyklus-Reihenfolge, Anschlag beidseitig,
  Sparse-Liste, abgelehnter Wert, "n/a" für Modelle ohne ND-Filter,
  gespeichert-Flag, Label-Anzeige). 291 Tests bestehen (vorher 269), keine
  Regression. **Teilweise live verifiziert (2026-07-22, reale AW-UE160):**
  der Encoder-Button/Dreh-Pfad selbst (Rx/Tx zur Kamera) funktioniert am
  echten Gerät. **Weiterhin nicht verifiziert:** ob AW-HE130/AW-HR140
  tatsächlich Data 1/2 ablehnen (nur aus der PDF übernommen, wie bei allen
  anderen rein PDF-basierten Werten in diesem Katalog) -- keine dieser
  beiden Kameras stand für einen Live-Test zur Verfügung.
- **ND-Notification fehlte komplett -- externe ND-Änderung (z. B. am
  Kamera-eigenen Bedienfeld) wurde nicht erkannt (Bugreport 2026-07-22,
  reale AW-UE160, direkte Folge des vorigen Punkts):**
  `PanasonicAWDriver._handle_notification()` wertete `OGU`/Pedestal/Toggle-
  Features bereits generisch aus (§7.3.1/Kap. 4 der HD Integrated Camera
  Interface Specifications), hatte aber schlicht KEINEN Zweig für `OFT`
  (ND-Filter) -- ein entsprechender Notification-Frame kam an, wurde aber
  von keinem der vorhandenen `if body.startswith(...)`-Zweige erfasst und
  lief ins Leere. `OFT` steht dabei NICHT in der Ausnahmeliste aus Kap.
  4.3.1 (nur OSD-Menü-Navigation, Pan/Tilt/Zoom/Focus/Iris, One-Touch-Focus,
  Contrast, Iris Volume sind dort ausgenommen) -- die Kamera sendet die
  Notification also durchaus, das Fehlen war ein reiner Implementierungs-
  Lücke, keine Kamera-Einschränkung (anders als bei `auto_focus`/
  `auto_iris`, siehe weiter oben). Neuer Zweig parst `OFT:[Data]` (Data ist
  hier ein einfacher Dezimalwert, kein Hex-String wie bei OGU/Pedestal) und
  feuert einen neuen `nd_changed`-Callback-Typ, gebrückt in
  `core/application.py::_wire_camera_events()` auf ein gleichnamiges
  EventBus-Topic (aktualisiert `cam_state.nd_index`) -- ergänzt in
  `_subscribe_snapshot_broadcast()` (WS-Broadcast) sowie in
  `midi/fader.py`s `_on_scribble_relevant_event`-Abonnements (Scribble-
  Strip-Vollabzug), analog zu `gain_changed`/`pedestal_changed`. Getestet
  in `tests/test_panasonic.py`
  (`test_handle_notification_fires_nd_changed`,
  `test_handle_notification_nd_changed_ignores_malformed_value`),
  `tests/test_application.py`
  (`test_driver_nd_changed_event_updates_state_and_publishes`). 294 Tests
  bestehen (vorher 291), keine Regression. **Live verifiziert (2026-07-22,
  reale AW-UE160):** Nutzer bestätigt, ND-Änderung am Kamera-eigenen
  Bedienfeld wird jetzt erkannt.
- **Browser öffnete sich vor Server-Bereitschaft, Start dauerte spürbar
  lange (Bugreport 2026-07-22):** zwei getrennte, aber zusammenhängende
  Fixes:
  1. `main.py::_open_browser()` wartete bisher fest `time.sleep(1.2)` vor
     `webbrowser.open()`, unabhängig davon, wie lange der Server tatsächlich
     zum Starten braucht -- ersetzt durch Polling auf `uvicorn.Server.
     started` (wird von uvicorn erst gesetzt, NACHDEM sowohl der
     FastAPI-Lifespan-Startup als auch das Socket-Binding abgeschlossen
     sind -- per `inspect.getsource(uvicorn.Server.startup)` verifiziert,
     nicht nur angenommen), mit `_BROWSER_OPEN_TIMEOUT=30s` als
     Sicherheitsnetz, falls der Server nie startet (z. B. Port belegt) --
     der Browser öffnet sich dann wie bisher trotzdem.
  2. Root Cause der eigentlichen Verzögerung: `web/app.py`s Lifespan
     verband bisher JEDE konfigurierte Kamera sequenziell (`for camera_id in
     state.drivers: await connect_camera(...)`) -- jede nicht erreichbare
     Kamera braucht aber bis zu ~1,5s Timeout + 1 Retry PRO Query
     (§7.4, mehrere Queries in `get_state()`), was sich bei mehreren
     gleichzeitig nicht erreichbaren Kameras (z. B. Emulator-Kameras in
     `config.yaml`, wenn der Emulator gerade nicht läuft) spürbar aufsummiert
     hat. Jetzt nebenläufig über `asyncio.gather()` -- jede Kamera bleibt
     unabhängig (eigener Treiber/State-Eintrag), ein hängender/
     fehlschlagender Connect blockiert die anderen nicht mehr; dieselbe
     Defensiv-Fehlerbehandlung (Exception geloggt, `cam_state.error`
     gesetzt, Startup bricht nie ab) bleibt pro Kamera erhalten.
  **Dabei eine unabhängige, nicht behobene Randbeobachtung gemacht:**
  `AppState.companion_client` (`field(default_factory=build_client)` in
  `core/application.py`) konstruiert bei JEDEM `build_app_state()`-Aufruf
  einen echten `httpx.AsyncClient()` -- das kostet auf der Entwicklungs-
  maschine selbst schon isoliert und reproduzierbar ~0,25-0,3s (vermutlich
  SSL-Kontext-/CA-Bundle-Aufbau, per direktem Test von
  `httpx.AsyncClient()` ohne jeden PTZ_Control-Code bestätigt). Das ist ein
  fixer, kamera-unabhängiger Sockel bei jedem Start -- spürbar, aber deutlich
  kleiner als die oben behobene, kamera-anzahl-abhängige Verzögerung, daher
  hier nur dokumentiert, nicht angefasst (kein Teil dieses Bugreports).
  Getestet in `tests/test_web_app.py`
  (`test_lifespan_connects_multiple_cameras_concurrently_not_sequentially`,
  zwei Kameras mit je 1s simuliertem `connect()`-Delay, Assertion auf
  Gesamtzeit deutlich unter dem sequenziellen Fall). 295 Tests bestehen
  (vorher 294), keine Regression. **Nicht separat live verifiziert** (die
  eigentliche Nebenläufigkeit ist nur per Unit-Test mit künstlicher
  Verzögerung belegt) -- der Nutzer hat aber für die nächsten Tage eine
  reale AW-UE160 + X-Touch zum Testen zur Verfügung (siehe Session-Notiz),
  ein echter Neustart mit mehreren konfigurierten, teils nicht erreichbaren
  Kameras würde das zusätzlich bestätigen.
- **Button 1 zeigt beim Start zuerst "Camera Info" statt "Gain"
  (Nutzerauftrag 2026-07-23):** `core/application.py._ENCODER_FUNCTIONS`
  umsortiert zu `("camera_status", "gain", "pedestal", "nd")` -- da jede
  Default-Index-Abfrage (`channel_display_text()`, `encoder_preview()`,
  `channel_line1_text()`, der Web-Snapshot, `cycle_encoder_function()`s
  erster Druck) auf `.get(channel_index, 0)` zurueckfaellt, zeigt Button 1
  ohne jeden Druck (App-Start, Kamera-Connect) jetzt zuerst "Camera Info"
  statt "Gain" -- der Zyklus selbst bleibt Gain→Pedestal→ND→Camera Info→wrap
  (nur der Startpunkt verschob sich). Zusaetzlich: das Button-1-Label selbst
  hiess vorher wortwoertlich "Camera Status" (aus dem Funktionsnamen
  `camera_status` abgeleitet, `enc.function | replace('_',' ') | upper` in
  `web/templates/surface.html` UND client-seitig nochmal in
  `web/static/app.js` bei jedem WebSocket-Snapshot) -- auf "Camera Info"
  umbenannt (Nutzerauftrag), interne Kennung `camera_status` bewusst
  unveraendert gelassen (Nutzerentscheid: Umbenennung nur menschenlesbarer
  Text, keine Code-Identifier). 24 Tests in `tests/test_application.py` und
  3 in `tests/test_web_app.py` mussten dabei angepasst werden (sie nahmen
  bisher "Gain" als impliziten Default an, meist durch direktes Setzen von
  `state.encoder_function_index[...]` ersetzt statt durch Zaehlen von
  Cycle-Druecken, um nicht fragil an der genauen Reihenfolge zu haengen).
  295 Tests bestehen (vorher 269 vor dieser und der vorherigen ND-Aenderung
  in Summe, siehe vorherige Eintraege), keine Regression.
- **Iris-Anzeige bei `camera_status` zeigt jetzt die F-Nummer statt Iris-%
  (Nutzerauftrag 2026-07-23, siehe Spec §14 Punkt 10 fuer die volle
  Herleitung der Dekodier-Formel):** `drivers/panasonic_aw.py::
  _decode_f_number()` dekodiert `QIF`/`OIF:[Data]` ueber die live gegen eine
  reale AW-UE160 kalibrierte Formel `Data/10 = F-Nummer` (10 Live-Messpunkte,
  F4.0-F11.0, exakt deckungsgleich mit den beiden Spec-Ankern 0Eh=F1.4/
  A0h=F16) fuer den bestaetigten Bereich 0Eh-A0h, `FFh`→"CLOSE" als
  separater Sentinel. Der Bereich A1h-FEh (zwischen F16-Anker und CLOSE)
  bleibt bewusst UNdekodiert (`query_f_number()` faellt dort auf den rohen
  Hex-Wert zurueck) -- zwei Live-Versuche in beide Richtungen sprangen in
  einem einzigen Kamera-Klick direkt zwischen `FFh` und `6Eh`, ohne einen
  Zwischenwert zu zeigen; bei der getesteten Zoomposition scheint dieser
  Bereich ueber die normale Iris-Steuerung nicht einzeln anwaehlbar zu sein.
  `channel_display_text()` in `core/application.py` liest dafuer jetzt
  `cam_state.iris_f_number` (bisher nur roh durchgereicht, nie dekodiert)
  statt der bisherigen `_iris_percent_text()`-Hilfsfunktion (entfernt, war
  nur an dieser einen Stelle genutzt) -- Funktionssignatur verlor dabei den
  `iris`-Parameter (nicht mehr gebraucht), alle drei Aufrufstellen in
  `midi/fader.py` sowie `channel_snapshot()` angepasst; `_send_iris_percent_
  line()` in `midi/fader.py` war dadurch identisch zu `_refresh_channel_
  line2()` geworden und wurde entfernt (Aufrufer nutzt jetzt Letzteres).
  **Live-Update-Verhalten waehrend eines Fader-Zugs:** anders als die
  bisherige Iris-%-Anzeige (lokal aus der Fader-Position berechenbar) gibt
  es fuer die F-Nummer keine Formel aus der Iris-Position -- nur die
  kamera-eigene `QIF`-Abfrage, und die Positions/F-Nummer-Beziehung ist
  selbst laut den Live-Messwerten nichtlinear. **Erste Fassung** fragte die
  F-Nummer deshalb nur bei `final=True` (Loslassen) neu ab, um nicht bei
  jedem Dreh-Tick einen zusaetzlichen Kamera-Request auszuloesen -- **noch
  am selben Tag durch Live-Test am echten Fader revidiert (Nutzerauftrag):**
  eine einzelne `QIF`-Abfrage ist klein genug (kleiner GET, wenige Bytes
  Antwort), um live waehrend des Ziehens keinen spuerbaren Zusatz-Traffic zu
  verursachen -- `apply_iris()` fragt die F-Nummer jetzt bei JEDEM vom
  Rate-Limiter durchgelassenen Tick per `driver.query_f_number()` neu ab
  (nicht mehr nur bei `final=True`). `query_f_number()` wurde dafuer von
  `PanasonicAWDriver._query_f_number()` (intern, nur in `get_state()`
  genutzt) zu einer oeffentlichen Methode der `CameraDriver`-ABC
  (`drivers/base.py`) -- fragt bewusst nur dieses eine Feld ab, nicht den
  vollen `get_state()` (Gain/Pedestal/ND/Fehler waeren pro Tick unnoetig).
  Externe Iris-Aenderungen (Kamera-eigenes Web-UI, anderer Controller)
  aktualisieren die F-Nummer weiterhin NICHT live -- die Kamera pusht ueber
  den Update-Notification-Kanal nur die Iris-POSITION (`lPI`-Frame, §7.3.2,
  dieselbe 555h-FFFh-Kodierung wie `#GI`), keine F-Nummer; das ist derselbe,
  bereits dokumentierte Kanal, ueber den der Motorfader live nachgefuehrt
  wird (Zeile 2 der Kanal-Anzeige bleibt bei einer externen Aenderung
  entsprechend auf dem zuletzt bekannten Stand, bis zum naechsten expliziten
  Fader-Zug/Reconnect -- analog zur bereits dokumentierten auto_focus/
  auto_iris-Einschraenkung weiter oben). Getestet in `tests/test_panasonic.py`
  (`test_decode_f_number_matches_live_calibration`,
  `test_decode_f_number_close_sentinel`,
  `test_decode_f_number_unconfirmed_gap_returns_none`,
  `test_query_f_number_decodes_known_range`,
  `test_query_f_number_falls_back_to_raw_hex_in_unconfirmed_gap`),
  `tests/test_application.py`
  (`test_apply_iris_refreshes_f_number_on_every_tick`). 301 Tests bestehen
  (vorher 295), keine Regression. **Live gegen die reale AW-UE160
  (`192.168.11.134`) + X-Touch verifiziert (2026-07-23):** Button 1 zeigte
  "CAMERA INFO" (siehe vorheriger Punkt), physischer Fader-Zug hat laut
  Nutzer funktioniert -- die konkrete "live waehrend des Ziehens
  aktualisiert" vs. "nur bei final"-Unterscheidung selbst wurde dabei noch
  nicht separat gegengeprueft (die Revision auf "jeder Tick" erfolgte direkt
  im Anschluss an diesen Test, noch ungetestet am echten Geraet).
- **Externe Iris-Bewegung (z. B. Auto-Iris) aktualisierte die F-Nummer-
  Anzeige nicht (Bugreport 2026-07-23, live gegen die reale AW-UE160
  `192.168.11.134` gefunden UND bestaetigt):** Nutzer schaltete Auto-Iris
  direkt an der Kamera ein/aus (nicht ueber PTZ_Control) -- ein WS-Probe-
  Skript bestaetigte, dass `cam_state.iris` (Position, ueber das
  `lPI`-Lens-Info-Frame, §7.3.2) UND der physische Motorfader live korrekt
  der Auto-Iris-Bewegung folgten, `cam_state.auto_iris` aber nie auf `True`
  wechselte (bekannte Einschraenkung, `ORS` sendet keine Notification, siehe
  weiter oben) -- das war NICHT der eigentliche Bug. Der eigentliche Bug
  zeigte sich erst danach: App zeigte "F11.0", `QIF` direkt gegen die Kamera
  UND deren eigenes OSD zeigten uebereinstimmend "F6.4" -- **Root Cause:**
  das `lPI`-Frame traegt nur die rohe Iris-POSITION (555h-FFFh, dieselbe
  Kodierung wie `#GI`), keine F-Nummer; `_wire_camera_events()`s
  `iris_changed`-Zweig in `core/application.py` aktualisierte bisher nur
  `cam_state.iris`, nie `cam_state.iris_f_number` -- die F-Nummer wurde also
  ausschliesslich von `apply_iris()` aufgefrischt (nur bei PTZ_Control-
  eigenen Fader-Zuegen, siehe vorheriger Punkt), nie bei extern (Kamera-
  eigenes Auto-Iris/Web-UI/anderer Controller) ausgeloesten Positions-
  aenderungen. Neue `_refresh_f_number_from_notification()`-Hilfsfunktion
  fragt bei jeder ueber die Notification ankommenden `iris_changed`-
  Positionsaenderung `driver.query_f_number()` zusaetzlich ab und publiziert
  erneut `iris_changed` (aktualisiert damit sowohl Web-UI-Snapshot als auch
  Scribble-Strip-Zeile 2, beide bereits auf dieses Topic abonniert) --
  bewusst NUR bei tatsaechlicher Positionsaenderung (`cam_state.iris` vorher
  != neuer Wert), nicht bei jedem ~300ms-lPI-Heartbeat, um keinen
  Dauer-Traffic zu erzeugen, wenn sich nichts bewegt. Getestet in
  `tests/test_application.py`
  (`test_driver_iris_changed_event_refreshes_f_number_on_position_change`,
  `test_driver_iris_changed_event_skips_f_number_refresh_when_position_
  unchanged`). 302 Tests bestehen (vorher 301), keine Regression. **Noch
  nicht erneut live gegengeprueft** (Fix direkt aus der Live-Diagnose
  entwickelt, aber die konkrete Korrektur selbst -- App neu gestartet,
  zeigt jetzt bei einer erneuten Auto-Iris-Bewegung die korrekte F-Nummer --
  wurde bisher nicht durch einen weiteren Auto-Iris-Test am echten Geraet
  bestaetigt).
- **Iris-F-Nummer-Formel modelluebergreifend PDF-bestaetigt, `QIF`-Anfrage
  jetzt modellabhaengig gegated (Nutzerauftrag 2026-07-23, "check pdfs
  first" -> "implement for the camera models that are pdf confirmed"):**
  die live gegen eine reale AW-UE160 kalibrierte Formel (Data/10 = F-Nummer,
  siehe vorheriger Punkt) wurde durch Pruefung aller sechs lokalen
  Referenz-PDFs (kein Live-Test) gegengecheckt: `AW-UE150A_
  InterfaceSpecification_E.pdf`, `AW-UE100_InterfaceSpecification_E.pdf` und
  `AW-UE150HE145_InterfaceSpecification_E.pdf` zeigen wortgleich dieselben
  Ankerpunkte (0Eh=F1.4/1Ch=F2.8/38h=F5.6/A0h=F16/FFh=CLOSE) wie die eigene
  AW-UE160-PDF; `AW-UE80UE50UE40_InterfaceSpecification_E.pdf` bestaetigt nur
  die ersten beiden Punkte (0Eh/1Ch), aber ohne Widerspruch. Damit gilt die
  Formel selbst als modelluebergreifend bestaetigt (kein Modell-Branching in
  `_decode_f_number()` noetig).
  **Wichtigerer Befund:** `HDIntegratedCamera_InterfaceSpecifications-E.pdf`
  (deckt die Modellgruppe AW-HE40/50/60/120/130, AW-HR140, AW-UE70, AW-HE42,
  AK-UB300 ab) nennt "Iris F value" (`QIF`) explizit **"Only supported by the
  AK-UB300/AW-UE150"** -- fuer die uebrigen acht Modelle dieser Gruppe war
  `query_f_number()` bisher ein sinnloser Request (haette vermutlich nur
  einen Fehler zurueckbekommen, `CameraCommandError` wurde zwar schon vorher
  abgefangen, aber unnoetig bei JEDEM Fader-Tick versucht). Neues Feld
  `PanasonicAWDriver.supports_iris_f_number` (aufgeloest in
  `_apply_model_catalog()` aus `SUPPORTS_IRIS_F_NUMBER` je Modell-Modul,
  Default `False`, analog zum bestehenden `nd_options`-Muster) -- `query_
  f_number()` gibt jetzt sofort `None` zurueck, ohne `QIF` zu senden, wenn
  das verbundene Modell nicht in der PDF-bestaetigten Liste steht.
  `SUPPORTS_IRIS_F_NUMBER = True` gesetzt bei: AW-UE160, AW-UE100,
  AW-UE150A (+Alias AW-UE150), AW-HE145 (+Alias AW-UE145), AW-UE80 (+UE30/
  UE40/UE50, re-exportiert), AK-UB300. Bewusst NICHT gesetzt (nur
  Docstring-Vermerk, kein erfundener Fallback noetig, da `getattr(...,
  False)` bereits ohne den Konstante nach `False` aufloest) bei: AW-HE40,
  AW-HE42, AW-HE50, AW-HE60, AW-HE120, AW-HE130, AW-HR140, AW-UE70 --
  bemerkenswert bei AW-HE130/AW-HR140, da diese sonst zur selben
  Knee-/White-Clip-Gruppe wie AW-UE150 gehoeren, hier aber trotzdem
  ausgenommen sind (unterschiedliche Feature-Untermengen je PDF-Tabelle,
  kein einheitliches "Tier"). Getestet in `tests/test_panasonic_models.py`
  (`test_iris_f_number_supported_for_pdf_confirmed_models`,
  `test_iris_f_number_absent_for_models_not_named_in_general_pdf`),
  `tests/test_panasonic.py`
  (`test_apply_model_catalog_resolves_supports_iris_f_number_true_for_ue160`,
  `test_apply_model_catalog_supports_iris_f_number_false_for_he130_not_in_pdf`,
  `test_apply_model_catalog_supports_iris_f_number_false_for_unrecognized_model`,
  `test_query_f_number_skips_request_for_model_without_pdf_support`). 309
  Tests bestehen (vorher 302 vor dieser Aenderung, plus die vorherigen zwei
  F-Nummer-Eintraege in Summe). **Nicht live verifiziert** -- diese Aenderung
  beruht ausschliesslich auf PDF-Pruefung (Nutzerauftrag "check pdfs first"),
  nicht auf einem Test gegen eine echte AW-HE-Serie/AW-HR140/AK-UB300-Kamera;
  ob diese Modelle `QIF` tatsaechlich ablehnen (statt es z. B. stillschweigend
  zu ignorieren oder doch zu beantworten), ist damit weiterhin nur aus der
  PDF-Formulierung abgeleitet, nicht am Geraet bestaetigt.
- **Config-Editor-Seite (Spec §10 Punkt 3) entfernt statt umgesetzt
  (Nutzerentscheid 2026-07-23):** die Seite war seit ihrer urspruenglichen
  Anlage ein reines Mockup -- `web/templates/config.html` zeigte fest
  einprogrammiertes Beispiel-YAML statt der tatsaechlich geladenen
  `config.yaml`, und der "Reload Config"-Button hatte weder ein
  `data-*`-Attribut noch irgendeine JS-/Backend-Anbindung (`core/config.py`
  hatte zu keinem Zeitpunkt eine reload-in-die-laufende-App-Funktion, nur
  `load_config()`/`save_config()`). Im Unterschied zur bereits frueher
  entfernten MIDI-Port-Dropdown-Mockup (siehe Eintrag oben) steht dieser
  Editor aber ausdruecklich in Spec §10 Punkt 3 als vorgesehenes v1-Feature
  ("nur Anzeige des geladenen YAML + 'Reload Config'") -- die Entfernung ist
  damit eine bewusste Scope-Abweichung von der Spec, kein reines
  Mockup-Aufraeumen, und wird deshalb hier ausdruecklich festgehalten (Spec
  §10 selbst bleibt unveraendert als historischer v1-Plan stehen, wie beim
  MIDI-Dropdown-Vorfall auch). Grund fuer die Entfernung: die Seite zeigte in
  ihrem aktuellen Zustand aktiv falsche Daten (fixes Beispiel-YAML statt der
  echten Config) und suggerierte eine funktionierende Reload-Funktion, die
  nie existierte -- dieselbe "lieber entfernen als eine Mockup-Attrappe
  stehen lassen"-Logik wie beim MIDI-Dropdown. Entfernt: Nav-Link in
  `web/templates/base.html`, Route `GET /config` (`config_page()`) in
  `web/app.py`, Template `web/templates/config.html`, das dort einzige
  genutzte `.code-block`-CSS in `web/static/app.css` (dead code nach der
  Template-Loeschung), sowie `tests/test_web_app.py::
  test_config_page_returns_ok`. 308 Tests bestehen (vorher 309, ein Test
  entfernt statt ersetzt, keine Regression bei den verbleibenden). Kein
  Ersatz-Feature umgesetzt -- Konfigurationsaenderungen jenseits von
  Kamera-Stammdaten (die weiterhin ueber die Setup-Seite laufen) bleiben wie
  zuvor nur ueber direktes Bearbeiten von `config.yaml` + App-Neustart
  moeglich, keine Live-Reload-Moeglichkeit. Falls der urspruengliche
  Anwendungsfall (Config-Aenderungen ohne Neustart pruefen/uebernehmen)
  doch noch gebraucht wird, ist das ein separater, neuer Auftrag.
- **Startup-Dialog "Load previous config"/"Start new config" (Nutzerauftrag
  2026-07-23, bewusste Erweiterung ueber v1 hinaus, kein Spec-Bezug):** beim
  Oeffnen der Web-UI (jede Seite, nicht nur die Control-Seite -- falls eine
  andere Seite zuerst geladen/eine alte Tab neu geladen wird) erscheint ein
  Overlay-Dialog mit zwei Optionen. "Load previous config" ist ein reines
  No-Op (die App hat beim Boot bereits normal mit der zuletzt gespeicherten
  `config.yaml` verbunden, siehe `lifespan()` in `web/app.py`) -- markiert
  die Frage nur als beantwortet. "Start new config" ruft
  `core/application.py::reset_to_new_config()` auf: trennt jede beim Boot
  verbundene Kamera (`disconnect_camera()`, entfernt dabei bereits deren
  Registrierung aus `config.yaml`) und setzt Companion/MIDI/Bank-/Kanal-
  Defaults zusaetzlich auf die Schema-Defaults zurueck, sodass `config.yaml`
  danach dem Zustand einer frisch angelegten Datei entspricht.
  **"Disconnect-after-the-fact" statt deferred startup (Nutzerentscheid):**
  urspruenglich war erwogen worden, das Laden von `config.yaml` bis nach der
  Nutzerantwort aufzuschieben (echter "leerer Start"), das haette aber einen
  groesseren Umbau der Startup-Reihenfolge (Config-Laden vor Server-Start,
  Kamera-Connect in `lifespan()`) erfordert -- stattdessen verbindet die App
  beim Boot weiterhin ganz normal wie bisher, und "Start new config" raeumt
  das im Nachhinein wieder auf. Neue `AppState.startup_choice_pending`
  (Default `True`, rein Laufzeitzustand, nicht in `config.yaml`) sowie drei
  Routen: `GET /api/startup/status`, `POST /api/startup/load-previous`,
  `POST /api/startup/new-config`. Frontend (`web/static/app.js::
  initStartupChoiceDialog()`) fragt den Status bei jedem Seitenaufruf ab und
  zeigt bei `pending=true` ein Overlay (`web/templates/base.html`,
  `.startup-overlay`/`.startup-dialog` in `app.css`) -- die dahinterliegende
  Web-UI bleibt sichtbar, aber per `.app-shell.is-dimmed`
  (`filter: grayscale(1) brightness(0.55)` + `pointer-events: none`)
  gedimmt/nicht bedienbar (Nutzerauftrag: "web ui in the background but
  grayed out" statt eines rein nativen Dialogs -- passt ausserdem besser
  zum bestehenden FastAPI+HTMX-Stack als ein natives tkinter-Fenster, keine
  neue Abhaengigkeit noetig). "Start new config" hat client-seitig ein
  `confirm()`-Popup davor (destruktive Aktion: trennt alle Kameras und
  ueberschreibt `config.yaml`), beide Aktionen laden danach die Seite neu
  (`location.reload()`, gleiches Muster wie beim bestehenden Kamera-Connect/
  Disconnect-Button). Getestet in `tests/test_application.py`
  (`test_reset_to_new_config_disconnects_camera_and_clears_config`,
  `test_reset_to_new_config_persists_empty_config_to_file`,
  `test_reset_to_new_config_publishes_config_changed`,
  `test_reset_to_new_config_with_no_cameras_is_noop_safe`),
  `tests/test_web_app.py` (`test_startup_status_pending_by_default`,
  `test_startup_load_previous_marks_answered_without_touching_cameras`,
  `test_startup_new_config_endpoint_disconnects_camera_and_resets_config`).
  315 Tests bestehen (vorher 308). **Live gegen eine echte laufende
  Instanz verifiziert (2026-07-23, separates Scratch-Verzeichnis + eigene
  `config.yaml`-Kopie, NICHT die echte Projekt-`config.yaml`):** `GET /`
  liefert das Overlay-Markup, `app.css`/`app.js` liefern die neuen
  Regeln/Funktion aus, `POST /api/startup/new-config` hat live eine
  registrierte Testkamera getrennt und die Scratch-`config.yaml` auf den
  Default-Zustand zurueckgesetzt (`cameras: []`, `banks: []` usw.) --
  serverseitiger Roundtrip vollstaendig bestaetigt. **Nicht verifiziert:**
  das Overlay/Dimmen visuell im Browser (kein Browser-Automatisierungs-
  Tool auf dieser Windows-Maschine verfuegbar, nur `curl`-basierte Pruefung
  von HTML/CSS/JS-Inhalt und API-Roundtrip) sowie das Verhalten des
  `confirm()`-Popups selbst.
- **Button 1 liess sich nach einem Fader-Zug bei aktivem Auto-Iris nicht mehr
  umschalten (Bugreport 2026-07-23, direkte Folge des Auto-Iris-Snapback-
  Fixes weiter oben):** Nutzer meldete nach Bestaetigung des Snapback-Fixes
  ("it is workin now"), dass Rec/Button 1 (Encoder-Funktionsauswahl)
  danach auf KEINEM Kanal mehr reagierte, nicht nur auf dem betroffenen.
  **Root Cause (per Code-Lesen erschlossen, nicht durch einen mitgeschnittenen
  Traceback bestaetigt -- ein etwaiger Fehler haette wie beim analogen,
  bereits behobenen Tx-Bug oben nur als "Task exception was never retrieved"
  ueber den asyncio-Root-Logger geloggt, NICHT ueber den vom `/logs`-
  Ringpuffer abgehoerten `ptz_control`-Logger, siehe dortiger Fix):**
  `midi/fader.py::_poll_loop()` rief `_handle(msg)` bisher ohne jede eigene
  Fehlerbehandlung auf -- eine Ausnahme aus IRGENDEINEM Handler (z. B. dem
  neuen `driver.query_iris()`-Aufruf in `apply_iris()` bei aktivem
  Auto-Iris, siehe Fix oben) haette den gesamten `while True`-Poll-Loop
  dauerhaft abgerissen (kein Supervisor/Neustart) -- danach reagiert das
  physische Geraet auf KEINE Note/Pitchbend-Nachricht mehr, exakt das
  gemeldete Symptom. Dieser Fehlerpfad war bereits als offener, bisher
  unbestaetigter Risikopunkt dokumentiert (s. o., "Rx-Seite hat weiterhin
  keine eigene Fehlerbehandlung") -- jetzt durch diesen Bugreport praktisch
  bestaetigt. Neue `XTouchFader._handle_safely()`-Methode (von `_poll_loop()`
  statt `_handle()` direkt aufgerufen) faengt jede Ausnahme ab, loggt sie
  (`LOGGER.exception(...)`, landet damit -- anders als das asyncio-Root-
  Logger-Verhalten oben -- diesmal korrekt im `/logs`-Ringpuffer) und macht
  mit der naechsten Nachricht weiter, statt den Loop mitzureissen. Getestet
  in `tests/test_fader.py`
  (`test_handle_safely_logs_and_swallows_exception_instead_of_killing_poll_loop`,
  `test_handle_safely_does_not_block_subsequent_messages` -- Letzterer bildet
  das gemeldete Symptom direkt nach: ein fehlschlagender erster Aufruf darf
  einen erfolgreichen zweiten Aufruf auf demselben Kanal nicht verhindern).
  321 Tests bestehen (vorher 319), keine Regression. **Nicht abschliessend
  geklärt:** die exakte Ausnahme, die beim Nutzer tatsaechlich auftrat, wurde
  NICHT durch einen mitgeschnittenen Traceback bestaetigt (per Code-Lesen
  konnte keine offensichtliche unbehandelte Ausnahme in `query_iris()`/
  `query_f_number()`/`apply_iris()` gefunden werden -- beide fangen
  `CameraCommandError` bereits ab) -- der Fix haertet `_poll_loop()` deshalb
  generell gegen JEDE Handler-Ausnahme ab (robuster, unabhaengig von der
  exakten Ursache), statt eine einzelne, nicht zweifelsfrei belegte Ursache
  gezielt zu patchen. Falls das Symptom nach diesem Fix erneut auftritt,
  waere jetzt zumindest eine Log-Zeile (`MIDI-Eingang-Verarbeitung
  fehlgeschlagen fuer ...`) im `/logs`-Ringpuffer zu erwarten, die die
  tatsaechliche Ausnahme benennt -- bisher nicht live gegen die reale
  Hardware nachgestellt.
  **Fortsetzung, noch am selben Tag (Bugreport: "on bank 1 the button 1 is
  still stuck at ND", danach "nothing is reacting to the controler" fuer
  ALLE Bedienelemente):** der Fix oben deckte nur `_handle()` (die
  Nachrichten-VERARBEITUNG) ab -- `self._in_port.iter_pending()` selbst
  (das eigentliche Port-LESEN, direkt in `_poll_loop()`s `while True`-Rumpf,
  ausserhalb jedes try/except) blieb ungeschuetzt. Ein Fehler dort (z. B.
  ein transienter `rtmidi`-Lesefehler) haette den Poll-Loop weiterhin
  dauerhaft mitgerissen -- passt exakt zum gemeldeten "gar keine Reaktion
  mehr auf dem Controller" (Fader/Rec/Solo/Mute/Select gleichermassen
  betroffen, nicht nur ND/Button 1). Das war derselbe, bereits in CLAUDE.md
  als offen dokumentierte Risikopfad ("Rx-Seite hat weiterhin keine eigene
  Fehlerbehandlung beim Lesen") -- durch diesen zweiten Bugreport jetzt
  ebenfalls praktisch bestaetigt. `_poll_loop()`s Rumpf wurde dafuer in eine
  neue `_poll_once()`-Methode extrahiert (testbar ohne die eigentliche
  Endlosschleife laufen zu lassen); das Lesen (`iter_pending()`) hat jetzt
  ein eigenes try/except (`LOGGER.exception("MIDI-Eingang-Lesen
  fehlgeschlagen")`, bricht den aktuellen Takt ab, naechster Takt startet
  normal), waehrend die Verarbeitung weiterhin ueber `_handle_safely()`
  laeuft (unveraendert). Getestet in `tests/test_fader.py`
  (`test_poll_once_logs_and_returns_when_reading_input_fails`,
  `test_poll_once_processes_pending_messages_normally`,
  `test_poll_once_recovers_on_next_call_after_a_failed_read` -- neue
  `FakeInPort`-Testklasse simuliert sowohl einen werfenden `iter_pending()`
  als auch eine normale Nachrichtenliste). 324 Tests bestehen (vorher 321),
  keine Regression. **Wichtig fuer den Nutzer:** dieser Fix wird erst nach
  einem vollstaendigen Neustart der App wirksam (nicht durch bloßes
  Neuladen der Browser-Seite) -- ob er das gemeldete Symptom tatsaechlich
  behebt, ist damit erst nach einem erneuten Test am echten Geraet bekannt.
  **Weiterhin nicht abschliessend geklärt:** wie beim ersten Teil dieses
  Bugreports wurde auch hier kein tatsaechlicher Traceback vom Nutzer
  eingesehen (nur die Symptombeschreibung) -- die Ursache des Lesefehlers
  selbst (Windows-USB-Energieverwaltung? etwas anderes?) bleibt unbestaetigt,
  nur die fehlende Fehlerbehandlung drumherum wurde behoben.
- **`config.yaml` versehentlich per "Start new config" auf die reale Projekt-
  Config statt nur eine Scratch-Kopie angewendet (2026-07-23):** die
  MIDI-Ports (`midi.input_port`/`output_port`) sowie alle 5 Kameras/Bank A/
  Companion waren in der (uncommitteten) Arbeitskopie auf die Schema-
  Defaults zurueckgesetzt -- deckungsgleich mit `reset_to_new_config()`
  (Startup-Dialog "Start new config", siehe Eintrag oben). Root Cause fuer
  den gemeldeten "keine Verbindung zum X-Touch": `web/app.py`s Lifespan
  versucht den MIDI-Connect nur, wenn `config.midi.input_port` truthy ist --
  mit leerem String wurde gar nicht erst versucht zu verbinden (kein
  Hardware-/Treiberproblem). Per `git checkout -- config.yaml` auf den
  letzten committeten Stand zurueckgesetzt (Nutzerentscheid: voller Restore,
  nicht nur die MIDI-Zeilen). Dabei zusaetzlich verifiziert (nicht nur
  angenommen): echte Hardware-Portnamen sind `X-Touch-Ext 0` (Input)/
  `X-Touch-Ext 1` (Output) -- der konfigurierte Kurzname `X-Touch-Ext` matcht
  darueber per Substring (`web/app.py::_find_midi_port()`, Spec §5.5), kein
  eigener Fehlerpfad.
- **Auto-Iris-Snapback (siehe Eintrag oben, urspruenglich 2026-07-23 gefixt)
  griff nach Druck auf einen Auto-Iris-Button nicht (Bugreport 2026-07-23,
  direkt im Anschluss an den vorigen Punkt gemeldet: "wir hatten das schon
  gefixt, dann kam aber die Verbindungstrennung dazwischen"):** Root Cause
  gefunden, unabhaengig vom fruehren `_poll_loop()`-Crash-Bug (der war
  bereits vorher behoben, siehe Eintraege oben) -- `apply_button_action()`
  in `core/application.py` aktualisierte beim Umschalten eines
  "auto_iris"-Toggle-Buttons bisher nur `cam_state.feature_states
  ["auto_iris"]` (fuer die Button-LED), nicht aber das separate
  `cam_state.auto_iris`-Feld, das `apply_iris()`s Snapback-Logik tatsaechlich
  prueft (siehe dortiger Eintrag) -- ein Fader-Zug direkt nach Druck auf den
  Auto-Iris-Button sah deshalb weiterhin den veralteten Auto-Iris-Stand (i. d.
  R. `False` seit dem letzten Connect) und sprang nicht zurueck, obwohl die
  Kamera laengst auf Auto-Iris stand. Neuer Zweig in `apply_button_action()`:
  bei `feature_key == "auto_iris"` wird nach dem Toggle zusaetzlich
  `cam_state.auto_iris = new_enabled` gesetzt. Getestet in
  `tests/test_application.py`
  (`test_apply_button_action_auto_iris_toggle_updates_cam_state_auto_iris`).
  325 Tests bestehen (vorher 324), keine Regression. **Nicht live
  nachgeprueft** -- der Fix ist nur unittest-abgesichert, noch nicht erneut
  am echten X-Touch/einer echten Kamera gegengetestet.

## Abschlussregel

Bevor eine Änderung als „fertig“ oder „gelöst“ beschrieben wird, muss sie in der Praxis verifiziert sein: durch Test, Laufzeitausgabe, Log, oder nachvollziehbare Datei-/Code-Evidenz.

Wenn etwas nicht verifiziert werden kann, ist der korrekte Status:
- „noch unbestätigt“
- „nicht verifiziert“
- „in der Spezifikation nicht definiert“

Nicht mit „sollte funktionieren“ oder ähnlichen ungesicherten Formulierungen abschließen.
