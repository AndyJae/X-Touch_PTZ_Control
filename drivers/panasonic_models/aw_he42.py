"""drivers/panasonic_models/aw_he42.py -- Panasonic AW-HE42 series.

Gleicher Befehlssatz wie AW-HE40 (siehe `aw_he40.py`) -- nur CAMERA_ID/
CAMERA_ID_ALIASES/DISPLAY_NAME unterscheiden sich, analog zu
`C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he42.py`.

ND-Filter (OFT/QFT) ist NICHT von `aw_he40.py` uebernommen (dort bewusst
kein Eintrag, siehe dortige Datei) -- `HDIntegratedCamera_
InterfaceSpecifications-E.pdf` §3.2.1.4 fuehrt "AW-UE70/AW-HE42" als eigene
Gruppe MIT ND-Filter (5 Werte inkl. Auto), waehrend AW-HE40 in derselben
PDF explizit ausgenommen ist (Menu-Tabelle 4-4-4: "OFT ND Filter *only
AW-UE70/AW-HE42"). Eigene, lokale Konstante statt Re-Export.

Iris F-Nummer: bewusst KEIN SUPPORTS_IRIS_F_NUMBER, siehe aw_he40.py --
"Iris F value" ist laut derselben PDF nur fuer AK-UB300/AW-UE150
dokumentiert, nicht fuer AW-HE42.
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
DISPLAY_NAME = "Panasonic AW-HE42"

ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "THROUGH"),
    (1, "1/4 ND"),
    (2, "1/16 ND"),
    (3, "1/64 ND"),
    (8, "AUTO ND"),
]
