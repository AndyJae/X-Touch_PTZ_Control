"""drivers/panasonic_models/aw_he50.py -- Panasonic AW-HE50 series.

Portiert aus `C:\\smart_reset_work\\camera_plugins\\panasonic\\aw_he50.py`s
UI_BUTTONS/UI_BUTTON_LABELS. Aelteres, einfacheres Modell als HE120/HE130 --
kein Knee-Button (Quelle hat dafuer keinen Eintrag).

Gain/Pedestal (`HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.6/
§3.2.14, gilt fuer "AW-HE50/AW-HE60"): Gain nur in 3dB-Schritten 0-18dB
(OGU 08h=0dB .. 1Ah=18dB, disabled bei FullAuto -> ER3); Pedestal ueber das
aeltere `OTP`/`QTP`-Kommando (nicht `OSJ:0F` wie bei UE150/UE160), Bereich
-10..+10, Data = 0x96 + Wert*15 (Ankerpunkte 000h=-10/096h=0/12Ch=+10).

DRS-Korrektur (2026-07-18, Quelle: dieselbe PDF §3.2.x "DRS", Tabelle fuer
"AW-HE50/AW-HE60/AW-HE40/AW-UE70/AW-HE42"): kein einfacher An/Aus-Toggle,
sondern 3 gueltige Werte (0=Off/1=Low/3=High -- Data-Wert 2 ist fuer diese
Modellgruppe nicht belegt/dokumentiert, laut PDF disabled bei FullAuto ->
ER3). Als je ein Toggle pro Zielzustand gefuehrt (`drs_low`/`drs_high`,
Nutzerentscheid 2026-07-18 -- kein eigenes "cycle"-Feature mehr auf
Button 2/3, siehe drivers/panasonic_aw.py-Klassendocstring): Druck schaltet
zwischen OFF und dem jeweiligen Zielzustand um, nicht rundenweise durch
alle Werte.

Query-Ergaenzung (2026-07-18, Nutzerauftrag "verdrahten inkl. Zustands-
abfrage beim Zuweisen"): `query`/`query_on_value` bei `auto_focus` (`QAF`),
`drs_low`/`drs_high` (`QSE:33`) und `osd` (`QUS`, Antwort als `OUS:[Data]`)
-- alle drei direkt in der o. g. PDF als Request/Response-Paar verifiziert.

White-Clip-Korrektur (2026-07-18, Rest-Katalog-Pruefung): `white_clip`
(`OSA:2E`) wurde bisher faelschlich gefuehrt (aus smart_reset_work, dort
nicht gegen diese PDF geprueft) -- §3.2.31 "White Clip settings" ist aber
explizit **"Only supported by the AW-HE130/AW-HR140/AW-UE150"**, weder
AW-HE50 noch AW-HE60 werden dort genannt. Der Eintrag wurde deshalb
komplett entfernt (kein erfundenes/falsches Feature).

Bewusst KEIN ND_FILTER_OPTIONS (Nutzerauftrag 2026-07-22, ND-Filter als
4. Encoder-Funktion auf Button 1): `HDIntegratedCamera_
InterfaceSpecifications-E.pdf` §3.2.1.4/Menu-Tabelle 4-4-1 fuehrt fuer
AW-HE50/AW-HE60 KEINEN `OFT`-Eintrag -- diese Modelle haben schlicht keinen
physischen ND-Filter (im Unterschied zu AW-UE70/AW-HE42, siehe dort).
"""

CAMERA_ID = "AW-HE50"
CAMERA_ID_ALIASES = ["AW-HE50H", "AW-HE50E", "AW-HE50S"]
DISPLAY_NAME = "Panasonic AW-HE50"

GAIN_MIN_DB = 0
GAIN_MAX_DB = 18
GAIN_STEP_DB = 3

PEDESTAL_COMMAND = "OTP"
PEDESTAL_QUERY_COMMAND = "QTP"
PEDESTAL_MIN = -10
PEDESTAL_MAX = 10
PEDESTAL_CENTER_DATA = 0x96
PEDESTAL_SCALE = 15
PEDESTAL_DATA_WIDTH = 3

BUTTON_FEATURES: dict[str, dict] = {
    "auto_focus": {"kind": "toggle", "on": "OAF:1", "off": "OAF:0", "query": "QAF", "query_on_value": "1"},
    "auto_iris": {"kind": "toggle", "on": "ORS:1", "off": "ORS:0"},
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
    "osd": {"kind": "toggle", "on": "DUS:1", "off": "DUS:0", "query": "QUS", "query_on_value": "1"},
}

BUTTON_FEATURE_LABELS: dict[str, str] = {
    "auto_focus": "Auto Focus",
    "auto_iris": "Auto Iris",
    "drs_low": "DRS: Low",
    "drs_high": "DRS: High",
    "osd": "OSD",
}
