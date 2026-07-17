"""drivers/panasonic_models/aw_ue100.py -- Panasonic AW-UE100.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue100.py`s
UI_BUTTONS/UI_BUTTON_LABELS (identisch zu AW-HE120/HE130/HR140, aber als
eigenes Modell/eigene Datei gefuehrt, analog zur Quelle; keine
CAMERA_ID_ALIASES in der Quelle).

Gain/Pedestal: AW-UE100 kommt in keiner der beiden lokalen Referenz-PDFs
(`AW-UE160_InterfaceSpecification_E.pdf`, `HDIntegratedCamera_Interface
Specifications-E.pdf`) vor -- daher bewusst KEIN GAIN_*/PEDESTAL_* hier
(kein erfundener Wert). Siehe CLAUDE.md Offene Punkte."""

CAMERA_ID = "AW-UE100"
DISPLAY_NAME = "Panasonic AW-UE100"

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
