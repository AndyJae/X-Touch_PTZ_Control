from __future__ import annotations

import asyncio

import httpx
import pytest

from drivers.base import CameraCommandError
from drivers.panasonic_aw import (
    PanasonicAWDriver,
    _data_to_iris,
    _iris_to_data,
    _parse_lens_info_iris,
    _parse_notification_payload,
)


def _run(coro):
    return asyncio.run(coro)


def _build_driver(handler) -> PanasonicAWDriver:
    driver = PanasonicAWDriver(host="192.168.0.10", port=80)
    driver._client = httpx.AsyncClient(
        base_url="http://192.168.0.10:80",
        transport=httpx.MockTransport(handler),
    )
    driver._connected = True
    # Bypass von connect() (kein echter QID-Roundtrip in diesen Tests) --
    # BUTTON_FEATURES/-LABELS werden seit dem Modell-Registry-Umbau (§9a)
    # erst dort ueber das erkannte Modell aufgeloest, hier also von Hand.
    driver.model = "AW-UE160"
    driver._apply_model_catalog()
    return driver


def test_iris_scaling_boundaries() -> None:
    assert _iris_to_data(0.0) == 0x555
    assert _iris_to_data(1.0) == 0xFFF
    assert _data_to_iris(0x555) == pytest.approx(0.0)
    assert _data_to_iris(0xFFF) == pytest.approx(1.0)


def test_set_iris_sends_correct_url_and_hash_encoding() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.set_iris(0.0))
    _run(driver.set_iris(1.0))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23AXI555&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23AXIFFF&res=1"


def test_set_gain_db_uses_aw_cam_endpoint_and_correct_data() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.set_gain_db(0))
    _run(driver.set_gain_db(-6))
    _run(driver.set_gain_db(12))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:08&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:02&res=1"
    assert seen[2] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:14&res=1"


def test_step_gain_reads_current_value_then_sets_new_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "cmd=QGU" in url:
            return httpx.Response(200, text="OGU:0C")  # 0x0C - 0x08 = +4 dB
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_db = _run(driver.step_gain(3))

    assert new_db == 7  # +4dB + 3 -> +7dB
    assert seen[-1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OGU:0F&res=1"  # 0x08+7=0x0F


def test_step_gain_raises_when_agc_active() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OGU:80")  # 80h = AGC aktiv

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.step_gain(1))


def test_query_pedestal_parses_offset_from_center() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QSJ:0F" in str(request.url)
        return httpx.Response(200, text="OSJ:0F:764")  # 0x764 - 0x800 = -156

    driver = _build_driver(handler)
    value = _run(driver._query_pedestal())

    assert value == 0x764 - 0x800


def test_step_pedestal_reads_current_value_then_sets_new_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "cmd=QSJ:0F" in url:
            return httpx.Response(200, text="OSJ:0F:800")  # 0
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_value = _run(driver.step_pedestal(20))

    assert new_value == 20
    assert seen[-1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSJ:0F:814&res=1"  # 0x800+20=0x814


def test_step_pedestal_clamps_to_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cmd=QSJ:0F" in str(request.url):
            return httpx.Response(200, text="OSJ:0F:8C8")  # +200, bereits am Maximum
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    new_value = _run(driver.step_pedestal(50))

    assert new_value == 200


def test_step_pedestal_raises_when_unreadable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="garbage")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.step_pedestal(1))


def test_camera_error_response_raises_with_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ER3:out of range")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError) as excinfo:
        _run(driver.set_gain_db(99))
    assert excinfo.value.response == "ER3:out of range"


def test_ptz_endpoint_error_prefix_is_recognized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="eR2")

    driver = _build_driver(handler)
    with pytest.raises(CameraCommandError):
        _run(driver.set_iris(0.5))


def test_query_model_extracts_model_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QID" in str(request.url)
        return httpx.Response(200, text="OID:AW-UE160")

    driver = _build_driver(handler)
    model = _run(driver._query_model())
    assert model == "AW-UE160"


def test_apply_model_catalog_resolves_known_model() -> None:
    # Spec §9a, Modell-Registry-Umbau: BUTTON_FEATURES ist seitdem
    # modellabhaengig statt fest auf AW-UE160 -- AW-HE50 hat laut Quelle
    # (drivers/panasonic_models/aw_he50.py, portiert aus smart_reset_work)
    # z.B. keinen "knee"-Eintrag, im Unterschied zu AW-UE160. `drs` hat 3
    # gueltige Werte (Off/Low/High, Data-Wert 2 nicht belegt), als je ein
    # Toggle pro Zielzustand (Nutzerentscheid 2026-07-18: kein "cycle"-
    # Feature mehr auf Button 2/3), siehe aw_he50.py.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-HE50"
    driver._apply_model_catalog()

    assert driver.BUTTON_FEATURES["drs_low"] == {
        "kind": "toggle", "on": "OSE:33:1", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "1",
    }
    assert driver.BUTTON_FEATURES["drs_high"] == {
        "kind": "toggle", "on": "OSE:33:3", "off": "OSE:33:0", "query": "QSE:33", "query_on_value": "3",
    }
    assert "knee" not in driver.BUTTON_FEATURES
    assert driver.BUTTON_FEATURE_LABELS["drs_low"] == "DRS: Low"


def test_apply_model_catalog_resolves_alias_to_same_catalog_as_base_model() -> None:
    driver_base = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver_base.model = "AW-HE50"
    driver_base._apply_model_catalog()

    driver_alias = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver_alias.model = "AW-HE50H"  # CAMERA_ID_ALIASES-Eintrag von AW-HE50
    driver_alias._apply_model_catalog()

    assert driver_alias.BUTTON_FEATURES == driver_base.BUTTON_FEATURES
    assert driver_alias.BUTTON_FEATURE_LABELS == driver_base.BUTTON_FEATURE_LABELS


def test_apply_model_catalog_empty_for_unrecognized_model() -> None:
    # Kein erfundener Fallback (Spec §9a/CLAUDE.md) -- unbekanntes Modell
    # zeigt weder Button-Features noch einen Gain-/Pedestal-Wertebereich an,
    # verhindert aber nicht das Verbinden selbst.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "SOME-UNKNOWN-CAMERA"
    driver._apply_model_catalog()

    assert driver.BUTTON_FEATURES == {}
    assert driver.BUTTON_FEATURE_LABELS == {}
    assert driver.gain_min_db is None
    assert driver.gain_max_db is None
    assert driver.pedestal_command is None
    assert driver.pedestal_min is None
    assert driver.pedestal_max is None


def test_apply_model_catalog_resolves_gain_pedestal_for_ue160() -> None:
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-UE160"
    driver._apply_model_catalog()

    assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (-6, 12, 1)
    assert driver.pedestal_command == "OSJ:0F"
    assert driver.pedestal_query_command == "QSJ:0F"
    assert (driver.pedestal_min, driver.pedestal_max) == (-200, 200)
    assert driver.pedestal_center_data == 0x800
    assert (driver.pedestal_scale, driver.pedestal_data_width) == (1, 3)


def test_apply_model_catalog_resolves_gain_pedestal_for_he50_otp_family() -> None:
    # AW-HE50 nutzt laut HDIntegratedCamera_InterfaceSpecifications-E.pdf
    # §3.2.6/§3.2.14 ein anderes Gain-Raster (nur 3dB-Schritte, 0-18dB) und
    # eine andere Pedestal-Kommandofamilie (OTP/QTP statt OSJ:0F) als UE160.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-HE50"
    driver._apply_model_catalog()

    assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (0, 18, 3)
    assert driver.pedestal_command == "OTP"
    assert driver.pedestal_query_command == "QTP"
    assert (driver.pedestal_min, driver.pedestal_max) == (-10, 10)
    assert driver.pedestal_center_data == 0x96
    assert (driver.pedestal_scale, driver.pedestal_data_width) == (15, 3)


def test_apply_model_catalog_resolves_gain_pedestal_for_he120_wide_pedestal_range() -> None:
    # AW-HE120 teilt sich die OTP/QTP-Kommandofamilie mit AW-HE50, aber mit
    # einem anderen Bereich/Skalierung (-150..+150 statt -10..+10).
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-HE120"
    driver._apply_model_catalog()

    assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (0, 18, 1)
    assert driver.pedestal_command == "OTP"
    assert (driver.pedestal_min, driver.pedestal_max) == (-150, 150)
    assert (driver.pedestal_center_data, driver.pedestal_scale) == (0x96, 1)


def test_apply_model_catalog_resolves_gain_pedestal_for_ue100() -> None:
    # AW-UE100 hat ein eigenes dediziertes Referenz-PDF
    # (docs/specs/AW-UE100_InterfaceSpecification_E.pdf, nachtraeglich ins
    # Repo gelegt) -- Gain-Ankerpunkte/-Bereich sind zufaellig identisch zu
    # AW-HR140/AW-UE150A, Pedestal-Kommando identisch zu AW-UE150A/AW-UE160
    # (OSJ:0F), aber eigenstaendig aus dieser PDF verifiziert, nicht davon
    # abgeleitet.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-UE100"
    driver._apply_model_catalog()

    assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (0, 42, 1)
    assert driver.pedestal_command == "OSJ:0F"
    assert driver.pedestal_query_command == "QSJ:0F"
    assert (driver.pedestal_min, driver.pedestal_max) == (-200, 200)
    assert driver.pedestal_center_data == 0x800


def test_apply_model_catalog_resolves_gain_pedestal_for_ue80_and_aliases() -> None:
    # AW-UE80/UE50/UE40/UE30 teilen sich ein dediziertes PDF
    # (docs/specs/AW-UE80UE50UE40_InterfaceSpecification_E.pdf, deckt laut
    # eigener "applicable models"-Angabe alle vier ab) -- gleiche Werte wie
    # AW-UE100, aber aus dieser eigenen Quelle verifiziert.
    for model in ("AW-UE80", "AW-UE50", "AW-UE40", "AW-UE30"):
        driver = PanasonicAWDriver(host="127.0.0.1", port=80)
        driver.model = model
        driver._apply_model_catalog()

        assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (0, 42, 1), model
        assert driver.pedestal_command == "OSJ:0F", model
        assert driver.pedestal_query_command == "QSJ:0F", model
        assert (driver.pedestal_min, driver.pedestal_max) == (-200, 200), model


def test_apply_model_catalog_ak_ub300_has_pedestal_but_no_gain() -> None:
    # AK-UB300 nutzt fuer Gain ein strukturell anderes Region-Select-Schema
    # (OGS + OSA:50/51/52), das nicht in set_gain_db(db)/step_gain(delta)
    # passt -- bewusst kein GAIN_MIN_DB/MAX_DB in ak_ub300.py. Pedestal
    # (OSG:4A) passt dagegen ins bestehende Set/Step-Interface.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AK-UB300"
    driver._apply_model_catalog()

    assert driver.gain_min_db is None
    assert driver.gain_max_db is None
    assert driver.pedestal_command == "OSG:4A"
    assert driver.pedestal_query_command == "QSG:4A"
    assert (driver.pedestal_min, driver.pedestal_max) == (-99, 99)
    assert (driver.pedestal_center_data, driver.pedestal_scale, driver.pedestal_data_width) == (0x80, 1, 2)


def test_apply_model_catalog_resolves_gain_pedestal_for_he145_via_ue145_alias() -> None:
    # Korrektur 2026-07-18: "AW-UE145" war urspruenglich die (falsche)
    # CAMERA_ID, ist jetzt nur noch Alias von "AW-HE145" (echte QID-Antwort
    # laut docs/specs/AW-UE150HE145_InterfaceSpecification_E.pdf) -- der per
    # QID erkannte String "AW-UE145" muss trotzdem weiterhin auf denselben
    # Katalog/dieselben Gain-/Pedestal-Werte aufloesen.
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)
    driver.model = "AW-UE145"
    driver._apply_model_catalog()

    assert driver.BUTTON_FEATURES  # Button-Katalog ist vorhanden
    assert (driver.gain_min_db, driver.gain_max_db, driver.gain_step_db) == (-3, 42, 1)
    assert driver.pedestal_command == "OSJ:0F"


def test_set_pedestal_uses_otp_command_for_he50() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    driver.model = "AW-HE50"
    driver._apply_model_catalog()

    _run(driver.set_pedestal(0))
    _run(driver.set_pedestal(10))
    _run(driver.set_pedestal(-10))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OTP:096&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OTP:12C&res=1"  # 0x96+10*15=0x12C
    assert seen[2] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OTP:000&res=1"  # 0x96-10*15=0x000


def test_query_pedestal_uses_model_query_command_for_ak_ub300() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QSG:4A" in str(request.url)
        return httpx.Response(200, text="OSG:4A:E3")  # 0xE3 - 0x80 = +99

    driver = _build_driver(handler)
    driver.model = "AK-UB300"
    driver._apply_model_catalog()

    value = _run(driver._query_pedestal())
    assert value == 99


def test_step_gain_clamps_to_he50_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cmd=QGU" in str(request.url):
            return httpx.Response(200, text="OGU:1A")  # 0x1A-0x08=+18dB, bereits am Maximum
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    driver.model = "AW-HE50"
    driver._apply_model_catalog()

    new_db = _run(driver.step_gain(5))
    assert new_db == 18  # geclamped auf GAIN_MAX_DB=18 (nicht +23)


def test_set_pedestal_raises_when_model_has_no_pedestal_data() -> None:
    # Mittlerweile hat jedes registrierte Modell (ausser AK-UB300, das aber
    # Pedestal ueber OSG:4A hat) Pedestal-Daten -- dieser Pfad wird also nur
    # noch fuer ein unbekanntes/nicht aufloesbares Modell durchlaufen.
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    driver.model = "SOME-UNKNOWN-CAMERA"
    driver._apply_model_catalog()

    with pytest.raises(CameraCommandError):
        _run(driver.set_pedestal(0))


def test_connect_resolves_button_catalog_from_detected_model(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cmd=QID" in str(request.url):
            return httpx.Response(200, text="OID:AW-HE50")
        return httpx.Response(200, text="ER1:unhandled")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_async_client(
            base_url=kwargs.get("base_url", ""), transport=httpx.MockTransport(handler)
        ),
    )
    driver = PanasonicAWDriver(host="127.0.0.1", port=80)

    _run(driver.connect())

    assert driver.model == "AW-HE50"
    assert driver.connected is True
    assert "drs_low" in driver.BUTTON_FEATURES
    assert "knee" not in driver.BUTTON_FEATURES


def test_query_iris_parses_position_and_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="gi7ff1")

    driver = _build_driver(handler)
    iris, auto_iris = _run(driver._query_iris())

    assert iris == pytest.approx(_data_to_iris(0x7FF))
    assert auto_iris is True


def test_get_state_aggregates_queries() -> None:
    responses = {
        "cmd=%23GI": "gi5551",
        "cmd=QIF": "OIF:0E",
        "cmd=QGU": "OGU:08",
        "cmd=QSJ:0F": "OSJ:0F:800",
        "cmd=QFT": "OFT:2",
        "cmd=QER": "rER1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, text in responses.items():
            if key in url:
                return httpx.Response(200, text=text)
        raise AssertionError(f"unexpected request: {url}")

    driver = _build_driver(handler)
    state = _run(driver.get_state())

    assert state.iris == pytest.approx(0.0)
    assert state.auto_iris is True
    assert state.iris_f_number == "0E"
    assert state.gain_db == 0
    assert state.pedestal == 0
    assert state.nd_index == 2
    assert state.error == "rER1"


def test_trigger_button_feature_toggle_sends_on_and_off() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("drs", enabled=True))
    _run(driver.trigger_button_feature("drs", enabled=False))

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:0D:1&res=1"
    assert seen[1] == "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:0D:0&res=1"


def test_trigger_button_feature_trigger_ignores_enabled() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("awb_black"))

    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=OAS&res=1"]


def test_trigger_button_feature_auto_iris_delegates_to_set_auto_iris() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("auto_iris", enabled=True))

    # Muss ueber set_auto_iris() laufen (ORS:1), nicht ueber eine zweite,
    # eigene Kommando-Implementierung fuer denselben Befehl.
    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=ORS:1&res=1"]


def test_trigger_button_feature_aww_white_delegates_to_trigger_awb() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("aww_white"))

    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=OWS&res=1"]


def test_trigger_button_feature_toggle_without_enabled_raises() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    with pytest.raises(ValueError):
        _run(driver.trigger_button_feature("drs"))


def test_trigger_button_feature_unknown_key_raises() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    with pytest.raises(ValueError):
        _run(driver.trigger_button_feature("does_not_exist", enabled=True))


def test_trigger_button_feature_toggle_on_sends_command_list() -> None:
    # AW-UE160s "knee_auto" braucht zwei Kommandos fuer "on" (OSL:45:1 +
    # OSA:2D:2) -- Nutzerentscheid 2026-07-18: Knee ist kein "cycle"-Feature
    # mehr, sondern je ein Toggle pro Zielzustand; "on"/"off" duerfen dafuer
    # eine Liste statt eines einzelnen Kommandos sein.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("knee_auto", enabled=True))

    assert seen == [
        "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSL:45:1&res=1",
        "http://192.168.0.10/cgi-bin/aw_cam?cmd=OSA:2D:2&res=1",
    ]


def test_trigger_button_feature_toggle_off_sends_single_shared_command() -> None:
    # "off" ist bei knee_manual/knee_auto derselbe einzelne Befehl (OSL:45:0)
    # -- als String, nicht als Liste, um zu pruefen, dass beide Formen
    # funktionieren.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)
    _run(driver.trigger_button_feature("knee_auto", enabled=False))

    assert seen == ["http://192.168.0.10/cgi-bin/aw_cam?cmd=OSL:45:0&res=1"]


def test_query_button_feature_returns_true_when_response_matches_on_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cmd=QSA:0D" in str(request.url)
        return httpx.Response(200, text="OSA:0D:1")

    driver = _build_driver(handler)
    assert _run(driver.query_button_feature("drs")) is True


def test_query_button_feature_returns_false_when_response_differs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OSA:0D:0")

    driver = _build_driver(handler)
    assert _run(driver.query_button_feature("drs")) is False


def test_query_button_feature_returns_none_without_known_query_command() -> None:
    # AW-UE160s knee_manual/knee_auto haben bewusst KEIN Query-Kommando
    # (siehe aw_ue160.py-Kommentar: Zustand haengt an zwei Befehlen, nicht
    # zuverlaessig aus einer einzelnen Abfrage ableitbar).
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    assert _run(driver.query_button_feature("knee_auto")) is None


def test_query_button_feature_returns_none_for_unknown_key() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    assert _run(driver.query_button_feature("does_not_exist")) is None


def test_query_button_feature_returns_none_on_camera_error() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text="ER1:QSA:0D"))
    assert _run(driver.query_button_feature("drs")) is None


def test_query_button_feature_auto_iris_uses_existing_iris_query() -> None:
    # Sonderfall wie in trigger_button_feature(): nutzt #GI (Mode-Bit) statt
    # eines eigenen Query-Kommandos fuer auto_iris.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="gi7ff1")  # Mode 1 = Auto

    driver = _build_driver(handler)
    assert _run(driver.query_button_feature("auto_iris")) is True


# --- Update-Notification-Kanal / Lens-Info (§7.3) ---------------------------
# Die Hex-Fixtures sind raw TCP-Captures gegen eine reale AW-UE160 nach
# #LPC1-Registrierung (siehe CLAUDE.md Offene Punkte) -- kein konstruiertes
# Beispiel, sondern das tatsaechlich beobachtete Frame-Layout.
_REAL_LPC1_ACK_FRAME = bytes.fromhex(
    "c0a8000a0001170101011025000100800000000000010010010000000d0a"
    "6c5043310d0a00020018b8208e1725ba0001170101011025000000000000"
)
_REAL_LPI_FRAME = bytes.fromhex(
    "c0a8000a0002170101011025000100800000000000010018010000000d0a"
    "6c50493535353842444439420d0a00020018b8208e1725ba00011701010110"
    "25000000000000"
)


def test_parse_notification_payload_lpc1_ack() -> None:
    assert _parse_notification_payload(_REAL_LPC1_ACK_FRAME) == "lPC1"


def test_parse_notification_payload_lpi() -> None:
    assert _parse_notification_payload(_REAL_LPI_FRAME) == "lPI5558BDD9B"


def test_parse_notification_payload_too_short_returns_none() -> None:
    assert _parse_notification_payload(b"\x00" * 10) is None


def test_parse_lens_info_iris_extracts_last_group() -> None:
    # lPI[ZZZ][FFF][III] -- Iris sind die letzten 3 Hex-Digits (§7.3.2)
    assert _parse_lens_info_iris("lPI5558BDD9B") == pytest.approx(_data_to_iris(0xD9B))


def test_parse_lens_info_iris_wrong_prefix_returns_none() -> None:
    assert _parse_lens_info_iris("OIF:2B") is None


class _FakeWriter:
    def close(self) -> None:
        pass


class _FakeReader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, n: int) -> bytes:
        return self._data


def test_handle_notification_fires_iris_changed_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_REAL_LPI_FRAME), _FakeWriter()))

    assert events == [{"type": "iris_changed", "value": pytest.approx(_data_to_iris(0xD9B))}]


def test_handle_notification_non_lpi_payload_fires_no_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_REAL_LPC1_ACK_FRAME), _FakeWriter()))

    assert events == []


def test_start_lens_feedback_registers_and_enables_lpc1() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)

    async def scenario() -> None:
        await driver.start_lens_feedback()
        try:
            assert "cgi-bin/event?connect=start&my_port=" in seen[0]
            assert "uid=0" in seen[0]
            assert seen[1] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23LPC1&res=1"
        finally:
            await driver.stop_lens_feedback()

    _run(scenario())


def _build_notification_frame(payload: str) -> bytes:
    """Synthetisches Notification-Frame (Header-Reserves als Nullbytes, da
    fuer die reine Payload-Auswertung irrelevant) -- Layout wie bei den
    echten `_REAL_LPI_FRAME`/`_REAL_LPC1_ACK_FRAME`-Captures oben (22B
    Reserve, 2B Big-Endian-Size = Payload-Laenge+8, 4B Reserve, Payload,
    24B Reserve)."""
    payload_bytes = payload.encode("ascii")
    size = len(payload_bytes) + 8
    return b"\x00" * 22 + size.to_bytes(2, "big") + b"\x00" * 4 + payload_bytes + b"\x00" * 24


def test_handle_notification_fires_feature_changed_for_single_command_toggle() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OSA:0D:1")), _FakeWriter()))

    assert events == [{"type": "feature_changed", "key": "drs", "enabled": True}]


def test_handle_notification_fires_feature_changed_for_off_command() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OSA:0D:0")), _FakeWriter()))

    assert events == [{"type": "feature_changed", "key": "drs", "enabled": False}]


def test_handle_notification_fires_feature_changed_for_command_list_toggle() -> None:
    # AW-UE160s "knee_manual" braucht laut Katalog zwei Kommandos fuer "on"
    # (["OSL:45:1", "OSA:2D:1"]) -- die Kamera meldet vermutlich jedes
    # geaenderte Kommando als eigene Notification, hier wird nur eines davon
    # zugestellt.
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OSA:2D:1")), _FakeWriter()))

    assert events == [{"type": "feature_changed", "key": "knee_manual", "enabled": True}]


def test_handle_notification_unknown_command_fires_no_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("XYZ:1")), _FakeWriter()))

    assert events == []


def test_handle_notification_fires_gain_changed() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OGU:0E")), _FakeWriter()))

    assert events == [{"type": "gain_changed", "value": 6}]


def test_handle_notification_gain_agc_fires_no_callback() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OGU:80")), _FakeWriter()))

    assert events == []


def test_handle_notification_fires_pedestal_changed() -> None:
    # AW-UE160: PEDESTAL_COMMAND="OSJ:0F", CENTER_DATA=0x800, SCALE=1 --
    # Data 0x864 -> (0x864 - 0x800) // 1 == 100.
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OSJ:0F:864")), _FakeWriter()))

    assert events == [{"type": "pedestal_changed", "value": 100}]


def test_handle_notification_pedestal_ignored_for_model_without_pedestal_command() -> None:
    driver = _build_driver(lambda request: httpx.Response(200, text=""))
    driver.model = "AW-UNKNOWN-MODEL"
    driver._apply_model_catalog()
    assert driver.pedestal_command is None
    events: list[dict] = []
    driver.subscribe(events.append)

    _run(driver._handle_notification(_FakeReader(_build_notification_frame("OSJ:0F:864")), _FakeWriter()))

    assert events == []


def test_stop_lens_feedback_sends_lpc0_and_deregisters() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="")

    driver = _build_driver(handler)

    async def scenario() -> None:
        await driver.start_lens_feedback()
        seen.clear()
        await driver.stop_lens_feedback()

    _run(scenario())

    assert seen[0] == "http://192.168.0.10/cgi-bin/aw_ptz?cmd=%23LPC0&res=1"
    assert "cgi-bin/event?connect=stop&my_port=" in seen[1]
