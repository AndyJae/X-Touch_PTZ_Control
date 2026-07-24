"""drivers/panasonic_models/aw_he42.py -- Panasonic AW-HE42 series.

Same command set as AW-HE40 (see `aw_he40.py`) -- only CAMERA_ID/
CAMERA_ID_ALIASES differ, except this model does have a physical ND filter
(5 values including Auto), defined locally rather than re-exported since
AW-HE40 has none. No iris-F-number support.
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

CAMERA_ID = "AW-HE42"
CAMERA_ID_ALIASES = ["AW-HE75", "AW-HE68", "AW-HE42HE"]

ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4 ND"),
    (2, "1/16 ND"),
    (3, "1/64 ND"),
    (8, "AUTO ND"),
]
