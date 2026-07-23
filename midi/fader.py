"""midi/fader.py -- Bidirektionale X-Touch-Extender-Faderanbindung (Spec §5,
aktueller Umfang: Fader/Touch <-> Iris (§5.2/§5.4), Scribble Strips (§5.3),
Encoder (§9: feste Funktionsliste gain/pedestal/nd/camera_status ueber
Button 1, Drehen, Push) sowie Solo/Mute/Select (§9a/§9: Button 2/3 ->
dynamischer Feature-Katalog des erkannten Kameramodells, Select ->
Companion-SELECT-Trigger). Encoder-Drehen sendet bei gain/pedestal/nd seit
Nutzerentscheid SOFORT live einen Kamerabefehl (ueber `core.application.apply_encoder_turn`s eigenen
Rate-Limiter je Kamera, analog zum Iris-Fader) -- der Encoder-Push (Note
32-39) sendet dagegen nichts mehr, sondern markiert den Kanal nur visuell als
"gespeichert" (Spec §9 nannte die Push-Verwendung urspruenglich "noch offen").
Encoder-LED-Ring (CC 48-55) ist weiterhin nicht Teil dieser Verdrahtung --
Encoding dafuer laut Spec §14 unverifiziert. Resync-bei-Hotplug (§5.5) folgt
in einem weiteren Schritt.

Note-/CC-Belegung gegen den realen X-Touch Extender verifiziert (Kanal 1:
Pitchbend Kanal 1 = Fader 1, Note 104 = Fader-Touch 1, Note 0/8/16/24 =
Rec/Solo/Mute/Select 1); ebenso die Scribble-Strip-Device-ID (0x15, siehe
unten), siehe Offene Punkte in CLAUDE.md. Solo/Mute/Select-LED-Tx (Note
On/Off zurueck ans Geraet) ist dagegen NEU und noch nicht gegen die reale
Hardware getestet -- nur Rx (Tastendruck empfangen) ist bisher verifiziert.
LED-Farben (Rec/Mute rot, Solo gelb, Select gruen, je Tastentyp fix, nicht
waehlbar) laut github.com/Aldaviva/BehringerXTouchExtender, keine offizielle
Behringer-Doku und nicht gegen reale Hardware verifiziert -- reine Velocity-
0/127-Ansteuerung (aus/an) aendert daran nichts, die Farbe ist Hardware-fix.

Rx: Polling statt mido-Callback-Thread -- `tools/midi_monitor.py` nutzt
denselben Ansatz und wurde bereits live gegen das Geraet verifiziert; ein
rtmidi-Callback laeuft aus einem eigenen C-Thread und muesste erst
umstaendlich an den asyncio-Loop zurueckgereicht werden.

Tx Fader: reagiert auf `iris_changed` auf demselben EventBus, den auch der
WebSocket-Broadcast abonniert (siehe core/bus.py-Docstring: MIDI und Web-UI
sind gleichwertige Publisher/Subscriber). Ohne dieses Tx bleibt der
Motorfader auf der zuletzt bekannten Position stehen und federt dorthin
zurueck, sobald man loslaesst -- deshalb Teil dieser ersten Verdrahtung und
nicht erst der spaeteren Resync/Hotplug-Stufe. Zusaetzlich (Bugreport
2026-07-20): `connection_changed` faehrt den Motorfader auf 0, wenn eine
Kamera ueber die Setup-Seite getrennt wird (`disconnect_camera()` setzt
`cam_state.iris` dafuer auf 0.0 zurueck) bzw. beim (Re-)Connect auf den
echten Kamerawert -- sonst blieb der Fader beim Trennen auf der zuletzt
gefahrenen Position stehen, obwohl `apply_iris()` Kamerabefehle fuer einen
getrennten Kanal ohnehin schon verwirft.

Tx Scribble Strips: Vollabzug aller 8 Strips bei `connection_changed`/
`feature_changed`/`config_changed`/`gain_changed`/`pedestal_changed`/
`nd_changed`. `iris_changed` aktualisiert dagegen gezielt nur die eine
betroffene Zeile 2 (kein Vollabzug bei jedem Iris-Tick, sonst unnoetiger
SysEx-Traffic waehrend des Fader-Ziehens). Zeile 2 zeigt laut Spec §5.3
eigentlich die F-Nummer -- die Hex->F-Nummer-Tabelle ist laut Spec aber
nicht vollstaendig dokumentiert (siehe Kommentar an
PanasonicAWDriver._query_f_number), daher als Platzhalter die Iris-% bis
diese Umrechnung nachgeruestet wird.
`gain_changed`/`pedestal_changed`/`nd_changed` kommen wie `feature_changed`
sowohl von eigenen Aktionen als auch von extern (z. B. Kamera-eigenes
Web-UI) ausgeloesten Aenderungen -- siehe
`PanasonicAWDriver._handle_notification()` und die generische
Update-Notification-Auswertung dort (§4.2 der HD Integrated Camera
Interface Specifications). **Nutzerreport 2026-07-22 (reale AW-UE160):**
`nd_changed` fehlte bisher komplett -- eine ND-Aenderung am Encoder
funktionierte zwar (Rx/Tx zur Kamera), eine externe ND-Aenderung (z. B. am
Kamera-eigenen Bedienfeld) wurde aber nicht erkannt, da
`_handle_notification()` `OFT`-Frames schlicht ignorierte.

Tx Rec/Solo/Mute/Select-LED: dieselben Events wie die Scribble Strips loesen
einen Vollabzug aller vier LED-Typen aus (`_refresh_button_leds()`) -- kein
eigenes Event noetig, `apply_button_action()`/`assign_channel_button()`
publizieren bereits `feature_changed`/`config_changed`. Solo/Mute:
Nutzerentscheid, Zustand rein binaer (OFF=Licht aus, ON=Licht an), kein
Blinken. Rec (Nutzerentscheid 2026-07-20): leuchtet dauerhaft auf allen 8
Kanaelen -- Rec hat keine On/Off-Logik, sondern waehlt nur die ueber den
Encoder einstellbare Funktion, die LED zeigt lediglich "hier ist eine
Encoder-Funktion waehlbar" an. Select (Nutzerentscheid 2026-07-20): leuchtet
nur, wenn Companion verbunden ist (`AppState.companion_connected`), und dann
immer nur auf dem zuletzt gedrueckten Kanal (`_last_select_channel`,
Instanzzustand dieser Klasse, kein Teil von AppState) -- Select selbst bleibt
weiterhin eine einmalige Companion-Aktion ohne Dauerzustand (siehe
`trigger_companion_select()`-Docstring in core/application.py), die LED
zeigt hier rein die zuletzt gedrueckte Taste, nicht einen Erfolgs-/
Fehlerzustand des Companion-Triggers."""

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

_FADER_TOUCH_NOTE_BASE = 104  # 0x68, Note 104-111 -> Fader-Touch 1-8 (Spec §5.2)
_REC_NOTE_BASE = 0  # Note 0-7 -> Rec/Button 1 je Kanal (Encoder-Funktionsauswahl, Spec §9)
_SOLO_NOTE_BASE = 8  # Note 8-15 -> Solo/Button 2 je Kanal (Spec §5.2/§9a)
_MUTE_NOTE_BASE = 16  # Note 16-23 -> Mute/Button 3 je Kanal (Spec §5.2/§9a)
_SELECT_NOTE_BASE = 24  # Note 24-31 -> Select je Kanal (Spec §9, Companion-SELECT-Trigger)
_ENCODER_CC_BASE = 16  # CC 16-23 (0x10-0x17) -> Encoder 1-8 drehen, relativ (Spec §5.2/§9)
_ENCODER_PUSH_NOTE_BASE = 32  # Note 32-39 -> Encoder-Push 1-8: committet den Pending-Wert (Spec §9/§5.2)
_POLL_INTERVAL = 0.01
# LED-Farben laut github.com/Aldaviva/BehringerXTouchExtender (Extender-spezifische
# Referenz, siehe CLAUDE.md-Offene-Punkte): Rec/Mute fix rot, Solo fix gelb, Select
# fix gruen -- je Tastentyp EINE feste Farbe, nicht per MIDI waehlbar. Steuerung
# bleibt binaer ueber Velocity (0=aus/127=an, Spec §5.2); Blinken (Velocity 1) wird
# lt. Nutzerentscheid nicht gebraucht.

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
        """Ein Polling-Takt: Nachrichten lesen + verarbeiten. Bugreport
        2026-07-23 (Fortsetzung): die vorherige Fassung fing Ausnahmen nur
        in `_handle()` ab (siehe `_handle_safely()`) -- `self._in_port.
        iter_pending()` selbst (das eigentliche Port-Lesen) war weiterhin
        UNGESCHUETZT. Nutzer meldete danach "gar keine Reaktion mehr auf dem
        Controller" (Fader/Rec/Solo/Mute/Select gleichermassen betroffen,
        nicht nur ein Feature) -- passt zu einer Ausnahme beim Lesen selbst
        (z. B. einem transienten `rtmidi`-Fehler), die weiterhin den
        gesamten `_poll_loop()` mitgerissen haette. War als "Rx-Seite hat
        keine eigene Fehlerbehandlung beim Lesen" bereits als offener,
        unbestaetigter Risikopfad dokumentiert (CLAUDE.md) -- jetzt ebenfalls
        abgefangen, analog zum bereits behobenen `_send()`-Tx-Fehler."""
        # Innerhalb eines Polling-Takts nur die jeweils juengste
        # Pitchbend-Nachricht pro Kanal verarbeiten (Rate-Limiter-Vertrag
        # "Latest-wins", siehe core/ratelimit.py) -- sonst arbeitet der
        # Loop bei einer schnellen Fader-Bewegung eine Warteschlange aus
        # laengst ueberholten Zwischenwerten ab, waehrend der reale
        # Kamera-Request auf ein langsames Netzwerk wartet (beobachteter
        # Nachlauf/"hackt" beim Live-Test).
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
        """Bugreport 2026-07-23: ein Fader-Zug bei aktivem Auto-Iris loeste
        (ueber `apply_iris()`s neue `driver.query_iris()`-Abfrage, siehe
        core/application.py) auf dem echten Geraet offenbar eine Ausnahme
        aus, die `_handle()` unbehandelt durchliess -- ohne eigene
        Fehlerbehandlung riss das `_poll_loop()` dauerhaft ab (kein
        Supervisor/Neustart), wodurch DANACH auch Rec/Solo/Mute/Select/
        Fader auf allen Kanaelen nicht mehr reagierten (nicht nur der Kanal,
        an dem es passierte) -- exakt das beobachtete "Button 1 laesst sich
        nicht mehr umschalten". War als Rx-seitiger Gegenpart zum bereits
        behobenen Tx-Fehler (`_send()`, s. o.) schon als offener, bisher
        unbestaetigter Risikopfad dokumentiert (CLAUDE.md) -- hiermit
        bestaetigt. Ein fehlgeschlagener Handler wird jetzt geloggt und
        uebersprungen, statt den gesamten Rx-Poll-Loop mitzureissen."""
        try:
            await self._handle(msg)
        except Exception:
            LOGGER.exception("MIDI-Eingang-Verarbeitung fehlgeschlagen fuer %r", msg)

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
        elif (
            msg.type == "note_on"
            and _SOLO_NOTE_BASE <= msg.note < _SOLO_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Solo/Button 2: loest die zugewiesene Kamera-Feature-Aktion aus
            # (Spec §9a, `apply_button_action`). LED-Update kommt ueber
            # denselben "feature_changed"-Event wie beim Web-UI-Klick, siehe
            # `_on_scribble_relevant_event` -- kein manueller Zusatzaufruf
            # noetig (EventBus.publish() wartet auf alle Subscriber, bevor
            # apply_button_action() zurueckkehrt).
            channel_index = msg.note - _SOLO_NOTE_BASE + 1
            await apply_button_action(self._state, channel_index, "button2")
        elif (
            msg.type == "note_on"
            and _MUTE_NOTE_BASE <= msg.note < _MUTE_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Mute/Button 3: siehe Solo/Button 2 oben.
            channel_index = msg.note - _MUTE_NOTE_BASE + 1
            await apply_button_action(self._state, channel_index, "button3")
        elif (
            msg.type == "note_on"
            and _SELECT_NOTE_BASE <= msg.note < _SELECT_NOTE_BASE + 8
            and msg.velocity > 0
        ):
            # Select: loest das hinterlegte Companion-SELECT-Ziel aus (Spec
            # §9, bewusste Erweiterung). Einmalige Aktion ohne Dauerzustand
            # (siehe trigger_companion_select()-Docstring). LED zeigt seit
            # Nutzerentscheid 2026-07-20 den zuletzt gedrueckten Kanal (nur
            # wenn Companion verbunden ist, siehe _refresh_button_leds()) --
            # das Nachziehen des LED-Zustands passiert unabhaengig davon, ob
            # der Trigger selbst erfolgreich war (reine Press-Anzeige, kein
            # Erfolgs-/Fehlerzustand). CompanionError wird hier (anders als
            # in der Web-Route) nur geloggt, damit ein Verbindungsfehler den
            # Poll-Loop nicht abbricht.
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
        self._refresh_channel_line2(channel_index)

    async def _on_connection_changed(self, payload: dict) -> None:
        """Faehrt den Motorfader auf die aktuelle `cam_state.iris`-Position
        nach, wenn sich der Verbindungsstatus einer Kamera aendert (Bugreport
        2026-07-20: der Fader blieb beim Trennen einer Kamera auf der zuletzt
        bekannten Position stehen). `disconnect_camera()` setzt `iris` dafuer
        bereits auf 0.0 zurueck, `connect_camera()` auf den echten
        Kamerawert -- diese Methode muss den Unterschied selbst nicht kennen,
        sie liest nur den bereits aktualisierten Wert und sendet ihn wie
        `_resync_from_state()` an den Motor (kein Touch-Check noetig, da eine
        Verbindungsaenderung nie waehrend eines aktiven physischen Fader-
        Zugs ausgeloest wird)."""
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
        """Zentraler Tx-Pfad fuer alle MIDI-Ausgangsnachrichten (Fader-Motor,
        Scribble-Strips, Button-LEDs). Bugreport 2026-07-22: nach laengerer
        Geraete-Inaktivitaet wirft `self._out_port.send()`
        `_rtmidi.SystemError` (WinMM meldet einen fehlgeschlagenen Send,
        vermutlich weil Windows das USB-Geraet zwischenzeitlich in einen
        Energiesparzustand versetzt hat -- extern, nicht verifiziert). Ohne
        Fehlerbehandlung riss das sowohl `_poll_loop()` ab (physisches Geraet
        reagiert danach dauerhaft nicht mehr, kein Supervisor/Neustart) als
        auch jeden Web-Request, der `event_bus.publish()` ausloest
        (`EventBus.publish()` hat keine eigene Fehlerbehandlung, siehe
        core/bus.py) -- exakt das beobachtete "nach einer Stunde reagiert
        weder Web-UI noch physisches Geraet". Ein fehlgeschlagener Send
        versucht deshalb einmalig eine Neuverbindung (`_reconnect_output()`)
        und wiederholt den Send; schlaegt auch das fehl, wird der Send
        verworfen und geloggt, nie an den Aufrufer weitergereicht."""
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

    # --- Tx: Scribble Strips (Spec §5.3) ---------------------------------

    async def _on_scribble_relevant_event(self, _payload: dict) -> None:
        self._refresh_scribble_strips()
        self._refresh_button_leds()

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
        upper = channel_line1_text(self._state, channel_index, camera_cfg.name if camera_cfg else None)
        lower = channel_display_text(self._state, channel_index)
        self._send_scribble_strip(channel_index, upper, lower)

    def _refresh_channel_line2(self, channel_index: int) -> None:
        """Aktualisiert Zeile 2 nur des einen betroffenen Kanals -- nach einem
        Encoder-Ereignis (Drehen/Push, Zeile 1 aendert sich dabei nicht) oder
        nach `iris_changed` (respektiert die aktive Encoder-Funktion ueber
        `channel_display_text()` -- Bugfix: zeigte vorher immer die Iris-
        Anzeige, auch wenn Zeile 2 gerade gain/pedestal anzeigte, und
        ueberschrieb das kurzzeitig waehrend eines Fader-Zugs). Kein Vollabzug
        aller 8 Strips noetig."""
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

    # --- Tx: Rec/Solo/Mute/Select-LED (Spec §5.2/§9/§9a) -------------------

    def _refresh_button_leds(self) -> None:
        """Vollabzug aller vier LED-Typen ueber alle 8 Kanaele -- ausgeloest
        durch dieselben Events wie die Scribble-Strips (siehe
        `_on_scribble_relevant_event`) sowie direkt nach einem Select-Druck.
        Solo/Mute-Zustand kommt aus derselben `_channel_button_snapshot()`-
        Quelle, die auch die `is-on`-Klasse der Web-UI setzt (Nutzerentscheid:
        physisches Geraet und Web-UI duerfen nicht auseinanderlaufen).
        Unbekannter Zustand (`state: None`, noch nie abgefragt/gedrueckt)
        zeigt wie in der Web-UI unbeleuchtet. Rec (Nutzerentscheid
        2026-07-20): keine Zustandsabfrage, leuchtet ohne Rücksicht auf
        Solo/Mute-Feature-Zustand, aber nur auf Kanaelen mit tatsaechlich
        verbundener Kamera (`ch["connected"]`, Nutzerentscheid 2026-07-20 --
        ein Kanal ohne oder mit nur getrennter Kamera hat keine Encoder-
        Funktion, die Rec waehlen koennte). Select (Nutzerentscheid
        2026-07-20): leuchtet nur auf `_last_select_channel`, nur wenn
        `AppState.companion_connected` gesetzt ist, UND nur wenn dieser Kanal
        ebenfalls eine verbundene Kamera hat -- alle anderen Kanaele aus,
        auch wenn sie zuvor mal der zuletzt gedrueckte waren oder Companion
        gerade nicht verbunden ist."""
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
