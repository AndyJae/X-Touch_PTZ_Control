"""drivers/panasonic_models/aw_he40.py -- Panasonic AW-HE40 series.

The only model with "night_mode" (day/night IR-cut filter, `OSD:B2`). Gain
only moves in 3dB steps (0-48dB). Pedestal uses the older `OTP`/`QTP`
command (not `OSJ:0F`), same family as AW-HE50/AW-HE60. `drs` has 3 valid
values (Off/Low/High, data value 2 unused). No ND filter -- that's only on
AW-UE70/AW-HE42 (see those modules). No `white_clip`/iris-F-number support.
"""

CAMERA_ID = "AW-HE40"
CAMERA_ID_ALIASES = [
    "AW-HE40S", "AW-HE40W", "AW-HE40HE",
    "AW-HE65", "AW-HE65H", "AW-HE65E",
    "AW-HE70", "AW-HE70HE",
    "AW-HE48", "AW-HE58",
    "AW-HE35", "AW-HE38",
    "AW-HN38", "AW-HN40", "AW-HN65", "AW-HN70",
]

GAIN_MIN_DB = 0
GAIN_MAX_DB = 48
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
    "night_mode": {"kind": "toggle", "on": "OSD:B2:1", "off": "OSD:B2:0", "query": "QSD:B2", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_high": "DRS: High",
    "osd": "OSD",
    "night_mode": "Night Mode",
}
