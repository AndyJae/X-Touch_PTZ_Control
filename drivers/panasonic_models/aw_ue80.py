"""drivers/panasonic_models/aw_ue80.py -- Panasonic AW-UE80.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue80.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Keine CAMERA_ID_ALIASES in der Quelle -- die
verwandten Modelle UE30/UE40/UE50 sind dort eigene, sehr kleine Module mit
demselben Befehlssatz (siehe aw_ue30.py/aw_ue40.py/aw_ue50.py).

Gain/Pedestal (Quelle: `docs/specs/AW-UE80UE50UE40_InterfaceSpecification_
E.pdf`, dediziertes Dokument fuer "AW-UE80/UE50/UE40/UE30" gemeinsam -- gilt
also fuer alle vier hier gefuehrten Modelle, siehe aw_ue30.py/aw_ue40.py/
aw_ue50.py): Gain (`OGU`/`QGU`) kontinuierlich 08h=0dB .. 1Ah=18dB ..
32h=42dB (1dB-Schritte), 80h=AGC -- identische Ankerpunkte wie AW-HR140/
AW-UE150A/AW-UE100. Maximalwert an "Super Gain" (`OSI:28`, hier nicht als
Button-Feature portiert) gekoppelt: 0-36dB wenn aus, 0-42dB wenn an (wie bei
AW-UE100) -- seit Nutzerauftrag 2026-07-20 durchgesetzt (live gegen eine
echte AW-UE100 verifiziert, siehe aw_ue100.py und
PanasonicAWDriver.effective_gain_max_db). Pedestal ueber
`OSJ:0F`/`QSJ:0F` Master Pedestal, Data 738h=-200/800h=0/8C8h=+200 --
identisches Kommando/Format wie AW-UE100/AW-UE150A/AW-UE160.

DRS-Korrektur (2026-07-18, dieselbe PDF, Kap. 9): `drs` (`OSE:33`) hat
4 gueltige Werte (0=Off/1=Low/2=Mid/3=High) -- wie bei AW-UE100/AW-HE120/
130/HR140/AW-UE150A. Als je ein Toggle pro Zielzustand (`drs_low`/`drs_mid`/
`drs_high`) statt einem "cycle"-Feature (Nutzerentscheid 2026-07-18, siehe
drivers/panasonic_aw.py-Klassendocstring).

**Offener Punkt:** Kap. 8 ("Menu-Command Correspondance Table") dieser PDF
listet "Knee mode OSA:2D" als vorhandenes Menu, im Unterschied zum
bisherigen Katalog (kein `knee`-Eintrag). Die genaue Werte-/Label-Tabelle
(Kap. 9) liess sich aus dieser PDF beim Verifizieren nicht sauber extrahieren
(Tabellenlayout unklar/OCR-Kollision) -- ob 2-, 3- oder mehr Werte, ist
NICHT bestaetigt. Deshalb hier bewusst NICHT ergaenzt (kein erfundener
Wert), siehe CLAUDE.md Offene Punkte.

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `auto_focus`
(`QAF`), `drs_low`/`drs_mid`/`drs_high` (`QSE:33`), `osd` (`QUS`) und
`white_clip` (`QSA:2E`) -- alle direkt in dieser PDF als Request/Response-
Paar verifiziert.

Iris F-Nummer (2026-07-23, `QIF`/`OIF`, siehe drivers/panasonic_aw.py::
_F_NUMBER_DATA_MIN): dieselbe PDF fuehrt `QIF`/`OIF` mit den Ankerpunkten
0Eh=F1.4/1Ch=F2.8 -- die oberen Ankerpunkte (A0h=F16/FFh=CLOSE) sind in
dieser PDF nicht extra aufgefuehrt, kein Widerspruch zur bei AW-UE160/
AW-UE100/AW-UE150A/AW-HE145 bestaetigten Formel. Gilt fuer AW-UE80/UE50/
UE40/UE30 gemeinsam (siehe aw_ue30.py/aw_ue40.py/aw_ue50.py).
"""

CAMERA_ID = "AW-UE80"
DISPLAY_NAME = "Panasonic AW-UE80"

SUPPORTS_IRIS_F_NUMBER = True

GAIN_MIN_DB = 0
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1
# Super-Gain-Kopplung (Nutzerauftrag 2026-07-20, live gegen AW-UE100
# verifiziert, siehe aw_ue100.py): 36dB statt 42dB, solange Super Gain
# (`OSI:28`) aus ist.
GAIN_MAX_DB_SUPER_GAIN_OFF = 36
SUPER_GAIN_QUERY_COMMAND = "QSI:28"

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

# ND-Filter (OFT/QFT), `AW-UE80UE50UE40_InterfaceSpecification_E.pdf`
# (gilt fuer AW-UE80/UE50/UE40/UE30 gemeinsam): "Through/1/4 ND/1/16 ND/
# 1/64 ND" fuer Data 0-3 (raw-Extraktion, kein "8=Auto" fuer diese Gruppe --
# das gehoert laut derselben PDF-Familie nur zu AW-UE70/AW-HE42).
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4 ND"),
    (2, "1/16 ND"),
    (3, "1/64 ND"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_mid": "DRS: Mid",
    "drs_high": "DRS: High",
    "osd": "OSD",
    "white_clip": "White Clip",
}
