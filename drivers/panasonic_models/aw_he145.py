"""drivers/panasonic_models/aw_he145.py -- Panasonic AW-HE145.

Umbenannt/korrigiert aus `aw_ue145.py` (Nutzerentscheid 2026-07-18): das
dedizierte `docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf` (2022,
"AW-UE150/AW-HE145") zeigt in seiner "Model Number"-Tabelle die tatsaechlich
per `QID` gemeldeten Werte -- `OID:AW-UE150` UND `OID:AW-HE145` -- fuer zwei
unterschiedliche, aber im selben Dokument gefuehrte Modelle. Der bisherige
CAMERA_ID "AW-UE145" passte zu KEINEM der beiden echten QID-Strings (Fehler
beim urspruenglichen Port, uebernommen aus `smart_reset_work`s Dateiname
`aw_ue145.py`) -- eine reale AW-HE145-Kamera waere damit nie erkannt worden.
CAMERA_ID ist jetzt "AW-HE145" (verifiziert), "AW-UE145" bleibt als Alias
erhalten (die alte, wahrscheinlich falsch benannte Bezeichnung, fuer den
Fall dass irgendwo noch danach gesucht wird).

Button-Katalog unveraendert aus `C:\\smart_reset_work\\camera_plugins\\
panasonic\\aw_ue145.py`s UI_BUTTONS/UI_BUTTON_LABELS uebernommen (re-
exportiert von `aw_ue150.py`, siehe dort) -- diese Korrektur betrifft nur
die Modell-Identifikation, nicht den Katalog.

Gain/Pedestal (Quelle: das oben genannte dedizierte PDF, Kap. 9 "Command
List" -- gilt laut Dokument gemeinsam fuer AW-UE150 UND AW-HE145, keine
"only supported by"-Einschraenkung beim Gain-/Pedestal-Abschnitt gefunden):
Gain (`OGU`/`QGU`) kontinuierlich 05h=-3dB .. 08h=0dB .. 32h=+42dB (1dB-
Schritte), 80h=AGC; Maximalwert an "Super Gain" gekoppelt (0..36dB wenn aus,
-3..42dB wenn an, wie bei AW-UE100/UE80 -- Kopplung hier nicht durchgesetzt).
Pedestal ueber `OSJ:0F`/`QSJ:0F` Master Pedestal, Data 738h=-200/800h=0/
8C8h=+200 -- identisch zu AW-UE150A/AW-UE100/AW-UE80/AW-UE160.

**Wichtig:** dieses PDF widerspricht bei Gain dem aelteren Multi-Modell-PDF
(`HDIntegratedCamera_InterfaceSpecifications-E.pdf`, 2020), das fuer
AW-UE150 0..+42dB (nicht -3..+42dB) angibt. Nutzerentscheid 2026-07-18: das
neuere, dedizierte PDF gilt als massgeblich -- `aw_ue150.py`s GAIN_MIN_DB
wurde entsprechend von 0 auf -3 korrigiert (siehe dortiger Kommentar).
"""

from drivers.panasonic_models.aw_ue150 import BUTTON_FEATURE_LABELS, BUTTON_FEATURES  # noqa: F401

CAMERA_ID = "AW-HE145"
CAMERA_ID_ALIASES = ["AW-UE145", "AW-UE150HE", "AW-UE150HE145"]
DISPLAY_NAME = "Panasonic AW-HE145"

GAIN_MIN_DB = -3
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3
