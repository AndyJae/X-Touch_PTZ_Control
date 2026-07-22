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
import tempfile
from pathlib import Path
from types import SimpleNamespace

import mido
import rtmidi

import core.application as core_application
from core.application import AppState, build_app_state, disconnect_camera
from core.companion import CompanionError
from core.config import AppConfig
from midi.fader import XTouchFader, _MUTE_NOTE_BASE, _REC_NOTE_BASE, _SELECT_NOTE_BASE, _SOLO_NOTE_BASE
from tests.fakes import FakeCameraDriver


def _run(coro):
    return asyncio.run(coro)


class FakeOutPort:
    def __init__(self) -> None:
        self.sent: list = []

    def send(self, msg) -> None:
        self.sent.append(msg)


class FailingOutPort:
    """Simuliert einen MIDI-Ausgang, dessen Send-Versuche wie bei einem vom
    USB-Bus entfernten/sistierten Geraet fehlschlagen (Bugreport 2026-07-22:
    `_rtmidi.SystemError: MidiOutWinMM::sendMessage: error sending MIDI
    message` nach laengerer Inaktivitaet)."""

    def send(self, msg) -> None:
        raise rtmidi.SystemError("MidiOutWinMM::sendMessage: error sending MIDI message.")

    def close(self) -> None:
        pass


# button2 -> "drs" (Toggle, siehe drivers/panasonic_models/aw_ue160.py, von
# FakeCameraDriver wiederverwendet); button3 bewusst unbelegt (No-Op-Test);
# companion-Ziel fuer den Select-Test. cam2/Kanal 2 bewusst NICHT verbunden
# (siehe _build_fader) -- deckt den Nutzerentscheid ab, dass Rec/Select nur
# auf Kanaelen mit tatsaechlich verbundener Kamera leuchten duerfen.
TEST_CONFIG = AppConfig.model_validate(
    {
        "cameras": [
            {"id": "cam1", "name": "CAM 1", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9999},
            {"id": "cam2", "name": "CAM 2", "driver": "panasonic_aw", "host": "127.0.0.1", "port": 9998},
        ],
        "banks": [
            {
                "name": "Bank A",
                "channels": [
                    {
                        "camera": "cam1",
                        "buttons": {"button2": "drs"},
                        "companion": {"page": 1, "row": 0, "column": 2},
                    },
                    {
                        "camera": "cam2",
                        "companion": {"page": 1, "row": 0, "column": 3},
                    },
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
    # Bugfix 2026-07-20: `config_path="config.yaml"` war ein woertlicher
    # relativer Pfad auf die ECHTE Projekt-config.yaml -- disconnect_camera()
    # (seit heute speichernd) hat darueber tatsaechlich die reale Datei des
    # Nutzers ueberschrieben (Bugreport: config.yaml zeigte Test-Fixture-
    # Daten). Immer ein frisches Temp-Verzeichnis verwenden.
    config_path = str(Path(tempfile.mkdtemp()) / "config.yaml")
    state = build_app_state(TEST_CONFIG.model_copy(deep=True), config_path=config_path)
    _run(state.drivers["cam1"].connect())
    # cam2 bleibt absichtlich getrennt (kein .connect()) -- Kanal 2 hat damit
    # eine zugewiesene, aber nicht verbundene Kamera (anders als Kanal 8,
    # das ueberhaupt keine hat).

    fader = XTouchFader(state, "fake-in", "fake-out")
    out_port = FakeOutPort()
    fader._out_port = out_port
    # Bildet die Subscriptions aus XTouchFader.start() nach, ohne echte MIDI-
    # Ports zu oeffnen (siehe Modul-Docstring: Rx ist Polling auf einem
    # echten Port, hier nicht Testgegenstand).
    for topic in ("connection_changed", "feature_changed", "config_changed"):
        state.event_bus.subscribe(topic, fader._on_scribble_relevant_event)
    state.event_bus.subscribe("connection_changed", fader._on_connection_changed)
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


def test_rec_led_only_on_for_channel_with_connected_camera(monkeypatch) -> None:
    # Nutzerentscheid 2026-07-20: Rec hat keine On/Off-Logik (waehlt nur die
    # Encoder-Funktion), leuchtet aber NUR auf Kanaelen mit tatsaechlich
    # verbundener Kamera -- Kanal 1 (cam1 verbunden) an, Kanal 2 (cam2
    # zugewiesen, aber nicht verbunden) und Kanal 8 (ueberhaupt keine Kamera)
    # aus.
    fader, _state, out_port = _build_fader(monkeypatch)

    fader._refresh_button_leds()

    def last_velocity(offset: int) -> int:
        led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _REC_NOTE_BASE + offset]
        return led_msgs[-1].velocity

    assert last_velocity(0) == 127  # Kanal 1: cam1 verbunden
    assert last_velocity(1) == 0  # Kanal 2: cam2 zugewiesen, aber nicht verbunden
    assert last_velocity(7) == 0  # Kanal 8: keine Kamera zugewiesen


def test_select_led_off_when_companion_not_connected(monkeypatch) -> None:
    # Nutzerentscheid 2026-07-20: Select leuchtet nur, wenn Companion
    # verbunden ist (AppState.companion_connected) -- TEST_CONFIG setzt das
    # nicht, Default ist False.
    fader, state, out_port = _build_fader(monkeypatch)
    assert state.companion_connected is False

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 0)))

    led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SELECT_NOTE_BASE]
    assert led_msgs[-1].velocity == 0


def test_select_led_requires_connected_camera_on_that_channel(monkeypatch) -> None:
    # Nutzerentscheid 2026-07-20: Select leuchtet nur auf Kanaelen mit
    # tatsaechlich verbundener Kamera -- Kanal 2 hat cam2 zugewiesen, aber
    # cam2 ist in _build_fader() bewusst nicht verbunden.
    fader, state, out_port = _build_fader(monkeypatch)
    state.companion_connected = True

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 1)))  # Kanal 2

    led_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SELECT_NOTE_BASE + 1]
    assert led_msgs[-1].velocity == 0


def test_select_led_lights_only_last_pressed_channel_when_companion_connected(monkeypatch) -> None:
    fader, state, out_port = _build_fader(monkeypatch)
    _run(state.drivers["cam2"].connect())  # beide Kanaele verbunden, um das Umschalten zu testen
    state.companion_connected = True

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 0)))  # Kanal 1

    ch1_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SELECT_NOTE_BASE]
    assert ch1_msgs[-1].velocity == 127

    _run(fader._handle(_note_on(_SELECT_NOTE_BASE + 1)))  # Kanal 2

    ch1_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SELECT_NOTE_BASE]
    ch2_msgs = [m for m in out_port.sent if m.type == "note_on" and m.note == _SELECT_NOTE_BASE + 1]
    assert ch1_msgs[-1].velocity == 0
    assert ch2_msgs[-1].velocity == 127


def test_disconnecting_camera_drives_motor_fader_to_zero(monkeypatch) -> None:
    # Bugreport 2026-07-20: Motorfader blieb beim Trennen einer Kamera auf
    # der zuletzt bekannten Position stehen -- disconnect_camera() setzt
    # cam_state.iris jetzt auf 0.0 zurueck, _on_connection_changed() faehrt
    # den Motor entsprechend.
    fader, state, out_port = _build_fader(monkeypatch)
    state.state_store.get_camera("cam1").iris = 1.0
    fader._send_fader_position(1, 1.0)  # Ausgangsposition: ganz oben
    out_port.sent.clear()

    _run(disconnect_camera(state, "cam1"))

    pitch_msgs = [m for m in out_port.sent if m.type == "pitchwheel" and m.channel == 0]
    assert pitch_msgs, "kein Pitchbend fuer Kanal 1 nach dem Trennen gesendet"
    assert pitch_msgs[-1].pitch == fader._protocol.normalized_to_pitchbend(0.0) - 8192


def test_send_reconnects_and_retries_after_transient_rtmidi_error(monkeypatch) -> None:
    # Bugreport 2026-07-22: erster Send-Versuch wirft rtmidi.SystemError (wie
    # nach einer von Windows sistierten USB-Verbindung) -- _send() muss den
    # Ausgang neu oeffnen und den Send auf dem neuen Port wiederholen.
    fader, _state, _out_port = _build_fader(monkeypatch)
    fader._out_port = FailingOutPort()
    reconnected_port = FakeOutPort()
    monkeypatch.setattr("midi.fader.mido.open_output", lambda name: reconnected_port)

    fader._send(mido.Message("note_on", note=1, velocity=127))

    assert len(reconnected_port.sent) == 1
    assert fader._out_port is reconnected_port


def test_send_swallows_error_when_reconnect_also_fails(monkeypatch, caplog) -> None:
    fader, _state, _out_port = _build_fader(monkeypatch)
    fader._out_port = FailingOutPort()

    def raise_open(name):
        raise OSError("device not found")

    monkeypatch.setattr("midi.fader.mido.open_output", raise_open)

    fader._send(mido.Message("note_on", note=1, velocity=127))  # darf nicht raisen

    assert "konnte nicht neu verbunden werden" in caplog.text
    assert fader._out_port is None


def test_button_action_does_not_raise_when_midi_send_fails(monkeypatch) -> None:
    # Reproduziert den eigentlichen Bugreport: ein fehlgeschlagener MIDI-Send
    # waehrend des LED-Refreshs (ausgeloest ueber denselben EventBus-Pfad wie
    # ein Web-UI-Klick) darf `apply_button_action()`/`_handle()` nicht zum
    # Absturz bringen -- der Kamerabefehl selbst muss trotzdem durchlaufen.
    fader, state, _out_port = _build_fader(monkeypatch)
    fader._out_port = FailingOutPort()
    monkeypatch.setattr(
        "midi.fader.mido.open_output",
        lambda name: (_ for _ in ()).throw(OSError("device not found")),
    )

    _run(fader._handle(_note_on(_SOLO_NOTE_BASE + 0)))  # darf nicht raisen

    assert state.drivers["cam1"].button_feature_calls == [("drs", True)]
