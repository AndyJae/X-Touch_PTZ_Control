"""drivers/panasonic_models/aw_ue160.py -- Panasonic AW-UE160.

Knee is modeled as two toggles (`knee_manual`/`knee_auto`) rather than a
single cycling feature, since this camera needs two commands per target
state (`OSL:45` arms knee, `OSA:2D` selects manual/auto). No query is
provided for these two: the state depends on both commands together, and
how they interact when `OSL:45` is off is undocumented.
"""

CAMERA_ID = "AW-UE160"

SUPPORTS_IRIS_F_NUMBER = True

GAIN_MIN_DB = -6
GAIN_MAX_DB = 12
GAIN_STEP_DB = 1  # continuous, 1 hex step = 1 dB

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

# ND filter (OFT/QFT): data value 0-3 -> THROUGH/1/4/1/16/1/64.
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4"),
    (2, "1/16"),
    (3, "1/64"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs": {"kind": "toggle", "on": "OSA:0D:1", "off": "OSA:0D:0", "query": "QSA:0D", "query_on_value": "1"},
    "flare": {"kind": "toggle", "on": "OSA:11:1", "off": "OSA:11:0", "query": "QSA:11", "query_on_value": "1"},
    "gamma": {"kind": "toggle", "on": "OSA:0A:1", "off": "OSA:0A:0", "query": "QSA:0A", "query_on_value": "1"},
    "knee_manual": {"kind": "toggle", "on": ["OSL:45:1", "OSA:2D:1"], "off": "OSL:45:0"},
    "knee_auto": {"kind": "toggle", "on": ["OSL:45:1", "OSA:2D:2"], "off": "OSL:45:0"},
    "linear_matrix": {"kind": "toggle", "on": "OSL:6C:1", "off": "OSL:6C:0", "query": "QSL:6C", "query_on_value": "1"},
    "matrix": {"kind": "toggle", "on": "OSA:84:1", "off": "OSA:84:0", "query": "QSA:84", "query_on_value": "1"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "flare": "Flare",
    "gamma": "Gamma",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "linear_matrix": "Linear Matrix",
    "matrix": "Matrix",
    "osd": "OSD",
    "white_clip": "White Clip",
}
