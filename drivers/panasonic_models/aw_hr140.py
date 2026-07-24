"""drivers/panasonic_models/aw_hr140.py -- Panasonic AW-HR140.

Pedestal uses `OTP`/`QTP` (range -150..+150, same family as AW-HE120/
AW-HE130 -- not AW-UE150's `OSJ:0F` family, despite sharing its gain range).
`knee` has 3 valid values (Off/Manual/Auto); `knee_manual`/`knee_auto` are
mutually exclusive toggles (`exclusive_with`, see core/application.py::
apply_button_action()). No iris-F-number support.
"""

CAMERA_ID = "AW-HR140"
CAMERA_ID_ALIASES = ["AW-HR140E", "AW-HR140N"]

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

# ND filter (OFT/QFT): only three valid values (0/3/4) for this group,
# data 1/2 don't exist.
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (3, "1/64"),
    (4, "1/8"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "knee_manual": {
        "kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0",
        "query": "QSA:2D", "query_on_value": "1", "exclusive_with": ["knee_auto"],
    },
    "knee_auto": {
        "kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0",
        "query": "QSA:2D", "query_on_value": "2", "exclusive_with": ["knee_manual"],
    },
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
}
