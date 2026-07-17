"""drivers/panasonic_models/aw_he120.py -- Panasonic AW-HE120.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he120.py`s
UI_BUTTONS/UI_BUTTON_LABELS. `knee` ist hier ein einfacher Toggle (nicht wie
bei AW-UE160 ein 3-Stufen-Cycle) -- so in der Quelle dokumentiert.

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14): Gain kontinuierlich 0-18dB (OGU 08h=0dB .. 1Ah=18dB, 1dB-Schritte);
Pedestal ueber `OTP`/`QTP` wie bei HE50/HE60, aber eigene Formel/Bereich
-150..+150, Data = 0x96 + Wert (Ankerpunkte 000h=-150/096h=0/12Ch=+150) --
gleiche Pedestal-Familie wie AW-HE130/AW-HR140.
"""

CAMERA_ID = "AW-HE120"
CAMERA_ID_ALIASES = ["AW-HE125", "AW-HE120W", "AW-HE120K"]
DISPLAY_NAME = "Panasonic AW-HE120"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
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
