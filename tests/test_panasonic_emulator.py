"""tests/test_panasonic_emulator.py -- Modell-abhaengige CGI-Dispatch-Logik
des Dev-Werkzeugs `tools/panasonic_emulator.py` (Nutzerentscheid 2026-07-18:
Emulator soll verschiedene Kameramodelle simulieren, siehe dessen
Modul-Docstring). Kein Produktionscode, aber die Dispatch-Logik in
`_handle_cam()` ist genau die Stelle, gegen die `drivers/panasonic_aw.py` im
manuellen Testbetrieb (`python tools/panasonic_emulator.py`) tatsaechlich
spricht -- ein Regressionstest dafuer ist deshalb sinnvoll.
"""

from __future__ import annotations

import tools.panasonic_emulator as emu


def _handle(model: str, cmd: str) -> str:
    emu.state = emu.CameraState(model)
    return emu._handle_cam(cmd)


def test_qid_reflects_selected_model() -> None:
    assert _handle("AW-UE160", "QID") == "OID:AW-UE160"
    assert _handle("AW-HE50", "QID") == "OID:AW-HE50"
    assert _handle("AK-UB300", "QID") == "OID:AK-UB300"


def test_gain_unsupported_for_ak_ub300_returns_er1() -> None:
    # AK-UB300 hat kein OGU/QGU (strukturell anderes OGS-Region-Schema,
    # siehe drivers/panasonic_models/ak_ub300.py).
    assert _handle("AK-UB300", "QGU") == "ER1:QGU"
    assert _handle("AK-UB300", "OGU:08") == "ER1:OGU:08"


def test_gain_unsupported_for_unknown_model_returns_er1() -> None:
    # Mittlerweile hat jedes registrierte Modell (ausser AK-UB300) Gain-
    # Daten -- dieser Pfad wird also nur noch fuer ein unbekanntes Modell
    # durchlaufen.
    assert _handle("SOME-UNKNOWN-CAMERA", "QGU") == "ER1:QGU"


def test_gain_works_for_ue160() -> None:
    assert _handle("AW-UE160", "QGU") == "OGU:08"


def test_gain_and_pedestal_work_for_ue100() -> None:
    # AW-UE100 hat ein eigenes dediziertes Referenz-PDF (siehe
    # drivers/panasonic_models/aw_ue100.py).
    assert _handle("AW-UE100", "QGU") == "OGU:08"
    assert _handle("AW-UE100", "QSJ:0F") == "OSJ:0F:800"


def test_gain_and_pedestal_work_for_he145_and_ue145_alias() -> None:
    # AW-HE145 (echte QID-Antwort) und der Alias "AW-UE145" (frueher
    # faelschlich die CAMERA_ID, siehe aw_he145.py-Docstring) muessen beide
    # auf denselben, per dediziertem PDF verifizierten Katalog aufloesen.
    for model in ("AW-HE145", "AW-UE145"):
        assert _handle(model, "QID") == f"OID:{model}"
        assert _handle(model, "QGU") == "OGU:08"  # Emulator startet immer bei der 0dB-Anker (universell)
        assert _handle(model, "QSJ:0F") == "OSJ:0F:800"


def test_gain_and_pedestal_work_for_ue80_and_aliases() -> None:
    # AW-UE80/UE50/UE40/UE30 teilen sich ein dediziertes PDF.
    for model in ("AW-UE80", "AW-UE50", "AW-UE40", "AW-UE30"):
        assert _handle(model, "QGU") == "OGU:08"
        assert _handle(model, "QSJ:0F") == "OSJ:0F:800"


def test_pedestal_command_family_matches_model() -> None:
    # AW-UE160/AW-UE150A: OSJ:0F Master Pedestal.
    assert _handle("AW-UE160", "QSJ:0F") == "OSJ:0F:800"
    # AW-HE50: aeltere OTP/QTP-Familie, anderer Zentraldatenwert.
    assert _handle("AW-HE50", "QTP") == "OTP:096"
    # AK-UB300: eigene OSG:4A-Familie.
    assert _handle("AK-UB300", "QSG:4A") == "OSG:4A:80"


def test_pedestal_command_from_wrong_family_returns_er1() -> None:
    # AW-HE50 kennt kein OSJ:0F (das ist die UE150/UE160-Familie).
    assert _handle("AW-HE50", "QSJ:0F") == "ER1:QSJ:0F"


def test_pedestal_unsupported_for_unknown_model_returns_er1() -> None:
    assert _handle("SOME-UNKNOWN-CAMERA", "QTP") == "ER1:QTP"
    assert _handle("SOME-UNKNOWN-CAMERA", "QSJ:0F") == "ER1:QSJ:0F"


def test_pedestal_control_updates_state_with_correct_scale() -> None:
    emu.state = emu.CameraState("AW-HE50")
    response = emu._handle_cam("OTP:12C")  # 0x12C = 0x96 + 10*15 -> +10
    assert response == "OTP:12C"
    assert emu.state.pedestal_data == 0x12C
    assert emu._handle_cam("QTP") == "OTP:12C"


def test_toggle_feature_query_returns_last_set_value() -> None:
    # AW-HE50 hat "drs_low"/"drs_high" (OSE:33) mit bestaetigter Query
    # QSE:33 (siehe drivers/panasonic_models/aw_he50.py).
    emu.state = emu.CameraState("AW-HE50")
    assert emu._handle_cam("QSE:33") == "OSE:33:0"  # Grundzustand, nichts gesetzt

    assert emu._handle_cam("OSE:33:1") == "OSE:33:1"
    assert emu._handle_cam("QSE:33") == "OSE:33:1"

    assert emu._handle_cam("OSE:33:3") == "OSE:33:3"
    assert emu._handle_cam("QSE:33") == "OSE:33:3"


def test_toggle_feature_query_with_dus_ous_prefix_mismatch() -> None:
    # OSD (DUS control, QUS query) ist der eine Sonderfall mit
    # unterschiedlichem Control-/Response-Praefix (Antwort "OUS", nicht
    # "ODUS") -- bestaetigt in HDIntegratedCamera_InterfaceSpecifications-
    # E.pdf Tabelle 3.2.22.
    emu.state = emu.CameraState("AW-HE50")
    assert emu._handle_cam("DUS:1") == "DUS:1"
    assert emu._handle_cam("QUS") == "OUS:1"


def test_toggle_feature_query_unsupported_for_features_without_query() -> None:
    # AW-UE160s knee_manual/knee_auto haben bewusst kein "query" (siehe
    # aw_ue160.py) -- die Query-Kommandos existieren fuer dieses Modell also
    # gar nicht im Katalog, ER1 wie ein unbekannter Befehl.
    assert _handle("AW-UE160", "QSA:2D") == "ER1:QSA:2D"


def test_button_feature_command_only_accepted_for_models_that_have_it() -> None:
    # "knee_manual"/"knee_auto" (OSL:45:.../OSA:2D:...) sind nur im
    # AW-UE160-Katalog, nicht bei AW-HE50 (siehe
    # drivers/panasonic_models/aw_ue160.py vs. aw_he50.py).
    assert _handle("AW-UE160", "OSL:45:1") == "OSL:45:1"
    assert _handle("AW-HE50", "OSL:45:1") == "ER1:OSL:45:1"

    # "drs_low" ist bei AW-HE50 OSE:33:1/bei AW-UE160 gibt es nur den
    # eigenstaendigen "drs"-Toggle auf OSA:0D:... -- jeweils nur das eigene
    # Kommando wird akzeptiert.
    assert _handle("AW-HE50", "OSE:33:1") == "OSE:33:1"
    assert _handle("AW-UE160", "OSE:33:1") == "ER1:OSE:33:1"
    assert _handle("AW-UE160", "OSA:0D:1") == "OSA:0D:1"


def test_button_feature_toggle_with_command_list_accepts_every_command() -> None:
    # AW-UE160s "knee_auto" hat "on": ["OSL:45:1", "OSA:2D:2"] (Liste statt
    # einzelnem String, siehe drivers/panasonic_aw.py::trigger_button_feature)
    # -- der Emulator muss beide Kommandos einzeln kennen.
    assert _handle("AW-UE160", "OSL:45:1") == "OSL:45:1"
    assert _handle("AW-UE160", "OSA:2D:2") == "OSA:2D:2"
    assert _handle("AW-UE160", "OSL:45:0") == "OSL:45:0"  # gemeinsames "off"


def test_unknown_command_returns_er1_regardless_of_model() -> None:
    assert _handle("AW-UE160", "XYZ") == "ER1:XYZ"
