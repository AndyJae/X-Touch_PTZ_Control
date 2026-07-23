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
3 gueltigen Werten (0=OFF/1=MANUAL/2=AUTO, `OSA:2D`) -- AK-UB300 nutzt
denselben Top-Level-Befehl wie die AW-Modelle (nur die abhaengigen
Knee-Point/-Slope-Werte haben eine eigene, AK-UB300-spezifische Kodierung,
die hier nicht relevant ist). Als je ein Toggle pro Zielzustand
(`knee_manual`/`knee_auto`) statt einem "cycle"-Feature (Nutzerentscheid
2026-07-18, siehe drivers/panasonic_aw.py-Klassendocstring).

`drs` (`OSE:33`) bewusst NICHT angefasst: die DRS-Tabelle derselben PDF
nennt nur "AW-HE50/AW-HE60/AW-HE40/AW-UE70/AW-HE42" (3 Werte) und
"AW-HE120/AW-HE130/AW-HR140/AW-UE150" (4 Werte) -- AK-UB300 wird dort in
keiner der beiden Gruppen erwaehnt. Ob/wie AK-UB300 DRS ueberhaupt
unterstuetzt, ist damit unbestaetigt; der bisherige Toggle wird deshalb
weder bestaetigt noch korrigiert (kein erfundener Wert in beide Richtungen).

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `knee_manual`/
`knee_auto` (`QSA:2D`) und `osd` (`QUS`) -- beide direkt in der o. g. PDF
fuer AK-UB300 als Request/Response-Paar verifiziert.

White-Clip-Korrektur (2026-07-18, Rest-Katalog-Pruefung): `white_clip`
(`OSA:2E`) wurde bisher faelschlich gefuehrt -- §3.2.31 "White Clip
settings" ist explizit **"Only supported by the AW-HE130/AW-HR140/
AW-UE150"**, AK-UB300 wird dort NICHT genannt (obwohl AK-UB300 laut
"Applicable models" auf S. 5 durchaus zu den von dieser PDF abgedeckten
Modellen gehoert -- die vorherige Formulierung "AK-UB300 kommt in keiner
dieser PDFs vor" war insofern ungenau). Der Eintrag wurde deshalb komplett
entfernt (kein erfundenes/falsches Feature).

`super_gain` (`OSI:28`, §3.2.6 "Gain setting", direkt im Anschluss an die
AK-UB300-exklusiven Bereichs-Gain-Kommandos `OSA:50/51/52`/`OSA:60`):
strukturell passend zu AK-UB300s LOW/MID/HIGH/S.GAIN1-3-Bereichsschema,
aber OHNE eigene "Only supported by AK-UB300"-Kennzeichnung auf der
`OSI:28`-Zeile selbst (anders als die Nachbarzeilen) -- die PDF-Tabelle an
dieser Stelle ist zudem beim Textextrakt stark spaltenverschoben
(mehrfach widerspruechliche Zuordnungen bei Testextraktion). Bleibt daher
weiterhin ohne Query (kein erfundener Wert) UND ohne endgueltige
Bestaetigung, ob `OSI:28` ueberhaupt AK-UB300-exklusiv ist -- Status
unveraendert zu vorher, nur die Begruendung praezisiert. `drs` bleibt aus
demselben Grund wie oben ohne Query.

Iris F-Nummer (2026-07-23, `QIF`/`OIF`, siehe drivers/panasonic_aw.py::
_F_NUMBER_DATA_MIN): §3.2.x "Iris F value" derselben PDF nennt AK-UB300
explizit **"Only supported by the AK-UB300/AW-UE150"** mit denselben
Ankerpunkten (0Eh=F1.4/1Ch=F2.8/38h=F5.6/A0h=F16/FFh=CLOSE) wie bei den
AW-Modellen -- ungewoehnlich fuer eine B4-Objektiv-Studiokamera, aber so in
der Tabelle dokumentiert (kein erfundener Wert).
"""

CAMERA_ID = "AK-UB300"
CAMERA_ID_ALIASES = ["AK-UB300GJ", "AK-UB300EJ"]
DISPLAY_NAME = "Panasonic AK-UB300"

SUPPORTS_IRIS_F_NUMBER = True

PEDESTAL_COMMAND = "OSG:4A"
PEDESTAL_QUERY_COMMAND = "QSG:4A"
PEDESTAL_MIN = -99
PEDESTAL_MAX = 99
PEDESTAL_CENTER_DATA = 0x80
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 2

# ND-Filter (OFT/QFT), `HDIntegratedCamera_InterfaceSpecifications-E.pdf`
# §3.2.1.4, Gruppe "AK-UB300": 0-3 -> Clear/1/4/1/16/1/64 (Label "Clear"
# statt "Through", sonst identisch zur Standard-Gruppe).
ND_FILTER_OPTIONS: list[tuple[int, str]] = [
    (0, "CLEAR"),
    (1, "1/4"),
    (2, "1/16"),
    (3, "1/64"),
]

BUTTON_FEATURES: dict[str, dict] = {
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0"},
    "knee_manual": {"kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "1"},
    "knee_auto": {"kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "2"},
    "super_gain": {"kind": "toggle", "on": "OSI:28:1", "off": "OSI:28:0"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_iris": "Auto Iris",
    "drs": "DRS",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "super_gain": "Super Gain",
    "osd": "OSD",
}
