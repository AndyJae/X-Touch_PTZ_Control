"""drivers/panasonic_models/aw_ue150.py -- Panasonic AW-UE150A.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue150.py`s
UI_BUTTONS/UI_BUTTON_LABELS. CAMERA_ID ist "AW-UE150A" (nicht "AW-UE150") --
so in der Quelle gefuehrt, "AW-UE150" ist dort ein Alias, keine
Tippabweichung. Einziges hier portiertes Modell mit "adaptive_matrix".

Gain/Pedestal: urspruenglich aus `HDIntegratedCamera_InterfaceSpecifications-
E.pdf` §3.2.6/§3.2.14 (2020, Multi-Modell-PDF, "applicable models":
AW-UE150/AW-UE155/AW-UN145 -- deckt also genau CAMERA_ID + CAMERA_ID_ALIASES
hier ab) verifiziert mit Gain 0-42dB (OGU 08h=0dB .. 32h=42dB). **Korrektur
2026-07-18 (Nutzerentscheid):** zwei neuere, dedizierte PDFs widersprechen
dem: `docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf` (2022,
"AW-UE150/AW-HE145", siehe auch `aw_he145.py`) UND
`docs/specs/AW-UE150A_InterfaceSpecification_E.pdf` (2025, explizit nur fuer
"AW-UE150A", Model Number-Tabelle bestaetigt `OID:AW-UE150A`) zeigen
uebereinstimmend einen WEITEREN Bereich -3..+42dB (Anker 05h=-3dB ..
08h=0dB .. 2Ch=36dB .. 32h=42dB) -- 2 von 3 Quellen stimmen ueberein, nur
die aelteste/generischste (2020) weicht ab. Die neueren, modellspezifischen
Quellen wurden als massgeblich gewaehlt, GAIN_MIN_DB ist daher jetzt -3
(nicht mehr 0). ACHTUNG, das ist trotzdem NICHT dieselbe Gain-Formel wie
AW-UE160 (dort -6..+12dB, eigene PDF-Quelle mit anderem Maximum). Pedestal
ueber `OSJ:0F`/`QSJ:0F` Master Pedestal, Bereich -200..+200, Data = 0x800 +
Wert -- in ALLEN DREI PDF-Quellen identisch, kein
Widerspruch, gleiches Kommando/Format wie bei AW-UE160/AW-HE145.

DRS/Knee-Korrektur (2026-07-18): `drs` hat 4 gueltige Werte (0=Off/1=Low/
2=Mid/3=High, alle drei o. g. PDFs uebereinstimmend); `knee` (`OSA:2D`) hat
3 gueltige Werte (0=OFF/1=MANUAL/2=AUTO). Beide als je ein Toggle pro
Zielzustand (`drs_low`/`drs_mid`/`drs_high`, `knee_manual`/`knee_auto`)
statt eigener "cycle"-Features (Nutzerentscheid 2026-07-18, siehe
drivers/panasonic_aw.py-Klassendocstring) -- vorher `drs` faelschlich als
einfacher Toggle, `knee` als "cycle"-Feature gefuehrt.

Query-Ergaenzung (2026-07-18, Quelle: `AW-UE150A_InterfaceSpecification_
E.pdf`/`AW-UE150HE145_InterfaceSpecification_E.pdf`): `query`/
`query_on_value` bei `adaptive_matrix` (`QSJ:4F`), `auto_focus` (`QAF`),
`drs_low`/`drs_mid`/`drs_high` (`QSE:33`), `knee_manual`/`knee_auto`
(`QSA:2D`), `osd` (`QUS`) und `white_clip` (`QSA:2E`) -- alle direkt in
diesen PDFs als Request/Response-Paar verifiziert.
"""

CAMERA_ID = "AW-UE150A"
CAMERA_ID_ALIASES = ["AW-UE150", "AW-UE155", "AW-UN145"]
DISPLAY_NAME = "Panasonic AW-UE150A"

GAIN_MIN_DB = -3
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1
# Super-Gain-Kopplung (Nutzerauftrag 2026-07-20, Quelle: AW-UE150HE145_
# InterfaceSpecification_E.pdf, "Auto, -3dB~36dB" wenn Super Gain aus,
# "Auto, -3dB~42dB" wenn an -- nur die Obergrenze aendert sich, nicht die
# Untergrenze; live nur gegen AW-UE100 verifiziert, nicht gegen eine echte
# AW-UE150A/HE145): 36dB statt 42dB, solange Super Gain (`OSI:28`) aus ist.
GAIN_MAX_DB_SUPER_GAIN_OFF = 36
SUPER_GAIN_QUERY_COMMAND = "QSI:28"

PEDESTAL_COMMAND = "OSJ:0F"
PEDESTAL_QUERY_COMMAND = "QSJ:0F"
PEDESTAL_MIN = -200
PEDESTAL_MAX = 200
PEDESTAL_CENTER_DATA = 0x800
PEDESTAL_SCALE = 1
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "adaptive_matrix": {"kind": "toggle", "on": "OSJ:4F:1", "off": "OSJ:4F:0", "query": "QSJ:4F", "query_on_value": "1"},
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "awb_black": {"kind": "trigger", "cmd": "OAS"},
    "aww_white": {"kind": "trigger", "cmd": "OWS"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "knee_manual": {"kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "1"},
    "knee_auto": {"kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "2"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
    "white_clip": {"kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0", "query": "QSA:2E", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "adaptive_matrix": "Adaptive Matrix",
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_mid": "DRS: Mid",
    "drs_high": "DRS: High",
    "knee_manual": "Knee: Manual",
    "knee_auto": "Knee: Auto",
    "osd": "OSD",
    "white_clip": "White Clip",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
