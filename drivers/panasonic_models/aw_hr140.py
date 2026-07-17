"""drivers/panasonic_models/aw_hr140.py -- Panasonic AW-HR140.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_hr140.py`s
UI_BUTTONS/UI_BUTTON_LABELS (identisch zu AW-HE120/HE130, aber als eigenes
Modell/eigene Datei gefuehrt, analog zur Quelle).

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14, gilt fuer "AW-HR140/AW-UE150"): Gain kontinuierlich 0-42dB (OGU
08h=0dB .. 32h=42dB, 1dB-Schritte); Pedestal ueber `OTP`/`QTP`, Bereich
-150..+150, Data = 0x96 + Wert -- gleiche Pedestal-Familie wie AW-HE120/
AW-HE130 (NICHT die `OSJ:0F`-Familie von AW-UE150 -- diese Tabelle listet
HR140 nur beim Gain gemeinsam mit UE150, beim Pedestal aber separat bei der
OTP-Gruppe).
"""

CAMERA_ID = "AW-HR140"
CAMERA_ID_ALIASES = ["AW-HR140E", "AW-HR140N"]
DISPLAY_NAME = "Panasonic AW-HR140"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 42
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
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
    "knee": {"kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0"},
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
