"""drivers/panasonic_models/aw_he50.py -- Panasonic AW-HE50 series.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he50.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Aelteres, einfacheres Modell als HE120/HE130 --
kein Knee-Button (Quelle hat dafuer keinen Eintrag).

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14, gilt fuer "AW-HE50/AW-HE60"): Gain nur in 3dB-Schritten 0-18dB
(OGU 08h=0dB .. 1Ah=18dB, disabled bei FullAuto -> ER3); Pedestal ueber das
aeltere `OTP`/`QTP`-Kommando (nicht `OSJ:0F` wie bei UE150/UE160), Bereich
-10..+10, Data = 0x96 + Wert*15 (Ankerpunkte 000h=-10/096h=0/12Ch=+10).
"""

CAMERA_ID = "AW-HE50"
CAMERA_ID_ALIASES = ["AW-HE50H", "AW-HE50E", "AW-HE50S"]
DISPLAY_NAME = "Panasonic AW-HE50"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
GAIN_STEP_DB = 3

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -10
PEDESTAL_MAX = 10
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 15
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
