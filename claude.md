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
  **Weiterhin offen:** die per-Tick-Schrittweite des Encoders (±1 Digit,
  ×5-Beschleunigung) berücksichtigt `GAIN_STEP_DB` noch nicht -- bei den
  3dB-Stufen-Modellen (AW-HE50/60/HE40/UE70/HE42) sendet ein einzelner Tick
  weiterhin ±1dB (bzw. ±5dB beschleunigt), nicht zwingend ein gültiges
  Vielfaches von 3. Verhalten der Kamera bei einem solchen Zwischenwert
  (z. B. `OGU:09`) ist nicht dokumentiert/verifiziert.
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
  aufgelösten Modell-Modul. Getestet in `tests/test_panasonic_models.py`
  (`test_drs_is_three_value_cycle_for_he_low_tier_group`,
  `test_drs_is_four_value_cycle_for_higher_tier_group`,
  `test_knee_absent_from_he120_not_supported_per_pdf`,
  `test_knee_is_three_value_cycle_where_supported`,
  `test_knee_not_guessed_for_ue80_group_despite_menu_entry`), live gegen
  Emulator verifiziert (HE50 lehnt `OSE:33:2` ab, HE120 lehnt jedes
  `OSA:2D`-Kommando ab, UE100 akzeptiert `OSA:2D:2`).
  **Weiterhin offen:** der Rest des Katalogs (`auto_focus`, `auto_iris`,
  `awb_black`, `aww_white`, `osd`, `white_clip`, `matrix`, `gamma`, `flare`,
  `linear_matrix`, `adaptive_matrix`, `night_mode`, `super_gain` u. Ä.) ist
  weiterhin nur gegen smart_reset_work verifiziert, nicht gegen die PDFs;
  ebenso die genauen Knee-Werte für AW-UE80/UE50/UE40/UE30.
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
