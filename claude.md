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
  **Nicht verifiziert:** LED-Tx (Note-On/Off zurück ans Gerät) sowie die Note-Rx-Bereiche
  für Solo/Mute/Select auf Kanal 2–8 wurden noch nicht gegen die reale Hardware getestet —
  nur Kanal 1 Rx ist bisher hardwareverifiziert (siehe oben), Tx für keinen der vier
  Tastentypen bisher überhaupt.
- Hotplug/Reconnect für den MIDI-Port (Spec §5.5) nicht implementiert
- Web-UI-Port-Auswahl für MIDI (Setup-Seite) ist weiterhin ein statisches Mockup, nicht mit
  echten `mido`-Ports verbunden — Port kommt aktuell nur aus `config.yaml`
- Update-Notifications für andere Ereignisse als Iris (`OAW`, `OWS` etc., Spec §7.3.1) laufen
  technisch über denselben neuen Notification-Kanal, werden aber nicht ausgewertet
  (`PanasonicAWDriver._handle_notification` reagiert nur auf `lPI`)
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

## Abschlussregel

Bevor eine Änderung als „fertig“ oder „gelöst“ beschrieben wird, muss sie in der Praxis verifiziert sein: durch Test, Laufzeitausgabe, Log, oder nachvollziehbare Datei-/Code-Evidenz.

Wenn etwas nicht verifiziert werden kann, ist der korrekte Status:
- „noch unbestätigt“
- „nicht verifiziert“
- „in der Spezifikation nicht definiert“

Nicht mit „sollte funktionieren“ oder ähnlichen ungesicherten Formulierungen abschließen.
