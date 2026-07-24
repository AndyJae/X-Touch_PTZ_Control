"""midi/fader.py -- Bidirectional Behringer X-Touch Extender fader link.

Covers fader/touch <-> iris, scribble strips, the encoder (fixed function
list gain/pedestal/nd/camera_status via button 1, turn, push), and
Solo/Mute/Select (button 2/3 -> dynamic feature catalog of the detected
camera model, Select -> Companion SELECT trigger). Encoder turns send
gain/pedestal/nd commands live to the camera through their own per-camera
rate limiter (`core.application.apply_encoder_turn`); the encoder push
sends nothing, it only marks the channel as visually "saved". The encoder
LED ring (CC 48-55) is not wired up.

Note/CC layout confirmed against real hardware for all 8 channels: fader
pitchbend, note 104-111 fader touch, note 0-7/8-15/16-23/24-31
Rec/Solo/Mute/Select, CC 16-23 encoder turn, note 32-39 encoder push.
Scribble-strip SysEx device ID is 0x15 (see below). LED colors (Rec/Mute
red, Solo yellow, Select green, fixed per button type, not selectable via
MIDI) are sourced from a community reference (github.com/Aldaviva/
BehringerXTouchExtender), not official Behringer documentation.

Rx uses polling rather than a mido callback thread, since an rtmidi
callback runs on its own C thread and would need to be handed back to the
asyncio loop.

Tx fader: reacts to `iris_changed` on the same event bus the WebSocket
broadcast subscribes to, so the motor fader doesn't spring back to a stale
position. `connection_changed` also drives the motor fader to the current
`cam_state.iris` (0 on disconnect, the real value on reconnect).

Tx scribble strips: a full refresh of all 8 strips on `connection_changed`/
`feature_changed`/`config_changed`/`gain_changed`/`pedestal_changed`/
`nd_changed`. `iris_changed` only updates the one affected channel's line 2,
to avoid SysEx traffic on every fader tick. `gain_changed`/
`pedestal_changed`/`nd_changed` fire both for actions taken here and for
externally triggered changes (e.g. the camera's own web UI), via
`PanasonicAWDriver._handle_notification()`.

Tx Rec/Solo/Mute/Select LEDs: the same events that refresh the scribble
strips also trigger a full LED refresh (`_refresh_button_leds()`). Solo/Mute
state is purely binary (no blinking). Rec lights up on any channel with a
connected camera, regardless of feature state -- it only selects the
encoder function, it has no on/off logic itself. Select lights only the
last-pressed channel, and only while Companion is connected and that
channel has a connected camera -- it stays a one-shot action with no
persistent success/failure state of its own."""

from __future__ import annotations

import asyncio
import logging

import mido
import rtmidi

from core.application import (
    AppState,
    apply_button_action,
    apply_encoder_turn,
    apply_iris,
    channel_display_text,
    channel_line1_text,
    channel_snapshot,
    commit_encoder_value,
    cycle_encoder_function,
    trigger_companion_select,
)
from core.companion import CompanionError
from midi.mackie import MackieControlProtocol

LOGGER = logging.getLogger("ptz_control.midi")

_FADER_TOUCH_NOTE_BASE = 104  # note 104-111 -> fader touch 1-8
_REC_NOTE_BASE = 0  # note 0-7 -> Rec/button 1 per channel (encoder function selection)
_SOLO_NOTE_BASE = 8  # note 8-15 -> Solo/button 2 per channel
_MUTE_NOTE_BASE = 16  # note 16-23 -> Mute/button 3 per channel
_SELECT_NOTE_BASE = 24  # note 24-31 -> Select per channel (Companion SELECT trigger)
_ENCODER_CC_BASE = 16  # CC 16-23 -> encoder 1-8 turn, relative mode
_ENCODER_PUSH_NOTE_BASE = 32  # note 32-39 -> encoder push 1-8
_POLL_INTERVAL = 0.01

# --- Scribble strips ---
_SCRIBBLE_STRIP_CHARS = 7
_SCRIBBLE_UPPER_BASE = 0x00  # upper line: 0x00-0x37, 7 chars x 8 strips
_SCRIBBLE_LOWER_BASE = 0x38  # lower line: 0x38-0x6F


def _scribble_text(text: str) -> str:
    return (text or "")[:_SCRIBBLE_STRIP_CHARS].ljust(_SCRIBBLE_STRIP_CHARS)


_SCRIBBLE_DEVICE_ID = 0x15  # X-Touch Extender (0x14 is the regular X-Touch)


def _scribble_message(offset: int, text: str) -> mido.Message:
    payload = _scribble_text(text)
    data = (0x00, 0x00, 0x66, _SCRIBBLE_DEVICE_ID, 0x12, offset, *(ord(c) for c in payload))
    return mido.Message("sysex", data=data)


class XTouchFader:
    """Rx: pitchbend/touch -> `core.application.apply_iris`. Tx:
    `iris_changed` -> motor fader position, except while actively touched."""

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
        self._last_select_channel: int | None = None

    async def start(self) -> None:
        self._in_port = mido.open_input(self._input_port_name)
        self._task = asyncio.create_task(self._poll_loop())
        LOGGER.info("MIDI-Eingang verbunden: %s", self._input_port_name)
        if self._output_port_name is not None:
            self._out_port = mido.open_output(self._output_port_name)
            self._state.event_bus.subscribe("iris_changed", self._on_iris_changed)
            self._state.event_bus.subscribe("connection_changed", self._on_connection_changed)
            for topic in (
                "connection_changed",
                "feature_changed",
                "config_changed",
                "gain_changed",
                "pedestal_changed",
                "nd_changed",
            ):
                self._state.event_bus.subscribe(topic, self._on_scribble_relevant_event)
            LOGGER.info("MIDI-Ausgang verbunden: %s", self._output_port_name)
            await self._resync_from_state()
            self._refresh_scribble_strips()
            self._refresh_button_leds()

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
            await self._poll_once()
            await asyncio.sleep(_POLL_INTERVAL)

    async def _poll_once(self) -> None:
        """One polling tick: read + process pending messages. Reading and
        handling each have their own exception guard, so a transient MIDI
        error on either side can't permanently kill the poll loop."""
        # Only the latest pitchbend message per channel is processed per
        # tick (rate-limiter "latest-wins" contract) -- otherwise a fast
        # fader move queues up a backlog of stale intermediate values while
        # the real camera request is still waiting on the network.
        latest_pitch: dict[int, mido.Message] = {}
        other_messages: list[mido.Message] = []
        try:
            for msg in self._in_port.iter_pending():
                if msg.type == "pitchwheel":
                    latest_pitch[msg.channel] = msg
                else:
                    other_messages.append(msg)
        except Exception:
            LOGGER.exception("MIDI-Eingang-Lesen fehlgeschlagen")
            return
        for msg in other_messages:
            await self._handle_safely(msg)
        for msg in latest_pitch.values():
            await self._handle_safely(msg)

    async def _handle_safely(self, msg: mido.Message) -> None:
        """Logs and swallows any exception from a single message handler,
        instead of letting it kill the whole Rx poll loop."""
        try:
            await self._handle(msg)
        except Exception:
            LOGGER.exception("MIDI-Eingang-Verarbeitung fehlgeschlagen fuer %r", msg)

    async def _handle(self, msg: mido.Message) -> None:
        if msg.type == "pitchwheel":
            channel_index = msg.channel + 1
            value = self._protocol.pitchbend_to_normalized(msg.pitch + 8192)
            self._last_value[channel_index] = value
            # Ongoing movement always goes through the rate limiter; only
            # touch release below forces a final send.
            await apply_iris(self._state, channel_index, value, final=False)
        elif msg.type == "note_on" and _FADER_TOUCH_NOTE_BASE <= msg.note < _FADER_TOUCH_NOTE_BASE + 8:
            channel_index = msg.note - _FADER_TOUCH_NOTE_BASE + 1
            touched = msg.velocity > 0
            was_touched = self._touch_active.get(channel_index, False)
            self._touch_active[channel_index] = touched
            if was_touched and not touched and channel_index in self._last_value:
                # Touch release: send the last target value as final.
                await apply_iris(self._state, channel_index, self._last_value[channel_index], final=True)
        elif (
            msg.type == "note_on"
            and _REC_NOTE_BASE <= msg.note < _REC_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Rec/button 1: only advances the local encoder function
            # selection, no camera command. Press only, not release. Line 1
            # switches between camera name and function name, so both lines
            # are refreshed instead of just line 2.
            channel_index = msg.note - _REC_NOTE_BASE + 1
            await cycle_encoder_function(self._state, channel_index)
            self._refresh_channel_full(channel_index)
        elif (
            msg.type == "note_on"
            and _SOLO_NOTE_BASE <= msg.note < _SOLO_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Solo/button 2: fires the assigned camera feature action. LED
            # update comes via the same "feature_changed" event as a web UI
            # click, no separate call needed.
            channel_index = msg.note - _SOLO_NOTE_BASE + 1
            await apply_button_action(self._state, channel_index, "button2")
        elif (
            msg.type == "note_on"
            and _MUTE_NOTE_BASE <= msg.note < _MUTE_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Mute/button 3: see Solo/button 2 above.
            channel_index = msg.note - _MUTE_NOTE_BASE + 1
            await apply_button_action(self._state, channel_index, "button3")
        elif (
            msg.type == "note_on"
            and _SELECT_NOTE_BASE <= msg.note < _SELECT_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Select: fires the channel's Companion SELECT target, a
            # one-shot action with no persistent state. The LED shows the
            # last-pressed channel regardless of whether the trigger itself
            # succeeded. CompanionError is only logged here (unlike the web
            # route) so a connection error doesn't kill the poll loop.
            channel_index = msg.note - _SELECT_NOTE_BASE + 1
            self._last_select_channel = channel_index
            self._refresh_button_leds()
            try:
                await trigger_companion_select(self._state, channel_index)
            except CompanionError as exc:
                LOGGER.warning("Companion-SELECT fehlgeschlagen (Kanal %s): %s", channel_index, exc)
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
            # Encoder push: sends no camera command (gain/pedestal already
            # send live on turn), only marks the value as visually "saved".
            channel_index = msg.note - _ENCODER_PUSH_NOTE_BASE + 1
            await commit_encoder_value(self._state, channel_index)
            self._refresh_channel_line2(channel_index)

    # --- Tx: Iris -> Motorfader ------------------------------------------

    async def _resync_from_state(self) -> None:
        """Once on connect: sends the currently known iris position of every
        mapped channel to the motor fader, so it doesn't hold a stale
        position from an earlier session."""
        for channel_index, mapping in self._state.mapping.channels_for_type("fader").items():
            cam_state = self._state.state_store.get_camera(mapping.camera_id)
            if cam_state.iris is not None:
                self._send_fader_position(channel_index, cam_state.iris)

    async def _on_iris_changed(self, payload: dict) -> None:
        channel_index = self._channel_for_camera(payload["camera_id"])
        if channel_index is None:
            return
        if not self._touch_active.get(channel_index, False):
            # Don't fight the finger while the fader is being touched --
            # only applies to the motor, not the strip display below.
            self._send_fader_position(channel_index, payload["value"])
        self._refresh_channel_line2(channel_index)

    async def _on_connection_changed(self, payload: dict) -> None:
        """Drives the motor fader to the current `cam_state.iris` position
        when a camera's connection status changes (0 on disconnect, the real
        value on reconnect -- this method just reads the already-updated
        value)."""
        channel_index = self._channel_for_camera(payload["camera_id"])
        if channel_index is None:
            return
        cam_state = self._state.state_store.get_camera(payload["camera_id"])
        if cam_state.iris is not None:
            self._send_fader_position(channel_index, cam_state.iris)

    def _channel_for_camera(self, camera_id: str) -> int | None:
        for channel_index, mapping in self._state.mapping.channels_for_type("fader").items():
            if mapping.camera_id == camera_id:
                return channel_index
        return None

    def _send(self, msg: mido.Message) -> None:
        """Central Tx path for all MIDI output (fader motor, scribble
        strips, button LEDs). A failed send attempts one reconnect
        (`_reconnect_output()`) and retries; if that also fails, the send is
        dropped and logged, never propagated to the caller -- an unhandled
        send error would otherwise kill both the poll loop and any web
        request that publishes an event."""
        if self._out_port is None:
            return
        try:
            self._out_port.send(msg)
            return
        except rtmidi.RtMidiError as exc:
            LOGGER.warning("MIDI-Ausgang-Send fehlgeschlagen (%s), versuche Neuverbindung", exc)
        if not self._reconnect_output():
            return
        try:
            self._out_port.send(msg)
        except rtmidi.RtMidiError as exc:
            LOGGER.warning("MIDI-Ausgang nach Neuverbindung weiterhin fehlgeschlagen: %s", exc)

    def _reconnect_output(self) -> bool:
        if self._output_port_name is None:
            return False
        try:
            self._out_port.close()
        except Exception:
            pass
        try:
            self._out_port = mido.open_output(self._output_port_name)
        except Exception as exc:
            LOGGER.warning("MIDI-Ausgang %s konnte nicht neu verbunden werden: %s", self._output_port_name, exc)
            self._out_port = None
            return False
        LOGGER.info("MIDI-Ausgang neu verbunden: %s", self._output_port_name)
        return True

    def _send_fader_position(self, channel_index: int, value: float) -> None:
        pitch = self._protocol.normalized_to_pitchbend(value) - 8192
        self._send(mido.Message("pitchwheel", channel=channel_index - 1, pitch=pitch))

    # --- Tx: scribble strips -----------------------------------------------

    async def _on_scribble_relevant_event(self, _payload: dict) -> None:
        self._refresh_scribble_strips()
        self._refresh_button_leds()

    def _refresh_scribble_strips(self) -> None:
        """Full refresh of all 8 strips, triggered by the infrequent events
        (connect/disconnect, feature toggle, config change). Lines 1/2 come
        from `channel_line1_text()`/`channel_display_text()`, the same
        functions the web UI uses for its channel display."""
        for ch in channel_snapshot(self._state):
            if ch["camera_id"] is None:
                upper, lower = "", "----"
            elif not ch["connected"]:
                upper, lower = ch["name"] or "", "NC"
            else:
                upper, lower = ch["display_line1"], ch["display_text"]
            self._send_scribble_strip(ch["index"], upper, lower)

    def _refresh_channel_full(self, channel_index: int) -> None:
        """Updates both lines after a function switch (Rec/button 1) --
        line 1 switches between camera name and function name, line 2 shows
        the new value. No need to refresh all 8 strips for this."""
        if self._out_port is None:
            return
        entry = self._state.mapping.get_channel("fader", channel_index)
        if entry is None:
            return
        camera_cfg = self._state.cameras.get(entry.camera_id)
        upper = channel_line1_text(self._state, channel_index, camera_cfg.name if camera_cfg else None)
        lower = channel_display_text(self._state, channel_index)
        self._send_scribble_strip(channel_index, upper, lower)

    def _refresh_channel_line2(self, channel_index: int) -> None:
        """Updates only line 2 of the one affected channel -- after an
        encoder event (turn/push, line 1 doesn't change) or after
        `iris_changed` (respects the active encoder function via
        `channel_display_text()`)."""
        if self._out_port is None:
            return
        entry = self._state.mapping.get_channel("fader", channel_index)
        if entry is None:
            return
        self._send_line2_text(channel_index, channel_display_text(self._state, channel_index))

    def _send_line2_text(self, channel_index: int, text: str) -> None:
        strip = channel_index - 1
        offset = _SCRIBBLE_LOWER_BASE + strip * _SCRIBBLE_STRIP_CHARS
        self._send(_scribble_message(offset, text))

    def _send_scribble_strip(self, channel_index: int, upper: str, lower: str) -> None:
        strip = channel_index - 1
        self._send(_scribble_message(_SCRIBBLE_UPPER_BASE + strip * _SCRIBBLE_STRIP_CHARS, upper))
        self._send(_scribble_message(_SCRIBBLE_LOWER_BASE + strip * _SCRIBBLE_STRIP_CHARS, lower))

    # --- Tx: Rec/Solo/Mute/Select LED --------------------------------------

    def _refresh_button_leds(self) -> None:
        """Full refresh of all four LED types across all 8 channels,
        triggered by the same events as the scribble strips plus directly
        after a Select press. Solo/Mute state comes from the same
        `_channel_button_snapshot()` source the web UI uses for its `is-on`
        class. Rec lights up on any channel with a connected camera,
        regardless of Solo/Mute feature state. Select lights only
        `_last_select_channel`, only while `AppState.companion_connected` is
        set and that channel has a connected camera."""
        for ch in channel_snapshot(self._state):
            self._send_button_led(ch["index"], _REC_NOTE_BASE, ch["connected"])
            for slot, note_base in (("button2", _SOLO_NOTE_BASE), ("button3", _MUTE_NOTE_BASE)):
                assigned = ch["buttons"][slot]
                on = bool(assigned and assigned["state"])
                self._send_button_led(ch["index"], note_base, on)
            select_on = (
                ch["connected"]
                and self._state.companion_connected
                and ch["index"] == self._last_select_channel
            )
            self._send_button_led(ch["index"], _SELECT_NOTE_BASE, select_on)

    def _send_button_led(self, channel_index: int, note_base: int, on: bool) -> None:
        note = note_base + (channel_index - 1)
        self._send(mido.Message("note_on", note=note, velocity=127 if on else 0))
