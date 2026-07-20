"""tests/test_panasonic_models.py -- Tests fuer die Kameramodell-Registry
(Spec §9a), die BUTTON_FEATURES/BUTTON_FEATURE_LABELS anhand des per `QID`
erkannten Modells auflöst (siehe drivers/panasonic_aw.py::_apply_model_catalog).
"""

from __future__ import annotations

from drivers.panasonic_models import aw_he50, aw_ue160
from drivers.panasonic_models.registry import ModelRegistry, get_registry, resolve_model


def test_get_registry_loads_all_model_files() -> None:
    registry = get_registry()
    ids = registry.registered_camera_ids()

    # Alle in drivers/panasonic_models/ portierten CAMERA_IDs (siehe
    # __init__.py-Docstring), nicht die CAMERA_ID_ALIASES.
    assert "AW-UE160" in ids
    assert "AW-HE50" in ids
    assert "AW-HE40" in ids
    assert "AW-HE120" in ids
    assert "AW-HE130" in ids
    assert "AW-HR140" in ids
    assert "AW-UE100" in ids
    assert "AW-UE150A" in ids
    assert "AW-UE80" in ids
    assert "AW-HE145" in ids
    assert "AK-UB300" in ids


def test_resolve_model_by_exact_camera_id() -> None:
    module = resolve_model("AW-UE160")
    assert module is aw_ue160


def test_resolve_model_by_alias() -> None:
    # AW-HE60H ist ein CAMERA_ID_ALIASES-Eintrag von AW-HE60, das wiederum
    # denselben Katalog wie AW-HE50 re-exportiert (siehe aw_he60.py).
    module = resolve_model("AW-HE60H")
    assert module is not None
    assert module.CAMERA_ID == "AW-HE60"
    assert module.BUTTON_FEATURES == aw_he50.BUTTON_FEATURES


def test_resolve_model_returns_none_for_unknown_camera_id() -> None:
    assert resolve_model("SOME-UNKNOWN-CAMERA") is None
    assert resolve_model(None) is None
    assert resolve_model("") is None


def test_model_registry_register_and_resolve_in_isolation() -> None:
    # Unabhaengig vom globalen Singleton (get_registry()) -- prueft
    # register()/resolve() direkt anhand eines echten Modell-Moduls.
    registry = ModelRegistry()
    registry.register(aw_ue160)

    assert registry.resolve("AW-UE160") is aw_ue160
    assert registry.resolve("AW-HE50") is None  # nicht registriert in dieser Instanz


def test_ue150_camera_id_is_ue150a_with_ue150_as_alias() -> None:
    # Bewusst KEIN Tippfehler -- so in der Referenzquelle (smart_reset_work)
    # gefuehrt, siehe aw_ue150.py-Docstring.
    module = resolve_model("AW-UE150A")
    assert module is not None
    assert module.CAMERA_ID == "AW-UE150A"
    assert resolve_model("AW-UE150") is module


def test_ue150_and_ue160_share_master_pedestal_command_but_differ_in_gain() -> None:
    # Beide nutzen OSJ:0F/-200..+200 fuers Pedestal (siehe
    # HDIntegratedCamera_InterfaceSpecifications-E.pdf: "Only enabled for
    # the AW-UE150", uebereinstimmend mit AW-UE160_InterfaceSpecification_
    # E.pdf), aber UE150 hat 0..42dB (kontinuierlich) statt UE160s -6..+12dB
    # -- die beiden PDFs sind fuer Gain NICHT austauschbar, nur fuer Pedestal.
    from drivers.panasonic_models import aw_ue150, aw_ue160

    assert aw_ue150.PEDESTAL_COMMAND == aw_ue160.PEDESTAL_COMMAND == "OSJ:0F"
    assert (aw_ue150.PEDESTAL_MIN, aw_ue150.PEDESTAL_MAX) == (aw_ue160.PEDESTAL_MIN, aw_ue160.PEDESTAL_MAX) == (-200, 200)
    assert (aw_ue150.GAIN_MIN_DB, aw_ue150.GAIN_MAX_DB) != (aw_ue160.GAIN_MIN_DB, aw_ue160.GAIN_MAX_DB)


def test_ue145_is_alias_of_he145_not_a_separate_camera_id() -> None:
    # Korrektur 2026-07-18 (Nutzerentscheid): "AW-UE145" war urspruenglich
    # faelschlich der CAMERA_ID (aus dem Dateinamen der smart_reset_work-
    # Quelle uebernommen), passte aber zu keiner echten QID-Antwort. Das
    # dedizierte docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf zeigt
    # die tatsaechlichen QID-Werte "AW-UE150" und "AW-HE145" -- "AW-UE145"
    # ist jetzt nur noch ein Alias (siehe aw_he145.py), fuer den Fall, dass
    # eine Kamera (fehlerhaft?) diesen String meldet.
    module = resolve_model("AW-UE145")
    assert module is not None
    assert module.CAMERA_ID == "AW-HE145"
    assert resolve_model("AW-HE145") is module


def test_he145_resolves_gain_pedestal_from_dedicated_pdf() -> None:
    # Gain/Pedestal kommen aus dem oben genannten dedizierten PDF, das
    # explizit fuer AW-UE150 UND AW-HE145 gemeinsam gilt (keine "only
    # supported by"-Einschraenkung beim Gain/Pedestal-Abschnitt) -- daher
    # identisch zu aw_ue150.py (nach dessen Korrektur 2026-07-18 auf
    # GAIN_MIN_DB=-3, siehe dortiger Kommentar zum PDF-Widerspruch).
    from drivers.panasonic_models import aw_he145, aw_ue150

    assert (aw_he145.GAIN_MIN_DB, aw_he145.GAIN_MAX_DB, aw_he145.GAIN_STEP_DB) == (-3, 42, 1)
    assert (aw_he145.GAIN_MIN_DB, aw_he145.GAIN_MAX_DB) == (aw_ue150.GAIN_MIN_DB, aw_ue150.GAIN_MAX_DB)
    assert aw_he145.PEDESTAL_COMMAND == aw_ue150.PEDESTAL_COMMAND == "OSJ:0F"


def test_super_gain_coupling_present_for_documented_models() -> None:
    # Nutzerauftrag 2026-07-20, live gegen eine echte AW-UE100 verifiziert:
    # Werte >36dB werden von der Kamera per ER3 abgelehnt, wenn Super Gain
    # (OSI:28) aus ist -- GAIN_MAX_DB (42) gilt nur, wenn Super Gain an ist.
    from drivers.panasonic_models import (
        aw_he145,
        aw_ue30,
        aw_ue40,
        aw_ue50,
        aw_ue80,
        aw_ue100,
        aw_ue150,
    )

    for module in (aw_ue100, aw_ue80, aw_ue30, aw_ue40, aw_ue50, aw_ue150, aw_he145):
        assert module.GAIN_MAX_DB_SUPER_GAIN_OFF == 36, module
        assert module.SUPER_GAIN_QUERY_COMMAND == "QSI:28", module


def test_super_gain_coupling_absent_for_ue160_not_documented_in_its_pdf() -> None:
    # AW-UE160_InterfaceSpecification_E.pdf erwaehnt "Super Gain" an keiner
    # Stelle -- kein erfundener Wert fuer dieses Modell.
    from drivers.panasonic_models import aw_ue160

    assert getattr(aw_ue160, "GAIN_MAX_DB_SUPER_GAIN_OFF", None) is None
    assert getattr(aw_ue160, "SUPER_GAIN_QUERY_COMMAND", None) is None


def test_ak_ub300_has_pedestal_but_no_gain_module_constants() -> None:
    module = resolve_model("AK-UB300")
    assert module is not None
    assert not hasattr(module, "GAIN_MIN_DB")
    assert module.PEDESTAL_COMMAND == "OSG:4A"


# --- DRS/Knee-Korrektur 2026-07-18 (Nutzerauftrag: Button-Kataloge gegen
# Kapitel 8/9 der jeweiligen PDFs verifizieren) -- bestehende, aus
# smart_reset_work uebernommene Eintraege waren fuer diese beiden Features
# durchgaengig als einfache Toggles kodiert, obwohl sie laut PDF mehrwertige
# Parameter sind (oder, bei "knee" auf AW-HE120, gar nicht existieren).
# Zweite Korrektur, ebenfalls 2026-07-18 (Nutzerentscheid): mehrwertige
# Parameter werden NICHT als "cycle"-Feature gefuehrt, sondern als je ein
# Toggle pro Zielzustand (Button 2/3 haben nur eine einfarbige LED, koennen
# also kein rundenweises Durchschalten anzeigen) -- "cycle" existiert nur
# noch bei Button 1 (Encoder-Funktionsauswahl), ein komplett getrennter
# Mechanismus. Dritte Ergaenzung, ebenfalls 2026-07-18 (Nutzerauftrag "echte
# Zustandsabfrage beim Zuweisen"): "query"/"query_on_value" pro Feature, wo
# ein Query-Kommando direkt in den PDFs verifiziert wurde (bei drs/knee
# durchgaengig der Fall, siehe QSE:33/QSA:2D). ---

_DRS_3VALUE_TOGGLES = {
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
}
_DRS_4VALUE_TOGGLES = {
    "drs_low": {"kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1"},
    "drs_mid": {"kind": "toggle", "on": "OSE:33:2", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "2"},
    "drs_high": {"kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3"},
}
_KNEE_TOGGLES = {
    "knee_manual": {"kind": "toggle", "on": "OSA:2D:1", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "1"},
    "knee_auto": {"kind": "toggle", "on": "OSA:2D:2", "off": "OSA:2D:0", "query": "QSA:2D", "query_on_value": "2"},
}


def test_drs_is_three_value_toggles_for_he_low_tier_group() -> None:
    # HDIntegratedCamera_InterfaceSpecifications-E.pdf, DRS-Tabelle fuer
    # "AW-HE50/AW-HE60/AW-HE40/AW-UE70/AW-HE42": nur 0/1/3 (Off/Low/High),
    # Data-Wert 2 ist fuer diese Gruppe nicht dokumentiert -- kein
    # "drs_mid"-Eintrag.
    for model in ("AW-HE50", "AW-HE60", "AW-HE40", "AW-HE42", "AW-UE70"):
        module = resolve_model(model)
        assert module is not None, model
        for key, feature in _DRS_3VALUE_TOGGLES.items():
            assert module.BUTTON_FEATURES[key] == feature, (model, key)
        assert "drs_mid" not in module.BUTTON_FEATURES, model


def test_drs_is_four_value_toggles_for_higher_tier_group() -> None:
    # Dieselbe PDF, DRS-Tabelle fuer "AW-HE120/AW-HE130/AW-HR140/AW-UE150":
    # volle 4 Werte (Off/Low/Mid/High). Gilt laut den jeweils dedizierten
    # PDFs auch fuer AW-UE100 und AW-UE80/UE50/UE40/UE30.
    for model in (
        "AW-HE120", "AW-HE130", "AW-HR140",
        "AW-UE150A", "AW-HE145",
        "AW-UE100", "AW-UE80", "AW-UE50", "AW-UE40", "AW-UE30",
    ):
        module = resolve_model(model)
        assert module is not None, model
        for key, feature in _DRS_4VALUE_TOGGLES.items():
            assert module.BUTTON_FEATURES[key] == feature, (model, key)


def test_knee_absent_from_he120_not_supported_per_pdf() -> None:
    # §3.2.30 "Knee settings": Knee Mode ist explizit "Only supported by the
    # AW-HE130/AW-HR140/AW-UE150/AK-UB300" -- AW-HE120 wird dort NICHT
    # genannt, der Katalog hatte ihn vorher faelschlich als Toggle.
    module = resolve_model("AW-HE120")
    assert module is not None
    assert "knee_manual" not in module.BUTTON_FEATURES
    assert "knee_auto" not in module.BUTTON_FEATURES


def test_knee_is_toggle_pair_where_supported() -> None:
    # Dieselbe PDF-Stelle nennt AW-HE130/AW-HR140/AW-UE150/AK-UB300 als
    # Knee-faehig (0=OFF/1=MANUAL/2=AUTO); AW-UE100 hat das laut seinem
    # eigenen dedizierten PDF ebenfalls in exakt dieser Kodierung.
    for model in ("AW-HE130", "AW-HR140", "AW-UE150A", "AW-HE145", "AK-UB300", "AW-UE100"):
        module = resolve_model(model)
        assert module is not None, model
        for key, feature in _KNEE_TOGGLES.items():
            assert module.BUTTON_FEATURES[key] == feature, (model, key)


def test_knee_not_guessed_for_ue80_group_despite_menu_entry() -> None:
    # Kap. 8 der AW-UE80UE50UE40-PDF listet "Knee mode OSA:2D" als
    # existierendes Menu, aber die Werte-/Label-Tabelle liess sich nicht
    # sauber extrahieren -- bewusst kein erfundener Wert, "knee_*" bleibt
    # abwesend (siehe aw_ue80.py-Kommentar, CLAUDE.md Offene Punkte).
    for model in ("AW-UE80", "AW-UE50", "AW-UE40", "AW-UE30"):
        module = resolve_model(model)
        assert module is not None, model
        assert "knee_manual" not in module.BUTTON_FEATURES, model
        assert "knee_auto" not in module.BUTTON_FEATURES, model


def test_white_clip_absent_where_not_supported_per_pdf() -> None:
    # §3.2.31 "White Clip settings": explizit "Only supported by the
    # AW-HE130/AW-HR140/AW-UE150" -- war vorher (aus smart_reset_work, nicht
    # gegen diese PDF geprueft) faelschlich auch bei diesen Modellen gefuehrt.
    for model in ("AW-HE50", "AW-HE60", "AW-HE40", "AW-HE42", "AW-UE70", "AW-HE120", "AK-UB300"):
        module = resolve_model(model)
        assert module is not None, model
        assert "white_clip" not in module.BUTTON_FEATURES, model
        assert "white_clip" not in module.BUTTON_FEATURE_LABELS, model


def test_white_clip_present_where_supported_per_pdf() -> None:
    # Die drei in §3.2.31 explizit genannten Modelle behalten white_clip.
    # AW-UE100/AW-UE150A/AW-HE145/AW-UE160/AW-UE80-Gruppe haben eigene,
    # dedizierte PDFs, die White Clip unabhaengig davon dokumentieren.
    for model in (
        "AW-HE130", "AW-HR140", "AW-UE150A", "AW-HE145",
        "AW-UE100", "AW-UE160", "AW-UE80", "AW-UE50", "AW-UE40", "AW-UE30",
    ):
        module = resolve_model(model)
        assert module is not None, model
        assert module.BUTTON_FEATURES["white_clip"] == {
            "kind": "toggle", "on": "OSA:2E:1", "off": "OSA:2E:0",
            "query": "QSA:2E", "query_on_value": "1",
        }, model


def test_night_mode_uses_correct_command_not_crop_marker_command() -> None:
    # §3.2.27 "Night mode settings": OSD:B2:[Data] (0=Manual/1=Auto), Query
    # QSD:B2 -- "Only supported by the AW-HE40/AW-UE70/AW-HE42" (Modell-
    # zuordnung war schon richtig). Der bisherige Katalog nutzte faelschlich
    # OSI:1A/QSI:1A, das laut PDF zu einer CROP-Marker-Farbauswahl fuer
    # AK-UB300/AW-UE150 gehoert, nicht zu Night Mode.
    for model in ("AW-HE40", "AW-HE42", "AW-UE70"):
        module = resolve_model(model)
        assert module is not None, model
        assert module.BUTTON_FEATURES["night_mode"] == {
            "kind": "toggle", "on": "OSD:B2:1", "off": "OSD:B2:0",
            "query": "QSD:B2", "query_on_value": "1",
        }, model


def test_ue160_knee_toggle_uses_command_list_for_on_side() -> None:
    # AW-UE160s Knee braucht laut Referenzquelle zwei Kommandos je
    # Zielzustand (OSL:45 aktiviert den manuellen/Auto-Modus ueberhaupt
    # erst, OSA:2D waehlt Manual/Auto) -- "on" ist deshalb eine Liste,
    # "off" bleibt ein einzelner, gemeinsamer Befehl.
    from drivers.panasonic_models import aw_ue160

    assert aw_ue160.BUTTON_FEATURES["knee_manual"] == {
        "kind": "toggle", "on": ["OSL:45:1", "OSA:2D:1"], "off": "OSL:45:0",
    }
    assert aw_ue160.BUTTON_FEATURES["knee_auto"] == {
        "kind": "toggle", "on": ["OSL:45:1", "OSA:2D:2"], "off": "OSL:45:0",
    }
