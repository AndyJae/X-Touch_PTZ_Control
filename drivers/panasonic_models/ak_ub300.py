"""drivers/panasonic_models/ak_ub300.py -- Panasonic AK-UB300.

Studio box camera (AK series, not AW-PTZ). No GAIN_MIN_DB/MAX_DB/STEP_DB
here: this model uses `OGS:[Data]` range selection (LOW/MID/HIGH/S.GAIN1-2)
plus per-range dB commands, structurally incompatible with the simple
set_gain_db(db)/step_gain(delta) interface the other models use -- no
encoder gain function for this camera. Pedestal uses its own `OSG:4A`/
`QSG:4A` command (range -99..+99), which does fit the simple interface. No
`auto_focus` (B4 lens mount has no autofocus over this protocol); has
`super_gain`, which no other model here has.
"""

CAMERA_ID = "AK-UB300"
CAMERA_ID_ALIASES = ["AK-UB300GJ", "AK-UB300EJ"]

SUPPORTS_IRIS_F_NUMBER = True

PEDESTAL_COMMAND = "OSG:4A"
PEDESTAL_QUERY_COMMAND = "QSG:4A"
PEDESTAL_MIN = -99
PEDESTAL_MAX = 99
PEDESTAL_CENTER_DATA = 0x80
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 2

# ND filter (OFT/QFT): data 0-3 -> Clear/1/4/1/16/1/64.
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "CLEAR"),
    (1, "1/4"),
    (2, "1/16"),
    (3, "1/64"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
    "knee_manual": {
        "kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0",
        "query": "QSA:2D", "query_on_value": "1", "exclusive_with": ["knee_auto"],
    },
    "knee_auto": {
        "kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0",
        "query": "QSA:2D", "query_on_value": "2", "exclusive_with": ["knee_manual"],
    },
    "super_gain": {"kind": "toggle", "on": "OSI:28:1", "off": "OSI:28:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "super_gain": "Super Gain",
    "osd": "OSD",
}
