"""tests/test_fader.py -- Rx/Tx-Verdrahtung von midi/fader.py fuer Solo/
Mute/Select (Spec §5.2/§9a), ohne echte MIDI-Hardware/-Ports.

`apply_button_action()`/`trigger_companion_select()` selbst sind bereits
vollstaendig in tests/test_application.py getestet -- hier geht es gezielt
um den Teil, der NUR in `midi/fader.py` lebt: Notenbereich -> Kanal/Slot-
Zuordnung (Rx) und die LED-Velocity-Ansteuerung (Tx, Nutzerentscheid
2026-07-18: rein binaer OFF=aus/ON=an, kein Blinken).

Kein Ersatz fuer den echten Hardware-Test (siehe CLAUDE.md-Offene-Punkte):
Rx-Notenbereiche sind bisher nur fuer Kanal 1 gegen das reale Geraet
verifiziert, LED-Tx fuer keinen der vier Tastentypen.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import core.application as core_application
from core.application import AppState, build_app_state
from core.companion import CompanionError
from core.config import AppConfig
from midi.fader import XTouchFader, _MUTE_NOTE_BASE, _SELECT_NOTE_BASE, _SOLO_NOTE_BASE
from tests.fakes import FakeCameraDriver


def _run(coro):
    return asyncio.run(coro)


class FakeOutPort:
    def __init__(self) -> None:
        self.sent: list = []

    def send(self, msg) -> None:
        self.sent.append(msg)


# button2 -> "drs" (Toggle, siehe drivers/panasonic_models/aw_ue160.py, von
# FakeCameraDriver wiederverwendet); button3 bewusst unbelegt (No-Op-Test);
# companion-Ziel fuer den Select-Test.
TEST_CONFIG = AppConfig.model_validate(
    {
        "cameras": [
            {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
        ],
        "banks": [
            {
                "name": "Bank A",
                "channels": [
                    {
                        "camera": "cam1",
                        "buttons": {"button2": "drs"},
                        "companion": {"page": 1, "row": 0, "column": 2},
                    }
                ],
            }
        ],
        "channel_defaults": {"fader": "iris"},
        "companion": {"host": "192.168.0.50", "port": 8000},
        "global": {"rate_limit_hz": 15},
    }
)


def _build_fader(monkeypatch) -> tuple[XTouchFader, AppState, FakeOutPort]:
    monkeypatch.setattr(
        core_application,
        "build_driver",
        lambda camera: FakeCameraDriver(camera.host, camera.port),
    )
    state = build_app_state(TEST_CONFIG, config_path="config.yaml")
    _run(state.drivers["cam1"].connect())

    fader = XTouchFader(state, "fake-in", "fake-out")
    out_port = FakeOutPort()
    fader._out_port = out_port
    # Bildet die Subscriptions aus XTouchFader.start() nach, ohne echte MIDI-
    # Ports zu oeffnen (siehe Modul-Docstring: Rx ist Polling auf einem
    # echten Port, hier nicht Testgegenstand).
    for topic in ("connection_changed", "feature_changed", "config_changed"):
        state.event_bus.subscribe(topic, fader._on_scribble_relevant_event)
    return fader, state, out_port


def _note_on(note: int, velocity: int = 127) -> SimpleNamespace:
    return SimpleNamespace(type="note_on", note=note, velocity=velocity)


def test_solo_press_triggers_button2_action_and_lights_led(monkeypatch) -> None:
    fader, state, out_port = _build_fader(monkeypatch)

    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 0)))  # Kanal 1

    assert state.drivers["cam1"].button_feature_calls == [("drs", True)]
    led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SOLO_NOTE_BASE]
    assert led_msgs[-1].velocity == 127


def test_second_solo_press_turns_led_off(monkeypatch) -> None:
    fader, _state, out_port = _build_fader(monkeypatch)

    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 0)))
    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 0)))

    led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SOLO_NOTE_BASE]
    assert led_msgs[-1].velocity == 0


def test_mute_press_without_assignment_is_noop(monkeypatch) -> None:
    fader, state, _out_port = _build_fader(monkeypatch)  # button3 ist in TEST_CONFIG nicht zugeordnet

    _run(fader._handle(_note_on(_MUTE_NOTE_BASE + 0)))

    assert state.drivers["cam1"].button_feature_calls == []


def test_solo_note_release_is_ignored(monkeypatch) -> None:
    fader, state, _out_port = _build_fader(monkeypatch)

    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 0, velocity=0)))  # Release

    assert state.drivers["cam1"].button_feature_calls == []


def test_solo_note_on_unmapped_channel_does_not_raise(monkeypatch) -> None:
    fader, state, _out_port = _build_fader(monkeypatch)

    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 7)))  # Kanal 8, in TEST_CONFIG ungemappt

    assert state.drivers["cam1"].button_feature_calls == []


def test_select_press_triggers_companion_with_configured_target(monkeypatch) -> None:
    fader, _state, _out_port = _build_fader(monkeypatch)
    calls = []

    async def fake_press_button(client, host, port, page, row, column):
        calls.append((host, port, page, row, column))

    monkeypatch.setattr(core_application, "press_button", fake_press_button)

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 0)))

    assert calls == [("192.168.0.50", 8000, 1, 0, 2)]


def test_select_press_companion_error_is_caught_not_raised(monkeypatch, caplog) -> None:
    fader, _state, _out_port = _build_fader(monkeypatch)

    async def failing_press_button(client, host, port, page, row, column):
        raise CompanionError("boom")

    monkeypatch.setattr(core_application, "press_button", failing_press_button)

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 0)))  # darf nicht raisen

    assert "Companion-SELECT fehlgeschlagen" in caplog.text


def test_refresh_button_leds_reflects_unknown_state_as_off(monkeypatch) -> None:
    # cam_state.feature_states["drs"] ist zu Beginn unbekannt (kein Query,
    # kein Druck) -- Nutzerentscheid: unbekannt zeigt wie in der Web-UI
    # unbeleuchtet, nicht an.
    fader, _state, out_port = _build_fader(monkeypatch)

    fader._refresh_button_leds()

    led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SOLO_NOTE_BASE]
    assert led_msgs[-1].velocity == 0
