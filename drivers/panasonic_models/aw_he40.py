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
AW-HE40/AW-UE70/AW-HE42"): 3-Werte-Cycle (0=Off/1=Low/3=High, Data-Wert 2
nicht belegt), nicht der bisherige einfache Toggle -- siehe aw_he50.py fuer
denselben Befund.
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
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {
        "kind": "cycle",
        "cycle": [
            {"label": "OFF", "cmd": ["OSE:33:0"]},
            {"label": "LOW", "cmd": ["OSE:33:1"]},
            {"label": "HIGH", "cmd": ["OSE:33:3"]},
        ],
    },
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
    "night_mode": {"kind": "toggle", "on": "OSI:1A:1", "off": "OSI:1A:0"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "white_clip": "White Clip",
    "osd": "OSD",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
    "night_mode": "Night Mode",
}
