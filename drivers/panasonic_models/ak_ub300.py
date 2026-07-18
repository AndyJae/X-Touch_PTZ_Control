"""drivers/panasonic_models/ak_ub300.py -- Panasonic AK-UB300.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\ak_ub300.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Studio-Box-Kamera der AK-Serie (nicht AW-PTZ-
Serie) -- CLAUDE.md nennt "Panasonic AW-Serie, besonders AW-UE160" als
Referenz-Driver-Scope, dieses Modell weicht beim Gain-Befehl bekanntermassen
ab (`OGS`/Bereichsauswahl statt `OGU`, siehe ptz-shading-tool-spec.md §7.2) --
das betrifft aber nur Gain/Pedestal (separates, noch offenes Thema), nicht
den hier portierten Button-Katalog, der ueber denselben CGI-Mechanismus
laeuft. Kein "auto_focus"-Eintrag in der Quelle (B4-Objektiv-Anschluss ohne
Autofokus-Steuerung ueber dieses Protokoll); dafuer "super_gain", das kein
anderes hier portiertes Modell hat.

Gain (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/§3.2.7):
bewusst KEIN GAIN_MIN_DB/GAIN_MAX_DB/GAIN_STEP_DB hier -- AK-UB300 nutzt
`OGS:[Data]` (Bereichsauswahl LOW/MID/HIGH/S.GAIN1/S.GAIN2) + `OSA:50/51/52`
(dB je Bereich), strukturell inkompatibel mit dem einfachen
`set_gain_db(db)`/`step_gain(delta)`-Interface der anderen Modelle. Kamera
hat also (noch) keine Encoder-Gain-Funktion -- siehe CLAUDE.md Offene Punkte.

Pedestal (§3.2.14): eigenes `OSG:4A`/`QSG:4A`-Kommando, Bereich -99..+99,
Data = 0x80 + Wert (Ankerpunkte 1Dh=-99/80h=0/E3h=+99) -- diese Formel ist
mit dem einfachen zentrierten Set/Step-Interface kompatibel, daher hier
(anders als Gain) doch abgebildet.

Knee-Korrektur (2026-07-18, §3.2.30 "Knee settings"): Knee Mode ist dort
explizit "Only supported by the AW-HE130/AW-HR140/AW-UE150/AK-UB300" mit
3 Werten (0=OFF/1=MANUAL/2=AUTO, `OSA:2D`) -- AK-UB300 nutzt denselben
Top-Level-Befehl wie die AW-Modelle (nur die abhaengigen Knee-Point/-Slope-
Werte haben eine eigene, AK-UB300-spezifische Kodierung, die hier nicht
relevant ist). Bisher faelschlich als Toggle gefuehrt, jetzt 3-Werte-Cycle.

`drs` (`OSE:33`) bewusst NICHT angefasst: die DRS-Tabelle derselben PDF
nennt nur "AW-HE50/AW-HE60/AW-HE40/AW-UE70/AW-HE42" (3 Werte) und
"AW-HE120/AW-HE130/AW-HR140/AW-UE150" (4 Werte) -- AK-UB300 wird dort in
keiner der beiden Gruppen erwaehnt. Ob/wie AK-UB300 DRS ueberhaupt
unterstuetzt, ist damit unbestaetigt; der bisherige Toggle wird deshalb
weder bestaetigt noch korrigiert (kein erfundener Wert in beide Richtungen).
"""

CAMERA_ID = "AK-UB300"
CAMERA_ID_ALIASES = ["AK-UB300GJ", "AK-UB300EJ"]
DISPLAY_NAME = "Panasonic AK-UB300"

PEDESTAL_COMMAND = "OSG:4A"
PEDESTAL_QUERY_COMMAND = "QSG:4A"
PEDESTAL_MIN = -99
PEDESTAL_MAX = 99
PEDESTAL_CENTER_DATA = 0x80
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 2

BUTTON_FEATURES: dict[str, dict] = {
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
    "knee": {
        "kind": "cycle",
        "cycle": [
            {"label": "OFF", "cmd": ["OSA:2D:0"]},
            {"label": "Manual", "cmd": ["OSA:2D:1"]},
            {"label": "Auto", "cmd": ["OSA:2D:2"]},
        ],
    },
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0"},
    "super_gain": {"kind": "toggle", "on": "OSI:28:1", "off": "OSI:28:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "knee": "Knee",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
    "super_gain": "Super Gain",
    "osd": "OSD",
}
