"""drivers/panasonic_models/aw_he60.py -- Panasonic AW-HE60 series.

Same command set as AW-HE50 (see `aw_he50.py`) -- only CAMERA_ID/
CAMERA_ID_ALIASES differ. No iris-F-number support.
"""

from drivers.panasonic_models.aw_he50 import (  # noqa: F401
    BUTTON_FEATURE_LABELS,
    BUTTON_FEATURES,
    GAIN_MAX_DB,
    GAIN_MIN_DB,
    GAIN_STEP_DB,
    PEDESTAL_CENTER_DATA,
    PEDESTAL_COMMAND,
    PEDESTAL_DATA_WIDTH,
    PEDESTAL_MAX,
    PEDESTAL_MIN,
    PEDESTAL_QUERY_COMMAND,
    PEDESTAL_SCALE,
)

CAMERA_ID = "AW-HE60"
CAMERA_ID_ALIASES = ["AW-HE60H", "AW-HE60E", "AW-HE60S"]
