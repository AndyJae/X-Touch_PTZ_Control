"""drivers/panasonic_models/aw_he120.py -- Panasonic AW-HE120.

Pedestal uses `OTP`/`QTP` (range -150..+150, same family as AW-HE130/
AW-HR140). No `knee`/`white_clip`/iris-F-number support -- those are
documented as exclusive to AW-HE130/AW-HR140/AW-UE150(/AK-UB300).
"""

CAMERA_ID = "AW-HE120"
CAMERA_ID_ALIASES = ["AW-HE125", "AW-HE120W", "AW-HE120K"]

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
GAIN_STEP_DB = 1

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -150
PEDESTAL_MAX = 150
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

# ND filter (OFT/QFT): data 0-3 -> Through/1/4/1/16/1/64.
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4"),
    (2, "1/16"),
    (3, "1/64"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_mid": "DRS: Mid",
    "drs_high": "DRS: High",
    "osd": "OSD",
}
