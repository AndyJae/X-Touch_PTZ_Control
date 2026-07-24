"""drivers/panasonic_models/aw_he145.py -- Panasonic AW-HE145.

CAMERA_ID is "AW-HE145" (real `QID` response), with "AW-UE145" kept as an
alias. Button catalog re-exported from `aw_ue150.py`, which documents the
same camera family. Gain/pedestal are otherwise identical to AW-UE150A.
"""

from drivers.panasonic_models.aw_ue150 import BUTTON_FEATURE_LABELS, BUTTON_FEATURES  # noqa: F401

CAMERA_ID = "AW-HE145"
CAMERA_ID_ALIASES = ["AW-UE145", "AW-UE150HE", "AW-UE150HE145"]

SUPPORTS_IRIS_F_NUMBER = True

GAIN_MIN_DB = -3
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1
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
