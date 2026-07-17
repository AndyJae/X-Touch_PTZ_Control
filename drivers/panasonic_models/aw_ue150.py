"""drivers/panasonic_models/aw_ue150.py -- Panasonic AW-UE150A.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue150.py`s
UI_BUTTONS/UI_BUTTON_LABELS. CAMERA_ID ist "AW-UE150A" (nicht "AW-UE150") --
so in der Quelle gefuehrt, "AW-UE150" ist dort ein Alias, keine
Tippabweichung. Einziges hier portiertes Modell mit "adaptive_matrix"; Knee
ist wie bei AW-UE160 ein 3-Stufen-Cycle statt Toggle.

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14, "applicable models": AW-UE150/AW-UE155/AW-UN145 -- deckt also genau
CAMERA_ID + CAMERA_ID_ALIASES hier ab): Gain kontinuierlich 0-42dB (OGU
08h=0dB .. 32h=42dB, gleiche Tabelle wie AW-HR140) -- ACHTUNG, das ist NICHT
dieselbe Gain-Formel wie AW-UE160 (dort -6..+12dB, eigene PDF-Quelle).
Pedestal ueber `OSJ:0F`/`QSJ:0F` Master Pedestal, Bereich -200..+200,
Data = 0x800 + Wert -- explizit "Only enabled for the AW-UE150" laut
Batch-Tabelle, gleiches Kommando/Format wie bei AW-UE160.
"""

CAMERA_ID = "AW-UE150A"
CAMERA_ID_ALIASES = ["AW-UE150", "AW-UE155", "AW-UN145"]
DISPLAY_NAME = "Panasonic AW-UE150A"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "adaptive_matrix": {"kind": "toggle", "on": "OSJ:4F:1", "off": "OSJ:4F:0"},
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
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
    "adaptive_matrix": "Adaptive Matrix",
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "knee": "Knee",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
