"""drivers/panasonic_models/aw_he50.py -- Panasonic AW-HE50 series.

Older, simpler model than HE120/HE130 -- no knee feature. Gain only moves
in 3dB steps (0-18dB). Pedestal uses the older `OTP`/`QTP` command (not
`OSJ:0F`). `drs` has 3 valid values (Off/Low/High, data value 2 unused). No
physical ND filter, no `white_clip`/iris-F-number support.
"""

CAMERA_ID = "AW-HE50"
CAMERA_ID_ALIASES = ["AW-HE50H", "AW-HE50E", "AW-HE50S"]

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
GAIN_STEP_DB = 3

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -10
PEDESTAL_MAX = 10
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 15
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_high": "DRS: High",
    "osd": "OSD",
}
