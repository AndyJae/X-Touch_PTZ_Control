"""drivers/panasonic_models/aw_ue100.py -- Panasonic AW-UE100.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_ue100.py`s
UI_BUTTONS/UI_BUTTON_LABELS (identisch zu AW-HE120/HE130/HR140, aber als
eigenes Modell/eigene Datei gefuehrt, analog zur Quelle; keine
CAMERA_ID_ALIASES in der Quelle).

Gain/Pedestal (Quelle: `docs/specs/AW-UE100_InterfaceSpecification_E.pdf`,
dediziertes Modell-Dokument, Kap. 9 "Command List" -- ein eigenes PDF fuer
AW-UE100, separat von den beiden anderen lokalen Referenz-PDFs, erst nach
der urspruenglichen Implementierung dieser Datei ins Repo gelegt worden):
Gain (`OGU`/`QGU`) kontinuierlich 08h=0dB .. 1Ah=18dB .. 32h=42dB (1dB-
Schritte), 80h=AGC -- identische Ankerpunkte wie AW-HR140/AW-UE150A (siehe
`aw_hr140.py`), aber eigenstaendig fuer dieses Modell aus seiner eigenen
PDF-Quelle uebernommen, nicht von dort abgeleitet. Laut Doku ist der
Maximalwert an "Super Gain" (`OSI:28`, hier nicht als Button-Feature
portiert, siehe unten) gekoppelt: 0-36dB wenn Super Gain aus, 0-42dB wenn
an -- `GAIN_MAX_DB` nutzt bewusst den groesseren Wert (42dB); die 36dB-
Deckelung bei ausgeschaltetem Super Gain wird hier (wie z.B. das FullAuto-
ER3-Verhalten bei anderen Modellen) nicht durchgesetzt.
Pedestal: `OSJ:0F`/`QSJ:0F` Master Pedestal, Data 738h=-200/800h=0/8C8h=+200
-- identisches Kommando/Format wie AW-UE150A/AW-UE160.

Bewusst NICHT ergaenzt: "Super Gain" (`OSI:28`) als komplett NEUES
Button-Feature -- der Button-KATALOG (welche Features es gibt) stammt laut
Projektkonvention (CLAUDE.md) weiterhin aus `C:\\smart_reset_work`; ein
zusaetzliches Feature waere eine eigene Entscheidung ausserhalb des
aktuellen Auftrags.

Super-Gain-Kopplung DOCH durchgesetzt (Nutzerauftrag 2026-07-20, live gegen
eine echte AW-UE100 mit Super Gain aus verifiziert: `OGU`-Werte >36dB
werden von der Kamera per `ER3` abgelehnt): `GAIN_MAX_DB_SUPER_GAIN_OFF`/
`SUPER_GAIN_QUERY_COMMAND` liefern die schmalere Obergrenze, wenn Super
Gain aus ist -- siehe `PanasonicAWDriver.effective_gain_max_db`.

DRS/Knee-Korrektur (2026-07-18, Nutzerauftrag "Button-Kataloge gegen
Kapitel 8 verifizieren", Quelle: Kap. 8 "Menu-Command Correspondance Table"
+ Kap. 9 "Command List" dieser PDF): bestehende, aus smart_reset_work
uebernommene Eintraege waren FALSCH kodiert. `drs` (`OSE:33`) hat 4 gueltige
Werte (0=Off/1=Low/2=Mid/3=High), `knee` (`OSA:2D`) hat 3 gueltige Werte
(0=OFF/1=MANUAL/2=AUTO, Kap. 9 zeigt "Knee Mode" explizit mit diesen drei
Werten) -- beide als je ein Toggle pro Zielzustand (`drs_low`/`drs_mid`/
`drs_high`, `knee_manual`/`knee_auto`) statt eigener "cycle"-Features
(Nutzerentscheid 2026-07-18, siehe drivers/panasonic_aw.py-Klassendocstring).

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `auto_focus`
(`QAF`), `drs_low`/`drs_mid`/`drs_high` (`QSE:33`), `knee_manual`/
`knee_auto` (`QSA:2D`), `osd` (`QUS`) und `white_clip` (`QSA:2E`) -- alle
direkt in dieser PDF als Request/Response-Paar verifiziert.
"""

CAMERA_ID = "AW-UE100"
DISPLAY_NAME = "Panasonic AW-UE100"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 42
GAIN_STEP_DB = 1
# Super-Gain-Kopplung (Nutzerauftrag 2026-07-20, live verifiziert): 36dB
# statt 42dB, solange Super Gain (`OSI:28`) aus ist.
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
