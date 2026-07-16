"""
tools/midi_monitor.py -- Roher MIDI-Rx-Monitor fuer den X-Touch Extender
(Dev-Werkzeug, kein Produktionscode).

Entspricht dem in ptz-shading-tool-spec.md Abschnitt 5.2 erwaehnten
Debug-Modus ("ein Debug-Modus (--midi-monitor) loggt alle Rx-Messages roh").
Zweck: die dort als Annahme markierte Mackie-Control-Note-/CC-Belegung
gegen das reale Geraet verifizieren, bevor midi/ auf dieser Annahme
aufgebaut wird (offener Punkt in CLAUDE.md).

Nur Rx (Fader, Touch, Encoder, Buttons) -- kein Tx/Feedback, keine
Motorfader-Ansteuerung. Schreibt/aendert nichts an Kamera- oder App-Zustand.

Start:
    python tools/midi_monitor.py [--port <Teilstring>]
Ohne --port wird automatisch ein Eingangsport gesucht, dessen Name
"x-touch" enthaelt (Gross-/Kleinschreibung egal); bei Mehrdeutigkeit oder
keinem Treffer werden alle verfuegbaren Ports aufgelistet und das Skript
bricht ab.
"""

from __future__ import annotations

import argparse
import sys
import time

import mido

# Spec §5.2: Message-Mapping (MC-Standard), nur Rx-relevante Teile.
_FADER_TOUCH_NOTE_BASE = 104  # 0x68, Note 104-111 -> Fader-Touch 1-8
_ENCODER_PUSH_NOTE_BASE = 32  # 0x20, Note 32-39 -> Encoder-Push 1-8
_REC_NOTE_BASE = 0  # Note 0-7
_SOLO_NOTE_BASE = 8  # Note 8-15
_MUTE_NOTE_BASE = 16  # Note 16-23
_SELECT_NOTE_BASE = 24  # Note 24-31
_ENCODER_CC_BASE = 16  # 0x10, CC 16-23 -> Encoder 1-8 drehen


def _decode_note(note: int) -> str:
    for base, label in (
        (_REC_NOTE_BASE, "Rec"),
        (_SOLO_NOTE_BASE, "Solo"),
        (_MUTE_NOTE_BASE, "Mute"),
        (_SELECT_NOTE_BASE, "Select"),
        (_ENCODER_PUSH_NOTE_BASE, "Encoder-Push"),
        (_FADER_TOUCH_NOTE_BASE, "Fader-Touch"),
    ):
        if base <= note < base + 8:
            return f"{label} {note - base + 1} (erwartet laut Spec §5.2)"
    return "unbekannt (nicht in Spec §5.2 Tabelle)"


def _decode_cc(control: int, value: int) -> str:
    if _ENCODER_CC_BASE <= control < _ENCODER_CC_BASE + 8:
        direction = "+" if 1 <= value <= 7 else ("-" if 65 <= value <= 71 else f"wert={value}")
        return f"Encoder {control - _ENCODER_CC_BASE + 1} drehen, relativ {direction} (erwartet laut Spec §5.2)"
    return "unbekannt (nicht in Spec §5.2 Tabelle)"


def _find_port(substring: str | None) -> str:
    names = mido.get_input_names()
    if substring:
        matches = [n for n in names if substring.lower() in n.lower()]
    else:
        matches = [n for n in names if "x-touch" in n.lower()]
    if len(matches) == 1:
        return matches[0]
    print("Konnte keinen eindeutigen Eingangsport bestimmen.")
    print("Verfuegbare Eingangsports:")
    for n in names:
        print(" ", repr(n))
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None, help="Teilstring des MIDI-Eingangsport-Namens")
    args = parser.parse_args()

    port_name = _find_port(args.port)
    print(f"Oeffne Eingangsport: {port_name!r}")
    print("Bewege Fader/Encoder, druecke Buttons. Strg+C zum Beenden.\n")

    with mido.open_input(port_name) as inport:
        try:
            while True:
                for msg in inport.iter_pending():
                    ts = time.strftime("%H:%M:%S")
                    if msg.type in ("note_on", "note_off"):
                        print(f"[{ts}] {msg.type:9s} note={msg.note:3d} vel={msg.velocity:3d}  -> {_decode_note(msg.note)}")
                    elif msg.type == "control_change":
                        print(f"[{ts}] control_change control={msg.control:3d} value={msg.value:3d}  -> {_decode_cc(msg.control, msg.value)}")
                    elif msg.type == "pitchwheel":
                        print(f"[{ts}] pitchwheel channel={msg.channel + 1} pitch={msg.pitch:6d}  -> Fader {msg.channel + 1} (erwartet laut Spec §5.2)")
                    else:
                        print(f"[{ts}] {msg}")
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("\nBeendet.")


if __name__ == "__main__":
    main()
