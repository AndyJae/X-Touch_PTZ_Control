"""drivers/panasonic_models/aw_ue40.py -- Panasonic AW-UE40.

Gleicher Befehlssatz wie AW-UE80 (siehe `aw_ue80.py`) -- nur CAMERA_ID/
DISPLAY_NAME unterscheiden sich, analog zu
`C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue40.py`.
"""

from drivers.panasonic_models.aw_ue80 import (  # noqa: F401
    BUTTON_FEATURE_LABELS,
    BUTTON_FEATURES,
    GAIN_MAX_DB,
    GAIN_MAX_DB_SUPER_GAIN_OFF,
    GAIN_MIN_DB,
    GAIN_STEP_DB,
    ND_FILTER_OPTIONS,
    PEDESTAL_CENTER_DATA,
    PEDESTAL_COMMAND,
    PEDESTAL_DATA_WIDTH,
    PEDESTAL_MAX,
    PEDESTAL_MIN,
    PEDESTAL_QUERY_COMMAND,
    PEDESTAL_SCALE,
    SUPER_GAIN_QUERY_COMMAND,
    SUPPORTS_IRIS_F_NUMBER,
)

CAMERA_ID = "AW-UE40"
DISPLAY_NAME = "Panasonic AW-UE40"
