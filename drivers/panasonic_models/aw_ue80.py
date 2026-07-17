"""drivers/panasonic_models/aw_ue80.py -- Panasonic AW-UE80.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue80.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Keine CAMERA_ID_ALIASES in der Quelle -- die
verwandten Modelle UE30/UE40/UE50 sind dort eigene, sehr kleine Module mit
demselben Befehlssatz (siehe aw_ue30.py/aw_ue40.py/aw_ue50.py).

Gain/Pedestal: AW-UE80 (und UE30/UE40/UE50) kommt in keiner der beiden
lokalen Referenz-PDFs vor -- daher bewusst KEIN GAIN_*/PEDESTAL_* hier (kein
erfundener Wert). Siehe CLAUDE.md Offene Punkte.
"""

CAMERA_ID = "AW-UE80"
DISPLAY_NAME = "Panasonic AW-UE80"

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
