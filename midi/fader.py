"""midi/fader.py -- Bidirektionale X-Touch-Extender-Faderanbindung (Spec §5,
aktueller Umfang: Fader/Touch <-> Iris (§5.2/§5.4), Scribble Strips (§5.3)
und Encoder (§9: feste Funktionsliste gain/pedestal/camera_status ueber
Button 1, Drehen, Push). Encoder-Drehen sendet bei gain/pedestal seit
Nutzerentscheid SOFORT live einen Kamerabefehl (ueber
`core.application.apply_encoder_turn`s eigenen Rate-Limiter je Kamera,
analog zum Iris-Fader) -- der Encoder-Push (Note 32-39) sendet dagegen
nichts mehr, sondern markiert den Kanal nur visuell als "gespeichert"
(Spec §9 nannte die Push-Verwendung urspruenglich "noch offen"). Encoder-
LED-Ring (CC 48-55) ist weiterhin nicht Teil dieser Verdrahtung -- Encoding
dafuer laut Spec §14 unverifiziert. Resync-bei-Hotplug (§5.5) folgt in
einem weiteren Schritt.

Note-/CC-Belegung gegen den realen X-Touch Extender verifiziert (Kanal 1:
Pitchbend Kanal 1 = Fader 1, Note 104 = Fader-Touch 1); ebenso die
Scribble-Strip-Device-ID (0x15, siehe unten), siehe Offene Punkte in
CLAUDE.md.

Rx: Polling statt mido-Callback-Thread -- `tools/midi_monitor.py` nutzt
denselben Ansatz und wurde bereits live gegen das Geraet verifiziert; ein
rtmidi-Callback laeuft aus einem eigenen C-Thread und muesste erst
umstaendlich an den asyncio-Loop zurueckgereicht werden.

Tx Fader: reagiert auf `iris_changed` auf demselben EventBus, den auch der
WebSocket-Broadcast abonniert (siehe core/bus.py-Docstring: MIDI und Web-UI
sind gleichwertige Publisher/Subscriber). Ohne dieses Tx bleibt der
Motorfader auf der zuletzt bekannten Position stehen und federt dorthin
zurueck, sobald man loslaesst -- deshalb Teil dieser ersten Verdrahtung und
nicht erst der spaeteren Resync/Hotplug-Stufe.

Tx Scribble Strips: Vollabzug aller 8 Strips bei `connection_changed`/
`feature_changed`/`config_changed`. `iris_changed` aktualisiert dagegen
gezielt nur die eine betroffene Zeile 2 (kein Vollabzug bei jedem Iris-Tick,
sonst unnoetiger SysEx-Traffic waehrend des Fader-Ziehens). Zeile 2 zeigt
laut Spec §5.3 eigentlich die F-Nummer -- die Hex->F-Nummer-Tabelle ist laut
Spec aber nicht vollstaendig dokumentiert (siehe Kommentar an
PanasonicAWDriver._query_f_number), daher als Platzhalter die Iris-% bis
diese Umrechnung nachgeruestet wird."""

from __future__ import annotations

import asyncio
import logging

import mido

from core.application import (
    AppState,
    apply_encoder_turn,
    apply_iris,
    channel_display_text,
    channel_line1_text,
    channel_snapshot,
    commit_encoder_value,
    cycle_encoder_function,
)
from midi.mackie import MackieControlProtocol

LOGGER = logging.getLogger("ptz_control.midi")

_FADER_TOUCH_NOTE_BASE = 104  # 0x68, Note 104-111 -> Fader-Touch 1-8 (Spec §5.2)
_REC_NOTE_BASE = 0  # Note 0-7 -> Rec/Button 1 je Kanal (Encoder-Funktionsauswahl, Spec §9)
_ENCODER_CC_BASE = 16  # CC 16-23 (0x10-0x17) -> Encoder 1-8 drehen, relativ (Spec §5.2/§9)
_ENCODER_PUSH_NOTE_BASE = 32  # Note 32-39 -> Encoder-Push 1-8: committet den Pending-Wert (Spec §9/§5.2)
_POLL_INTERVAL = 0.01

# --- Scribble Strips (Spec §5.3) ---
_SCRIBBLE_STRIP_CHARS = 7
_SCRIBBLE_UPPER_BASE = 0x00  # obere Zeile: 0x00-0x37, 7 Zeichen x 8 Strips
_SCRIBBLE_LOWER_BASE = 0x38  # untere Zeile: 0x38-0x6F


def _scribble_text(text: str) -> str:
    return (text or "")[:_SCRIBBLE_STRIP_CHARS].ljust(_SCRIBBLE_STRIP_CHARS)


_SCRIBBLE_DEVICE_ID = 0x15  # X-Touch Extender -- 0x14 waere der reguläre X-Touch (live verifiziert:
# 0x14 blieb auf dem Extender-Display leer, 0x15 zeigt Text an). Bestaetigt den in
# CLAUDE.md offen markierten Punkt "Device-ID des Extenders verifizieren".


def _scribble_message(offset: int, text: str) -> mido.Message:
    payload = _scribble_text(text)
    data = (0x00, 0x00, 0x66, _SCRIBBLE_DEVICE_ID, 0x12, offset, *(ord(c) for c in payload))
    return mido.Message("sysex", data=data)


class XTouchFader:
    """Rx: Pitchbend/Touch -> `core.application.apply_iris` (Spec §3
    Datenfluss Fader -> Mapping -> Rate-Limiter -> Driver). Tx: `iris_changed`
    -> Motorfader-Position, ausser waehrend aktivem Touch (Spec §5.4)."""

    def __init__(self, state: AppState, input_port_name: str, output_port_name: str | None) -> None:
        self._state = state
        self._input_port_name = input_port_name
        self._output_port_name = output_port_name
        self._protocol = MackieControlProtocol()
        self._in_port: mido.ports.BaseInput | None = None
        self._out_port: mido.ports.BaseOutput | None = None
        self._task: asyncio.Task[None] | None = None
        self._touch_active: dict[int, bool] = {}
        self._last_value: dict[int, float] = {}

    async def start(self) -> None:
        self._in_port = mido.open_input(self._input_port_name)
        self._task = asyncio.create_task(self._poll_loop())
        LOGGER.info("MIDI-Eingang verbunden: %s", self._input_port_name)
        if self._output_port_name is not None:
            self._out_port = mido.open_output(self._output_port_name)
            self._state.event_bus.subscribe("iris_changed", self._on_iris_changed)
            for topic in ("connection_changed", "feature_changed", "config_changed"):
                self._state.event_bus.subscribe(topic, self._on_scribble_relevant_event)
            LOGGER.info("MIDI-Ausgang verbunden: %s", self._output_port_name)
            await self._resync_from_state()
            self._refresh_scribble_strips()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._in_port is not None:
            self._in_port.close()
            self._in_port = None
        if self._out_port is not None:
            self._out_port.close()
            self._out_port = None

    # --- Rx: Fader/Touch -> Iris ---------------------------------------

    async def _poll_loop(self) -> None:
        assert self._in_port is not None
        while True:
            # Innerhalb eines Polling-Takts nur die jeweils juengste
            # Pitchbend-Nachricht pro Kanal verarbeiten (Rate-Limiter-Vertrag
            # "Latest-wins", siehe core/ratelimit.py) -- sonst arbeitet der
            # Loop bei einer schnellen Fader-Bewegung eine Warteschlange aus
            # laengst ueberholten Zwischenwerten ab, waehrend der reale
            # Kamera-Request auf ein langsames Netzwerk wartet (beobachteter
            # Nachlauf/"hackt" beim Live-Test).
            latest_pitch: dict[int, mido.Message] = {}
            other_messages: list[mido.Message] = []
            for msg in self._in_port.iter_pending():
                if msg.type == "pitchwheel":
                    latest_pitch[msg.channel] = msg
                else:
                    other_messages.append(msg)
            for msg in other_messages:
                await self._handle(msg)
            for msg in latest_pitch.values():
                await self._handle(msg)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _handle(self, msg: mido.Message) -> None:
        if msg.type == "pitchwheel":
            channel_index = msg.channel + 1
            value = self._protocol.pitchbend_to_normalized(msg.pitch + 8192)
            self._last_value[channel_index] = value
            # Laufende Bewegung geht immer durch den Rate-Limiter (Spec §8);
            # nur der Touch-Release unten erzwingt einen finalen Sendevorgang
            # (Spec §5.4).
            await apply_iris(self._state, channel_index, value, final=False)
        elif msg.type == "note_on" and _FADER_TOUCH_NOTE_BASE <= msg.note < _FADER_TOUCH_NOTE_BASE + 8:
            channel_index = msg.note - _FADER_TOUCH_NOTE_BASE + 1
            touched = msg.velocity > 0
            was_touched = self._touch_active.get(channel_index, False)
            self._touch_active[channel_index] = touched
            if was_touched and not touched and channel_index in self._last_value:
                # Touch-Release: letzten Soll-Wert final senden (Spec §5.4)
                await apply_iris(self._state, channel_index, self._last_value[channel_index], final=True)
        elif (
            msg.type == "note_on"
            and _REC_NOTE_BASE <= msg.note < _REC_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Rec/Button 1: schaltet nur die lokale Encoder-Funktionsauswahl
            # weiter, kein Kamerabefehl (Spec §9). Nur auf Press reagieren,
            # nicht auf Release, sonst wuerde ein Tastendruck zweimal zaehlen.
            # Zeile 1 wechselt dabei zwischen Kameraname und Funktionsname
            # (Nutzerentscheid) -- deshalb Vollabzug beider Zeilen statt nur
            # Zeile 2 wie bei Drehen/Push.
            channel_index = msg.note - _REC_NOTE_BASE + 1
            await cycle_encoder_function(self._state, channel_index)
            self._refresh_channel_full(channel_index)
        elif msg.type == "control_change" and _ENCODER_CC_BASE <= msg.control < _ENCODER_CC_BASE + 8:
            channel_index = msg.control - _ENCODER_CC_BASE + 1
            delta = self._protocol.encoder_cc_to_delta(msg.value)
            await apply_encoder_turn(self._state, channel_index, delta)
            self._refresh_channel_line2(channel_index)
        elif (
            msg.type == "note_on"
            and _ENCODER_PUSH_NOTE_BASE <= msg.note < _ENCODER_PUSH_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Encoder-Push: sendet keinen Kamerabefehl mehr (gain/pedestal
            # senden seit Nutzerentscheid schon live beim Drehen, siehe
            # Modul-Docstring) -- markiert den Wert nur visuell als
            # "gespeichert". Nur auf Press reagieren, nicht auf Release.
            channel_index = msg.note - _ENCODER_PUSH_NOTE_BASE + 1
            await commit_encoder_value(self._state, channel_index)
            self._refresh_channel_line2(channel_index)

    # --- Tx: Iris -> Motorfader ------------------------------------------

    async def _resync_from_state(self) -> None:
        """Einmalig beim Verbinden: aktuell bekannte Iris-Position jedes
        gemappten Kanals an den Motorfader senden, sonst haelt der Motor die
        zuletzt gesendete Position (z. B. von einem frueheren Test)."""
        for channel_index, mapping in self._state.mapping.channels_for_type("fader").items():
            cam_state = self._state.state_store.get_camera(mapping.camera_id)
            if cam_state.iris is not None:
                self._send_fader_position(channel_index, cam_state.iris)

    async def _on_iris_changed(self, payload: dict) -> None:
        channel_index = self._channel_for_camera(payload["camera_id"])
        if channel_index is None:
            return
        if not self._touch_active.get(channel_index, False):
            # Spec §5.4: waehrend Touch nicht gegen den Finger schreiben --
            # gilt nur fuer den Motor, nicht fuer die Strip-Anzeige unten.
            self._send_fader_position(channel_index, payload["value"])
        self._send_iris_percent_line(channel_index, payload["value"])

    def _channel_for_camera(self, camera_id: str) -> int | None:
        for channel_index, mapping in self._state.mapping.channels_for_type("fader").items():
            if mapping.camera_id == camera_id:
                return channel_index
        return None

    def _send_fader_position(self, channel_index: int, value: float) -> None:
        if self._out_port is None:
            return
        pitch = self._protocol.normalized_to_pitchbend(value) - 8192
        self._out_port.send(mido.Message("pitchwheel", channel=channel_index - 1, pitch=pitch))

    # --- Tx: Scribble Strips (Spec §5.3) ---------------------------------

    async def _on_scribble_relevant_event(self, _payload: dict) -> None:
        self._refresh_scribble_strips()

    def _refresh_scribble_strips(self) -> None:
        """Vollabzug aller 8 Strips (wie channel_snapshot() selbst, kein
        inkrementelles Diffing) -- ausgeloest durch die seltenen Events
        (Connect/Disconnect, Feature-Toggle, Config-Aenderung). Zeile 1/2
        kommen aus `channel_line1_text()`/`channel_display_text()`
        (core/application.py) -- denselben Funktionen, die auch die Web-UI
        fuer die EINE verbleibende Kanal-Anzeige verwendet (Nutzerentscheid:
        physisches Geraet und Web-UI duerfen nicht auseinanderlaufen)."""
        for ch in channel_snapshot(self._state):
            if ch["camera_id"] is None:
                upper, lower = "", "----"
            elif not ch["connected"]:
                upper, lower = ch["name"] or "", "NC"
            else:
                upper, lower = ch["display_line1"], ch["display_text"]
            self._send_scribble_strip(ch["index"], upper, lower)

    def _refresh_channel_full(self, channel_index: int) -> None:
        """Aktualisiert BEIDE Zeilen nach einem Funktionswechsel (Rec/
        Button 1) -- Zeile 1 wechselt zwischen Kameraname (camera_status) und
        Funktionsname (gain/pedestal, Nutzerentscheid), Zeile 2 zeigt den
        neuen Wert. Kein Vollabzug aller 8 Strips dafuer noetig."""
        if self._out_port is None:
            return
        entry = self._state.mapping.get_channel("fader", channel_index)
        if entry is None:
            return
        camera_cfg = self._state.cameras.get(entry.camera_id)
        cam_state = self._state.state_store.get_camera(entry.camera_id)
        upper = channel_line1_text(self._state, channel_index, camera_cfg.name if camera_cfg else None)
        lower = channel_display_text(self._state, channel_index, cam_state.iris)
        self._send_scribble_strip(channel_index, upper, lower)

    def _refresh_channel_line2(self, channel_index: int) -> None:
        """Aktualisiert Zeile 2 nur des einen betroffenen Kanals nach einem
        Encoder-Ereignis (Drehen/Push) -- Zeile 1 (Kameraname/Funktionsname)
        aendert sich dabei nicht, kein Vollabzug aller 8 Strips noetig."""
        if self._out_port is None:
            return
        entry = self._state.mapping.get_channel("fader", channel_index)
        if entry is None:
            return
        cam_state = self._state.state_store.get_camera(entry.camera_id)
        self._send_line2_text(channel_index, channel_display_text(self._state, channel_index, cam_state.iris))

    def _send_iris_percent_line(self, channel_index: int, value: float) -> None:
        """Ausgeloest durch `iris_changed` -- respektiert die aktive Encoder-
        Funktion ueber `channel_display_text()` (Bugfix: zeigte vorher immer
        Iris-%, auch wenn Zeile 2 gerade gain/pedestal anzeigte, und
        ueberschrieb das kurzzeitig waehrend eines Fader-Zugs)."""
        self._send_line2_text(channel_index, channel_display_text(self._state, channel_index, value))

    def _send_line2_text(self, channel_index: int, text: str) -> None:
        if self._out_port is None:
            return
        strip = channel_index - 1
        offset = _SCRIBBLE_LOWER_BASE + strip * _SCRIBBLE_STRIP_CHARS
        self._out_port.send(_scribble_message(offset, text))

    def _send_scribble_strip(self, channel_index: int, upper: str, lower: str) -> None:
        if self._out_port is None:
            return
        strip = channel_index - 1
        self._out_port.send(_scribble_message(_SCRIBBLE_UPPER_BASE + strip * _SCRIBBLE_STRIP_CHARS, upper))
        self._out_port.send(_scribble_message(_SCRIBBLE_LOWER_BASE + strip * _SCRIBBLE_STRIP_CHARS, lower))
