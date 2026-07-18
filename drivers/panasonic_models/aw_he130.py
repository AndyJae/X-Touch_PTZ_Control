"""drivers/panasonic_models/aw_he130.py -- Panasonic AW-HE130.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he130.py`s
UI_BUTTONS/UI_BUTTON_LABELS (identisch zu AW-HE120, aber als eigenes
Modell/eigene Datei gefuehrt, analog zur Quelle).

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14): Gain kontinuierlich 0-36dB (OGU 08h=0dB .. 2Ch=36dB, 1dB-Schritte);
Pedestal ueber `OTP`/`QTP`, Bereich -150..+150, Data = 0x96 + Wert -- gleiche
Pedestal-Familie wie AW-HE120/AW-HR140.

DRS/Knee-Korrektur (2026-07-18, dieselbe PDF, §3.2.30 "Knee settings" +
DRS-Tabelle): `drs` hat 4 gueltige Werte (0=Off/1=Low/2=Mid/3=High); `knee`
(`OSA:2D`) ist laut §3.2.30 explizit "Only supported by the AW-HE130/
AW-HR140/AW-UE150/AK-UB300" -- fuer AW-HE130 also korrekt vorhanden, mit
3 gueltigen Werten (0=OFF/1=MANUAL/2=AUTO). Beide als je ein Toggle pro
Zielzustand (`drs_low`/`drs_mid`/`drs_high`, `knee_manual`/`knee_auto`)
statt eigener "cycle"-Features (Nutzerentscheid 2026-07-18, siehe
drivers/panasonic_aw.py-Klassendocstring) -- vorher beide faelschlich als
Toggle bzw. Cycle mit falscher Semantik fuer Button 2/3 gefuehrt.

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `auto_focus`
(`QAF`), `drs_low`/`drs_mid`/`drs_high` (`QSE:33`), `knee_manual`/
`knee_auto` (`QSA:2D`), `osd` (`QUS`) und `white_clip` (`QSA:2E`) -- alle
direkt in der o. g. PDF als Request/Response-Paar verifiziert.
"""

CAMERA_ID = "AW-HE130"
CAMERA_ID_ALIASES = ["AW-HE135", "AW-HE130W", "AW-HE130K"]
DISPLAY_NAME = "Panasonic AW-HE130"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 36
GAIN_STEP_DB = 1

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -150
PEDESTAL_MAX = 150
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "knee_manual": {"kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "1"},
    "knee_auto": {"kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "2"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_mid": "DRS: Mid",
    "drs_high": "DRS: High",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
