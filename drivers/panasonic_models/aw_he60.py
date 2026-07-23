"""drivers/panasonic_models/aw_he60.py -- Panasonic AW-HE60 series.

Gleicher Befehlssatz wie AW-HE50 (siehe `aw_he50.py`) -- nur CAMERA_ID/
CAMERA_ID_ALIASES/DISPLAY_NAME unterscheiden sich, analog zu
`C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he60.py`.

Iris F-Nummer: bewusst KEIN SUPPORTS_IRIS_F_NUMBER, siehe aw_he50.py --
"Iris F value" ist laut derselben PDF nur fuer AK-UB300/AW-UE150
dokumentiert, nicht fuer AW-HE60.
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
DISPLAY_NAME = "Panasonic AW-HE60"
