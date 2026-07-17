"""drivers/panasonic_models -- Modell-Katalog fuer Panasonic-Kamera-Buttons (Spec §9a).

Ein Modul je Kameramodell, portiert aus der verifizierten Referenzquelle
`C:\\smart_reset_work\\camera_plugins\\panasonic\\*.py` (Attribute UI_BUTTONS/
UI_BUTTON_LABELS -> hier BUTTON_FEATURES/BUTTON_FEATURE_LABELS, Struktur an
`PanasonicAWDriver.trigger_button_feature`/`cycle_button_feature` angepasst:
{"kind": "toggle"/"trigger"/"cycle", ...} statt {"on"/"off"} bzw. {"cmd"}
bzw. {"cycle"}). Nur Button-Features werden portiert -- RESET_COMMANDS/
UI_LAYOUT/UI_DROPDOWNS aus der Quelle gehoeren zu deren eigenem Reset-Tool
und haben in PTZ_Control keine Entsprechung (Button 2/3 sind hier frei aus
dem Katalog zuweisbar, kein fester Grid/Dropdown-Aufbau).

Alias-Module (z.B. aw_he60.py fuer aw_he50.py) re-exportieren BUTTON_FEATURES/
BUTTON_FEATURE_LABELS vom Basismodul, genau wie im Original per
`from ... import *` -- gleiche Werte, andere CAMERA_ID/CAMERA_ID_ALIASES.
"""
