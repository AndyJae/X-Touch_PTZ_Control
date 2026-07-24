"""drivers/panasonic_models -- Model catalog for Panasonic camera buttons.

One module per camera model, each defining BUTTON_FEATURES/
BUTTON_FEATURE_LABELS: {"kind": "toggle"/"trigger", ...} entries consumed by
`PanasonicAWDriver.trigger_button_feature`.

Multi-value camera parameters (knee, DRS) are modeled as one "toggle" per
target state (e.g. "knee_manual"/"knee_auto") rather than a "cycle" feature
type, since button 2/3 only have a single-color LED.

Alias modules (e.g. aw_he60.py for aw_he50.py) re-export BUTTON_FEATURES/
BUTTON_FEATURE_LABELS from the base module -- same values, different
CAMERA_ID/CAMERA_ID_ALIASES.
"""
