"""drivers/panasonic_models/aw_ue70.py -- Panasonic AW-UE70 series.

Gleicher Befehlssatz wie AW-HE40 (siehe `aw_he40.py`) -- nur CAMERA_ID/
CAMERA_ID_ALIASES/DISPLAY_NAME unterscheiden sich, analog zu
`C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue70.py`.
"""

from drivers.panasonic_models.aw_he40 import (  # noqa: F401
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

CAMERA_ID = "AW-UE70"
CAMERA_ID_ALIASES = ["AW-UN70", "AW-UE65", "AW-UE63"]
DISPLAY_NAME = "Panasonic AW-UE70"
