"""drivers/panasonic_models/aw_he120.py -- Panasonic AW-HE120.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he120.py`s
UI_BUTTONS/UI_BUTTON_LABELS.

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14): Gain kontinuierlich 0-18dB (OGU 08h=0dB .. 1Ah=18dB, 1dB-Schritte);
Pedestal ueber `OTP`/`QTP` wie bei HE50/HE60, aber eigene Formel/Bereich
-150..+150, Data = 0x96 + Wert (Ankerpunkte 000h=-150/096h=0/12Ch=+150) --
gleiche Pedestal-Familie wie AW-HE130/AW-HR140.

DRS/Knee-Korrektur (2026-07-18, dieselbe PDF, §3.2.30 "Knee settings" +
DRS-Tabelle): `drs` hat 4 gueltige Werte (0=Off/1=Low/2=Mid/3=High, Tabelle
fuer "AW-HE120/AW-HE130/AW-HR140/AW-UE150") -- als je ein Toggle pro
Zielzustand (`drs_low`/`drs_mid`/`drs_high`) statt einem "cycle"-Feature
(Nutzerentscheid 2026-07-18, siehe drivers/panasonic_aw.py-Klassendocstring).
`knee` (`OSA:2D`) wurde bisher faelschlich als Toggle gefuehrt (aus
smart_reset_work, dort nicht gegen diese PDF geprueft) -- laut §3.2.30 ist
Knee Mode aber explizit **"Only supported by the AW-HE130/AW-HR140/
AW-UE150/AK-UB300"**, AW-HE120 wird dort NICHT genannt. Der Eintrag wurde
deshalb komplett entfernt (kein erfundenes/falsches Feature).

Query-Ergaenzung (2026-07-18): `query`/`query_on_value` bei `auto_focus`
(`QAF`), `drs_low`/`drs_mid`/`drs_high` (`QSE:33`) und `osd` (`QUS`) --
alle drei direkt in der o. g. PDF als Request/Response-Paar verifiziert.

White-Clip-Korrektur (2026-07-18, Rest-Katalog-Pruefung): `white_clip`
(`OSA:2E`) wurde bisher faelschlich gefuehrt (aus smart_reset_work, dort
nicht gegen diese PDF geprueft) -- §3.2.31 "White Clip settings" ist aber
explizit **"Only supported by the AW-HE130/AW-HR140/AW-UE150"**, AW-HE120
wird dort NICHT genannt. Der Eintrag wurde deshalb komplett entfernt
(kein erfundenes/falsches Feature) -- exakt dieselbe Art Fehler wie zuvor
bei `knee` (siehe oben).
"""

CAMERA_ID = "AW-HE120"
CAMERA_ID_ALIASES = ["AW-HE125", "AW-HE120W", "AW-HE120K"]
DISPLAY_NAME = "Panasonic AW-HE120"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
GAIN_STEP_DB = 1

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -150
PEDESTAL_MAX = 150
PEDESTAL_CENTER_DATA = 0x96
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
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_mid": "DRS: Mid",
    "drs_high": "DRS: High",
    "osd": "OSD",
    "awb_black": "ABB (Black)",
    "aww_white": "AWW (White)",
}
