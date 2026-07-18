"""drivers/panasonic_models/aw_he40.py -- Panasonic AW-HE40 series.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he40.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Einziges Modell mit "night_mode" (Day/Night
IR-Cut-Filter) im portierten Katalog.

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14, gilt fuer "AW-HE40/AW-UE70/AW-HE42"): Gain nur in 3dB-Schritten
0-48dB (OGU 08h=0dB .. 38h=48dB, disabled bei FullAuto -> ER3); Pedestal
ueber das aeltere `OTP`/`QTP`-Kommando (nicht `OSJ:0F`), Bereich -10..+10,
Data = 0x96 + Wert*15 -- gleiche Pedestal-Familie wie AW-HE50/AW-HE60.

DRS-Korrektur (2026-07-18, gleiche Quelle, Tabelle fuer "AW-HE50/AW-HE60/
AW-HE40/AW-UE70/AW-HE42"): 3 gueltige Werte (0=Off/1=Low/3=High, Data-Wert 2
nicht belegt), als je ein Toggle pro Zielzustand (`drs_low`/`drs_high`)
statt einem "cycle"-Feature -- siehe aw_he50.py fuer denselben Befund und
die Begruendung (Nutzerentscheid 2026-07-18).

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `auto_focus`
(`QAF`), `drs_low`/`drs_high` (`QSE:33`), `white_clip` (`QSA:2E`), `osd`
(`QUS`) und `night_mode` (`QSI:1A`) -- alle fuenf direkt in der
`HDIntegratedCamera_InterfaceSpecifications-E.pdf` als Request/Response-Paar
verifiziert.
"""

CAMERA_ID = "AW-HE40"
CAMERA_ID_ALIASES = [
    "AW-HE40S", "AW-HE40W", "AW-HE40HE",
    "AW-HE65", "AW-HE65H", "AW-HE65E",
    "AW-HE70", "AW-HE70HE",
    "AW-HE48", "AW-HE58",
    "AW-HE35", "AW-HE38",
    "AW-HN38", "AW-HN40", "AW-HN65", "AW-HN70",
]
DISPLAY_NAME = "Panasonic AW-HE40"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 48
GAIN_STEP_DB = 3

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -10
PEDESTAL_MAX = 10
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 15
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "night_mode": {"kind": "toggle", "on": "OSI:1A:1", "off": "OSI:1A:0", "query": "QSI:1A", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_high": "DRS: High",
    "white_clip": "White Clip",
    "osd": "OSD",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
    "night_mode": "Night Mode",
}
