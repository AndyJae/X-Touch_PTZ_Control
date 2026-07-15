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
- Panasonic AW-Serie, besonders AW-UE160
- HTTP-basierte Befehle per CGI
- Feedback über Update-Notifications, Lens-Info und Polling
- Externe Referenzquelle für Button-Funktionen: `smart-reset-browser`
  (lokal `C:\smart-reset-browser`) — verifizierte `UI_BUTTONS`/`UI_BUTTON_LABELS`
  pro Kameramodell, siehe Spec §9a

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
- reale MC-Belegung des X-Touch Extender verifizieren
- `QGU`-Abfrage gegen Gerät prüfen
- Verhalten von `#AXI` bei aktivem Auto-Iris testen
- Scribble-Strip-Offsets / Device-ID des Extenders verifizieren
- Integrationsmechanismus für die Button-Funktionsquelle aus `smart-reset-browser` (§9a) —
  für AW-UE160 über das Web-UI umgesetzt (siehe Spec §9a); physische Auslösung über den
  X-Touch Extender bleibt offen, da MIDI weiterhin nicht angeschlossen ist
- Verhalten bei erkanntem Kameramodell ohne `smart-reset-browser`-Plugin-Modul (§9a)
- Umfang etwaiger PTZ-Control-eigener Zusatzfunktionen über `smart-reset-browser` hinaus (§9a)

## Abschlussregel

Bevor eine Änderung als „fertig“ oder „gelöst“ beschrieben wird, muss sie in der Praxis verifiziert sein: durch Test, Laufzeitausgabe, Log, oder nachvollziehbare Datei-/Code-Evidenz.

Wenn etwas nicht verifiziert werden kann, ist der korrekte Status:
- „noch unbestätigt“
- „nicht verifiziert“
- „in der Spezifikation nicht definiert“

Nicht mit „sollte funktionieren“ oder ähnlichen ungesicherten Formulierungen abschließen.
