"""drivers/panasonic_models/aw_ue160.py -- Panasonic AW-UE160.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue160.py`s
UI_BUTTONS/UI_BUTTON_LABELS (bereits vor dieser Registry als hartkodierte
Klassenattribute auf `PanasonicAWDriver` verifiziert, siehe CLAUDE.md §9a --
hier nur an die Modell-Registry umgezogen, keine inhaltliche Aenderung).

Gain (OGU/QGU) und Master Pedestal (OSJ:0F/QSJ:0F) waren vor dem Umbau auf
per-Modell-Daten als Modul-Konstanten in `drivers/panasonic_aw.py` verifiziert
(Quelle: `AW-UE160_InterfaceSpecification_E.pdf`, Ankerpunkte OGU: 02h=-6dB/
08h=0dB/14h=+12dB, OSJ:0F: 738h=-200/800h=0/8C8h=+200) -- hier nur 1:1
uebernommen, keine inhaltliche Aenderung.

Knee-Korrektur (2026-07-18, Nutzerentscheid): war bereits als "cycle"-
Feature korrekt kodiert (0=OFF/1=Manual/2=Auto), aber "cycle" auf Button 2/3
entfaellt komplett (siehe drivers/panasonic_aw.py-Klassendocstring) -- jetzt
als je ein Toggle pro Zielzustand (`knee_manual`/`knee_auto`), "off" ist bei
beiden `OSL:45:0`. "on" ist hier je eine Liste (`["OSL:45:1", "OSA:2D:1"]`
bzw. `["OSL:45:1", "OSA:2D:2"]`), da fuer diese Kamera zwei Kommandos noetig
sind -- `trigger_button_feature()` akzeptiert seit dieser Korrektur sowohl
einen einzelnen Kommando-String als auch eine Liste.

Query-Ergaenzung (2026-07-18, alle direkt in `AW-UE160_InterfaceSpecification_
E.pdf` als Request/Response-Paar verifiziert): `query`/`query_on_value` bei
`auto_focus` (`QAF`), `drs` (`QSA:0D`), `flare` (`QSA:11`), `gamma`
(`QSA:0A`), `linear_matrix` (`QSL:6C`), `matrix` (`QSA:84`), `osd` (`QUS`)
und `white_clip` (`QSA:2E`). **Bewusst NICHT ergaenzt bei `knee_manual`/
`knee_auto`:** der Zustand haengt hier an ZWEI Kommandos (`OSL:45`
schaltet Knee ueberhaupt scharf, `OSA:2D` waehlt Manual/Auto) -- ob `OSA:2D`
seinen zuletzt gesetzten Wert behaelt, wenn `OSL:45` auf 0 steht, oder ob
die Kamera dann etwas anderes zurueckliefert, ist in der PDF nicht
dokumentiert und nicht verifizierbar. Eine Abfrage nur ueber `QSA:2D` waere
eine Vermutung ueber dieses Zusammenspiel -- deshalb bleibt der Zustand
dieser beiden Features weiterhin nur lokal getrackt (wie vor dieser
Korrektur), bis das an echter Hardware verifiziert werden kann.

Iris F-Nummer (2026-07-23, `QIF`/`OIF`, live gegen eine reale AW-UE160
kalibriert -- siehe drivers/panasonic_aw.py::_F_NUMBER_DATA_MIN): eigene PDF
bestaetigt die Ankerpunkte 0Eh=F1.4/A0h=F16/FFh=CLOSE.
"""

CAMERA_ID = "AW-UE160"
DISPLAY_NAME = "Panasonic AW-UE160"

SUPPORTS_IRIS_F_NUMBER = True

GAIN_MIN_DB = -6
GAIN_MAX_DB = 12
GAIN_STEP_DB = 1  # kontinuierlich, 1 Hex-Schritt = 1 dB

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

# ND-Filter (OFT/QFT), Werte/Reihenfolge aus `AW-UE160_InterfaceSpecification_
# E.pdf`, eigene Tabelle (Data value 0-3 -> THROUGH/1/4/1/16/1/64).
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4"),
    (2, "1/16"),
    (3, "1/64"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs": {"kind": "toggle", "on": "OSA:0D:1", "off": "OSA:0D:0", "query": "QSA:0D", "query_on_value": "1"},
    "flare": {"kind": "toggle", "on": "OSA:11:1", "off": "OSA:11:0", "query": "QSA:11", "query_on_value": "1"},
    "gamma": {"kind": "toggle", "on": "OSA:0A:1", "off": "OSA:0A:0", "query": "QSA:0A", "query_on_value": "1"},
    "knee_manual": {"kind": "toggle", "on": ["OSL:45:1", "OSA:2D:1"], "off": "OSL:45:0"},
    "knee_auto": {"kind": "toggle", "on": ["OSL:45:1", "OSA:2D:2"], "off": "OSL:45:0"},
    "linear_matrix": {"kind": "toggle", "on": "OSL:6C:1", "off": "OSL:6C:0", "query": "QSL:6C", "query_on_value": "1"},
    "matrix": {"kind": "toggle", "on": "OSA:84:1", "off": "OSA:84:0", "query": "QSA:84", "query_on_value": "1"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "flare": "Flare",
    "gamma": "Gamma",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "linear_matrix": "Linear Matrix",
    "matrix": "Matrix",
    "osd": "OSD",
    "white_clip": "White Clip",
}
