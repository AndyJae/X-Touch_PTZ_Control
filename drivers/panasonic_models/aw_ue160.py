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
"""

CAMERA_ID = "AW-UE160"
DISPLAY_NAME = "Panasonic AW-UE160"

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

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {"kind": "toggle", "on": "OSA:0D:1", "off": "OSA:0D:0"},
    "flare": {"kind": "toggle", "on": "OSA:11:1", "off": "OSA:11:0"},
    "gamma": {"kind": "toggle", "on": "OSA:0A:1", "off": "OSA:0A:0"},
    "knee": {
        "kind": "cycle",
        "cycle": [
            {"label": "OFF", "cmd": ["OSL:45:0"]},
            {"label": "Manual", "cmd": ["OSL:45:1", "OSA:2D:1"]},
            {"label": "Auto", "cmd": ["OSL:45:1", "OSA:2D:2"]},
        ],
    },
    "linear_matrix": {"kind": "toggle", "on": "OSL:6C:1", "off": "OSL:6C:0"},
    "matrix": {"kind": "toggle", "on": "OSA:84:1", "off": "OSA:84:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "flare": "Flare",
    "gamma": "Gamma",
    "knee": "Knee",
    "linear_matrix": "Linear Matrix",
    "matrix": "Matrix",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
