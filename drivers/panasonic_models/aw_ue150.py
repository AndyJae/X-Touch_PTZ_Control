"""drivers/panasonic_models/aw_ue150.py -- Panasonic AW-UE150A.

CAMERA_ID is "AW-UE150A" ("AW-UE150" is an alias, not a typo). The only
model here with "adaptive_matrix". `drs` has 4 valid values (Off/Low/Mid/
High), modeled as one toggle per target state. `knee` (`OSA:2D`) has 3
values (Off/Manual/Auto); `knee_manual`/`knee_auto` are mutually exclusive
toggles (`exclusive_with`, see core/application.py::apply_button_action())
so switching directly between them doesn't leave stale on-state for the
one not pressed.
"""

CAMERA_ID = "AW-UE150A"
CAMERA_ID_ALIASES = ["AW-UE150", "AW-UE155", "AW-UN145"]

SUPPORTS_IRIS_F_NUMBER = True

GAIN_MIN_DB = -3
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1
# Super-gain coupling: 36dB instead of 42dB while super gain (OSI:28) is off.
GAIN_MAX_DB_SUPER_GAIN_OFF = 36
SUPER_GAIN_QUERY_COMMAND = "QSI:28"

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

# ND filter (OFT/QFT): data 0-3 -> Through/1/4 ND/1/16 ND/1/64 ND.
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4 ND"),
    (2, "1/16 ND"),
    (3, "1/64 ND"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "adaptive_matrix": {"kind": "toggle", "on": "OSJ:4F:1", "off": "OSJ:4F:0", "query": "QSJ:4F", "query_on_value": "1"},
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
    "adaptive_matrix": "Adaptive Matrix",
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
