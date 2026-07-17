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


def test_ue145_does_not_inherit_gain_pedestal_from_ue150() -> None:
    # AW-UE145 re-exportiert BUTTON_FEATURES von aw_ue150 (siehe aw_ue145.py),
    # ist aber in keiner der beiden Referenz-PDFs fuer Gain/Pedestal gelistet
    # ("applicable models" nennt nur AW-UE150/AW-UE155/AW-UN145) -- bewusst
    # kein GAIN_MIN_DB/PEDESTAL_COMMAND hier, kein erfundener Wert.
    module = resolve_model("AW-UE145")
    assert module is not None
    assert not hasattr(module, "GAIN_MIN_DB")
    assert not hasattr(module, "PEDESTAL_COMMAND")


def test_ak_ub300_has_pedestal_but_no_gain_module_constants() -> None:
    module = resolve_model("AK-UB300")
    assert module is not None
    assert not hasattr(module, "GAIN_MIN_DB")
    assert module.PEDESTAL_COMMAND == "OSG:4A"
