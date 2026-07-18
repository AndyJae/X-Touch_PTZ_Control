"""drivers/panasonic_models/aw_he130.py -- Panasonic AW-HE130.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he130.py`s
UI_BUTTONS/UI_BUTTON_LABELS (identisch zu AW-HE120, aber als eigenes
Modell/eigene Datei gefuehrt, analog zur Quelle).

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14): Gain kontinuierlich 0-36dB (OGU 08h=0dB .. 2Ch=36dB, 1dB-Schritte);
Pedestal ueber `OTP`/`QTP`, Bereich -150..+150, Data = 0x96 + Wert -- gleiche
Pedestal-Familie wie AW-HE120/AW-HR140.

DRS/Knee-Korrektur (2026-07-18, dieselbe PDF, §3.2.30 "Knee settings" +
DRS-Tabelle): `drs` ist ein 4-Werte-Cycle (0=Off/1=Low/2=Mid/3=High) statt
Toggle. `knee` (`OSA:2D`) ist laut §3.2.30 explizit "Only supported by the
AW-HE130/AW-HR140/AW-UE150/AK-UB300" -- fuer AW-HE130 also korrekt
vorhanden, aber als 3-Werte-Cycle (0=OFF/1=MANUAL/2=AUTO), nicht als
Toggle (vorher faelschlich `{"kind": "toggle", ...}` aus smart_reset_work).
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
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {
        "kind": "cycle",
        "cycle": [
            {"label": "OFF", "cmd": ["OSE:33:0"]},
            {"label": "LOW", "cmd": ["OSE:33:1"]},
            {"label": "MID", "cmd": ["OSE:33:2"]},
            {"label": "HIGH", "cmd": ["OSE:33:3"]},
        ],
    },
    "knee": {
        "kind": "cycle",
        "cycle": [
            {"label": "OFF", "cmd": ["OSA:2D:0"]},
            {"label": "Manual", "cmd": ["OSA:2D:1"]},
            {"label": "Auto", "cmd": ["OSA:2D:2"]},
        ],
    },
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "knee": "Knee",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
