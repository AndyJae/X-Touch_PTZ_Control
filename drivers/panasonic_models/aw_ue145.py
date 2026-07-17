"""drivers/panasonic_models/aw_ue145.py -- Panasonic AW-UE145.

Gleicher Befehlssatz wie AW-UE150A (siehe `aw_ue150.py`) -- nur CAMERA_ID/
CAMERA_ID_ALIASES/DISPLAY_NAME unterscheiden sich, analog zu
`C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue145.py`.

Gain/Pedestal: bewusst NICHT von `aw_ue150.py` mit-importiert. Die
"applicable models" von `HDIntegratedCamera_InterfaceSpecifications-E.pdf`
fuehren die UE150-Serie explizit nur als "AW-UE150/AW-UE155/AW-UN145" --
AW-UE145 ist dort nicht gelistet (auch nicht in der AW-UE160-PDF). Der
gemeinsame Button-Katalog stammt aus `smart_reset_work` (nur dort als
gleiche Baureihe gefuehrt), das ist keine Bestaetigung fuer identische
Gain-/Pedestal-Werte -- daher hier bewusst KEIN GAIN_*/PEDESTAL_* (kein
erfundener Wert). Siehe CLAUDE.md Offene Punkte.
"""

from drivers.panasonic_models.aw_ue150 import BUTTON_FEATURE_LABELS, BUTTON_FEATURES  # noqa: F401

CAMERA_ID = "AW-UE145"
CAMERA_ID_ALIASES = ["AW-UE150HE", "AW-UE150HE145"]
DISPLAY_NAME = "Panasonic AW-UE145"
