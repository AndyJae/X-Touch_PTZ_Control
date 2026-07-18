// Surface-Ansicht: Button 1 waehlt die Encoder-Funktion des Kanals (Spec §9,
// physisches Aequivalent: Rec-Taste). Loest nur die Auswahl serverseitig aus
// (POST /api/channels/{i}/encoder/select, Aequivalent zu cycle_encoder_function())
// -- die eigentliche Anzeige (Funktion/Wert) kommt ueber den WebSocket-Snapshot
// zurueck, siehe applySurfaceSnapshot().
function initEncoderFunctionSelect() {
    document.querySelectorAll("[data-encoder-fn-select]").forEach((button) => {
        button.addEventListener("click", async () => {
            const channelIndex = button.dataset.channelIndex;
            button.disabled = true;
            try {
                await fetch(`/api/channels/${channelIndex}/encoder/select`, { method: "POST" });
            } finally {
                button.disabled = false;
            }
        });
    });
}

// Surface-Ansicht: Drehregler (Spec §9) -- Drehen (Ziehen mit der Maus oder
// Scrollen) sendet bei gain/pedestal SOFORT einen Kamerabefehl (live, ueber
// den Rate-Limiter in apply_encoder_turn()); ein Klick ohne Ziehen loest nur
// noch rein visuelles "gespeichert"-Feedback aus (commit_encoder_value()),
// ohne weiteren Kamerabefehl. Nutzerentscheid, analog zum physischen
// Drehrad-Druck am X-Touch Extender.
function initEncoderKnob(ws) {
    const PX_PER_TICK = 6; // reine UI-Feinabstimmung, keine Spec-Vorgabe

    document.querySelectorAll("[data-encoder]").forEach((knob) => {
        const channelIndex = Number(knob.dataset.channelIndex);

        const sendTurn = (delta) => {
            if (ws.readyState !== WebSocket.OPEN || delta === 0) return;
            ws.send(JSON.stringify({ type: "encoder_turn", channel: channelIndex, delta }));
        };
        const sendCommit = () => {
            if (ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ type: "encoder_commit", channel: channelIndex }));
        };

        knob.addEventListener("wheel", (evt) => {
            evt.preventDefault();
            sendTurn(evt.deltaY < 0 ? 1 : -1);
        }, { passive: false });

        let dragging = false;
        let dragged = false;
        let lastY = 0;
        let carryPx = 0; // Rest-Pixel zwischen zwei vollen Ticks

        knob.addEventListener("pointerdown", (evt) => {
            dragging = true;
            dragged = false;
            carryPx = 0;
            lastY = evt.clientY;
            knob.setPointerCapture(evt.pointerId);
            knob.classList.add("is-dragging");
        });

        knob.addEventListener("pointermove", (evt) => {
            if (!dragging) return;
            carryPx += lastY - evt.clientY; // nach oben ziehen = erhoehen
            lastY = evt.clientY;
            if (Math.abs(carryPx) < PX_PER_TICK) return;
            const ticks = Math.trunc(carryPx / PX_PER_TICK);
            carryPx -= ticks * PX_PER_TICK;
            dragged = true;
            sendTurn(ticks);
        });

        const endDrag = () => {
            if (!dragging) return;
            dragging = false;
            knob.classList.remove("is-dragging");
            if (!dragged) sendCommit(); // Klick ohne Ziehen = uebernehmen
        };
        knob.addEventListener("pointerup", endDrag);
        knob.addEventListener("pointercancel", endDrag);
    });
}

// Setup-Seite: Connect-Camera-Button pro Zeile in "Kamera- & Tastenbelegung".
// Verbunden -> erneuter Klick: entkoppelt (POST .../camera/disconnect).
// Nicht verbunden -> Klick: registriert/aktualisiert die Kamera für diesen
// Kanal (Name/IP/Port aus den Sibling-Inputs) über POST
// /api/channels/{index}/camera -- ersetzt externes Eintragen in config.yaml
// (Nutzerentscheid, Abkehr von Spec §10.3 für Kamera-Stammdaten). Bei Erfolg
// wird die Seite neu geladen, damit Modell-Anzeige und Button-2/3-Katalog
// (die vom erkannten Kameramodell abhängen) konsistent aus dem
// Server-Render kommen, statt mehrere DOM-Stellen einzeln nachzuziehen.
function initCameraConnectButtons() {
    document.querySelectorAll("[data-camera-row]").forEach((row) => {
        const button = row.querySelector("[data-connect-btn]");
        const channelIndex = row.dataset.channelIndex;
        const nameInput = row.querySelector("[data-name-input]");
        const hostInput = row.querySelector("[data-host-input]");
        const portInput = row.querySelector("[data-port-input]");
        if (!button || !channelIndex || !hostInput) return;

        button.addEventListener("click", async () => {
            const isConnected = button.classList.contains("is-connected");
            button.disabled = true;
            button.textContent = isConnected ? "Disconnecting…" : "Connecting…";
            try {
                const res = isConnected
                    ? await fetch(`/api/channels/${channelIndex}/camera/disconnect`, { method: "POST" })
                    : await fetch(`/api/channels/${channelIndex}/camera`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                              name: nameInput ? nameInput.value.trim() : "",
                              host: hostInput.value.trim(),
                              port: portInput ? portInput.value.trim() : "",
                          }),
                      });
                if (res.ok) {
                    location.reload();
                    return;
                }
                const data = await res.json();
                button.textContent = data.error || "Error";
            } catch (err) {
                button.textContent = "Connection error";
            } finally {
                button.disabled = false;
            }
        });
    });
}

// Setup-Seite: Kameraname pro Kanal -- ganz einfaches Eingabefeld ohne
// weitere Funktion, absichtlich unabhängig vom Connect/Disconnect-Toggle
// des "Connect Camera"-Buttons (Umbenennen soll keine Verbindung trennen).
// Speichert bei Verlassen des Felds (change-Event, nicht bei jedem
// Tastendruck) über POST /api/channels/{index}/camera/name.
function initCameraNameInputs() {
    document.querySelectorAll("[data-name-input]").forEach((input) => {
        const row = input.closest("[data-camera-row]");
        const channelIndex = row ? row.dataset.channelIndex : null;
        if (!channelIndex) return;

        input.addEventListener("change", () => {
            fetch(`/api/channels/${channelIndex}/camera/name`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: input.value.trim() }),
            });
        });
    });
}

// Setup-Seite: globale Bitfocus-Companion-Instanz (Host/Port), Panel an der
// Stelle des ehemaligen "Camera Status"-Blocks. Bewusste Erweiterung über
// v1 hinaus (Spec §9) -- eine Instanz für alle Kanäle (Nutzerentscheid).
function initCompanionConfigForm() {
    const button = document.querySelector("[data-companion-save]");
    const disconnectButton = document.querySelector("[data-companion-disconnect]");
    const hostInput = document.querySelector("[data-companion-host]");
    const portInput = document.querySelector("[data-companion-port]");
    if (!button || !hostInput) return;

    const originalLabel = button.textContent;

    button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const res = await fetch("/api/companion/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    host: hostInput.value.trim(),
                    port: portInput ? portInput.value.trim() : "",
                }),
            });
            if (res.ok) {
                location.reload();
                return;
            }
            button.textContent = "Error";
        } catch (err) {
            button.textContent = "Connection error";
        } finally {
            setTimeout(() => { button.textContent = originalLabel; }, 1500);
            button.disabled = false;
        }
    });

    if (disconnectButton) {
        disconnectButton.addEventListener("click", async () => {
            disconnectButton.disabled = true;
            try {
                const res = await fetch("/api/companion/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ host: "", port: portInput ? portInput.value.trim() : "" }),
                });
                if (res.ok) {
                    location.reload();
                    return;
                }
                disconnectButton.textContent = "Error";
            } catch (err) {
                disconnectButton.textContent = "Connection error";
            } finally {
                disconnectButton.disabled = false;
            }
        });
    }
}

// Setup-Seite: SELECT-Ziel (Companion Page/Row/Column) pro Kanal. Alle drei
// Felder einer Zeile werden zusammen gespeichert -- fehlt eines, wertet der
// Server das als "keine Zuordnung" (siehe assign_channel_companion_target).
function initCompanionTargetInputs() {
    document.querySelectorAll("[data-companion-page], [data-companion-row], [data-companion-column]").forEach((input) => {
        input.addEventListener("change", () => {
            const row = input.closest("[data-camera-row]");
            const channelIndex = row ? row.dataset.channelIndex : null;
            if (!channelIndex) return;
            const page = row.querySelector("[data-companion-page]");
            const rowField = row.querySelector("[data-companion-row]");
            const column = row.querySelector("[data-companion-column]");
            fetch(`/api/channels/${channelIndex}/companion`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    page: page ? page.value.trim() : "",
                    row: rowField ? rowField.value.trim() : "",
                    column: column ? column.value.trim() : "",
                }),
            });
        });
    });
}

// Setup-Seite: Button-2/3-Zuordnung pro Kanal (Spec §9a) -- persistiert
// echt über POST /api/channels/{index}/buttons/{slot}.
function initButtonAssignmentSelects() {
    document.querySelectorAll("[data-button-assign-select]").forEach((select) => {
        select.addEventListener("change", async () => {
            const channelIndex = select.dataset.channelIndex;
            const buttonSlot = select.dataset.buttonSlot;
            select.disabled = true;
            try {
                await fetch(`/api/channels/${channelIndex}/buttons/${buttonSlot}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ feature_key: select.value }),
                });
            } finally {
                select.disabled = false;
            }
        });
    });
}

// Übersicht-Seite: Button 2/3 lösen die auf der Setup-Seite zugewiesene
// Kamera-Feature-Aktion aus (Spec §9a). Der neue Zustand (an/aus) kommt über
// den WebSocket-Snapshot zurück, siehe applySurfaceSnapshot().
function initFeatureButtons() {
    document.querySelectorAll("[data-feature-btn]").forEach((button) => {
        button.addEventListener("click", async () => {
            const channelIndex = button.dataset.channelIndex;
            const buttonSlot = button.dataset.buttonSlot;
            button.disabled = true;
            try {
                await fetch(`/api/channels/${channelIndex}/buttons/${buttonSlot}/trigger`, {
                    method: "POST",
                });
            } finally {
                button.disabled = false;
            }
        });
    });
}

// Übersicht-Seite: Zahnrad neben Button 2/3 oeffnet ein Popover mit dem
// echten, dynamischen Funktionskatalog des am Kanal verbundenen
// Kameramodells (Nutzerauftrag 2026-07-18) -- keine zweite Seite (Setup)
// mehr noetig, um eine Funktion zuzuweisen. Katalog kommt bei jedem Oeffnen
// frisch von GET /api/channels/{i}/available-buttons (nicht beim Seitenladen
// gecacht, falls sich das Kameramodell durch Reconnect aendert). Auswahl
// ruft denselben POST /api/channels/{i}/buttons/{slot} wie die Setup-Seite
// auf -- Persistenz in config.yaml UND (dort serverseitig, siehe
// assign_channel_button()) eine sofortige Zustandsabfrage, deren Ergebnis
// ueber den naechsten WebSocket-Snapshot zurueckkommt und applySurfaceSnapshot()
// den Button korrekt beleuchtet/unbeleuchtet zeigen laesst -- kein manuelles
// Text-/Zustands-Setzen hier noetig.
function initFeatureGearMenu() {
    document.querySelectorAll("[data-gear-btn]").forEach((gear) => {
        const row = gear.closest(".feature-btn-row");
        const popover = row.querySelector("[data-feature-popover]");
        const channelIndex = gear.dataset.channelIndex;
        const buttonSlot = gear.dataset.buttonSlot;

        gear.addEventListener("click", async (evt) => {
            evt.stopPropagation();
            const wasOpen = !popover.hidden;
            document.querySelectorAll("[data-feature-popover]").forEach((other) => {
                other.hidden = true;
            });
            if (wasOpen) return;

            popover.innerHTML = "<button type=\"button\" class=\"feature-popover-option\" disabled>Lädt…</button>";
            popover.hidden = false;
            try {
                const res = await fetch(`/api/channels/${channelIndex}/available-buttons`);
                const data = await res.json();
                popover.innerHTML = "";
                const noneOption = document.createElement("button");
                noneOption.type = "button";
                noneOption.className = "feature-popover-option";
                noneOption.textContent = "—";
                noneOption.dataset.featureKey = "";
                popover.appendChild(noneOption);
                Object.entries(data.features || {}).forEach(([key, label]) => {
                    const option = document.createElement("button");
                    option.type = "button";
                    option.className = "feature-popover-option";
                    option.textContent = label;
                    option.dataset.featureKey = key;
                    popover.appendChild(option);
                });
                popover.querySelectorAll(".feature-popover-option[data-feature-key]").forEach((option) => {
                    option.addEventListener("click", async (optEvt) => {
                        optEvt.stopPropagation();
                        popover.hidden = true;
                        await fetch(`/api/channels/${channelIndex}/buttons/${buttonSlot}`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ feature_key: option.dataset.featureKey || null }),
                        });
                    });
                });
            } catch (err) {
                popover.innerHTML = "<button type=\"button\" class=\"feature-popover-option\" disabled>Fehler</button>";
            }
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll("[data-feature-popover]").forEach((popover) => {
            popover.hidden = true;
        });
    });
}

// Übersicht-Seite: SELECT löst das auf der Setup-Seite zugewiesene
// Companion-Ziel fern aus (Spec §9, bewusste Erweiterung über v1 hinaus).
// Anders als die Feature-Buttons hat SELECT keinen Dauerzustand -- bei
// Fehlschlag zeigt der Button kurz die Fehlermeldung statt eines
// persistenten Fehler-Icons.
function initSelectButtons() {
    document.querySelectorAll("[data-select-btn]").forEach((button) => {
        const originalLabel = button.textContent;
        button.addEventListener("click", async () => {
            const channelIndex = button.dataset.channelIndex;
            button.disabled = true;
            try {
                const res = await fetch(`/api/channels/${channelIndex}/companion/trigger`, { method: "POST" });
                if (!res.ok) {
                    const data = await res.json();
                    button.textContent = data.error || "Error";
                    setTimeout(() => { button.textContent = originalLabel; }, 2000);
                }
            } catch (err) {
                button.textContent = "Connection error";
                setTimeout(() => { button.textContent = originalLabel; }, 2000);
            } finally {
                button.disabled = false;
            }
        });
    });
}

// Übersicht-Seite (surface.html): Live-Zustand per WebSocket + Iris-Fader
// per Zeigen/Ziehen steuerbar. Datenfluss Fader -> Kamera folgt Spec §3.
function connectSurfaceSocket() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.addEventListener("message", (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (err) {
            return;
        }
        if (data.type === "snapshot") applySurfaceSnapshot(data.channels);
    });

    ws.addEventListener("close", () => {
        setTimeout(connectSurfaceSocket, 2000);
    });

    return ws;
}

function applySurfaceSnapshot(channels) {
    channels.forEach((ch) => {
        const article = document.querySelector(`.surface-channel[data-channel="${ch.index}"]`);
        if (!article) return;

        // Nur eine tatsaechlich verbundene Kamera macht den Kanalzug aktiv --
        // eine registrierte, aber getrennte Kamera (Setup-Seite "Connect
        // Camera" erneut geklickt) soll wie ein unbelegter Kanal wirken,
        // nicht wie ein aktiver mit veralteten Werten.
        article.classList.toggle("is-unassigned", !ch.connected);
        article.dataset.hasCamera = ch.connected ? "true" : "false";

        const pct = ch.iris != null ? Math.round(ch.iris * 100) : 0;
        const fill = article.querySelector("[data-fader-fill]");
        const handle = article.querySelector("[data-fader-handle]");
        if (fill) fill.style.height = pct + "%";
        if (handle) handle.style.bottom = pct + "%";

        // EINE Kanal-Anzeige (Nutzerentscheid): Text kommt direkt aus dem
        // Server-Snapshot (channel_line1_text()/channel_display_text() in
        // core/application.py), damit Web-UI und physisches Scribble-Strip
        // nie auseinanderlaufen.
        const displayLine1 = article.querySelector("[data-display-line1]");
        if (displayLine1) displayLine1.textContent = ch.connected ? ch.display_line1 : (ch.name || `CAM ${ch.index}`);
        const displayText = article.querySelector("[data-display-text]");
        if (displayText) displayText.textContent = ch.connected ? ch.display_text : "—";
        const scribbleStrip = displayText ? displayText.closest(".scribble-strip") : null;

        const enc = ch.encoder;
        const fnButton = article.querySelector("[data-encoder-fn-select]");
        const encKnob = article.querySelector("[data-encoder]");
        if (fnButton) fnButton.textContent = enc.function.replace(/_/g, " ").toUpperCase();
        // Rot bis zum naechsten Dreh-Tick (Nutzerentscheid, siehe
        // commit_encoder_value()/apply_encoder_turn()).
        if (scribbleStrip) scribbleStrip.classList.toggle("is-saved", !!enc.saved);
        if (encKnob && enc.value != null && enc.min != null && enc.max != null) {
            const pos = Math.round(((enc.value - enc.min) / (enc.max - enc.min)) * 100);
            encKnob.style.setProperty("--enc-pos", pos + "%");
        }

        const dot = article.querySelector("[data-tally-dot]");
        if (dot) {
            dot.classList.toggle("is-tally-green", !!ch.connected);
            dot.classList.toggle("is-tally-red", !ch.connected && !!ch.camera_id);
            dot.title = ch.error || "";
        }

        ["button2", "button3"].forEach((slot) => {
            const button = article.querySelector(`[data-feature-btn][data-button-slot="${slot}"]`);
            if (!button) return;
            const assigned = ch.buttons ? ch.buttons[slot] : null;
            button.disabled = !assigned;
            button.classList.toggle("is-on", !!(assigned && assigned.state));
            if (assigned) {
                button.textContent = assigned.label;
                button.title = assigned.label;
            }
        });
    });
}

function initFaderDrag(ws) {
    // Auf allen Kanalzuegen anhaengen (nicht nur den beim Laden verbundenen)
    // -- ob ein Zug reagiert, wird bei jedem Event live anhand von
    // data-has-camera geprueft, das applySurfaceSnapshot() aktuell haelt.
    // Sonst wuerde ein Fader nach dem Trennen der Kamera weiter reagieren,
    // weil die Listener schon beim Laden fest gebunden wurden.
    document.querySelectorAll(".surface-channel").forEach((article) => {
        const channelIndex = Number(article.dataset.channel);
        const track = article.querySelector("[data-fader-track]");
        const fill = article.querySelector("[data-fader-fill]");
        const handle = article.querySelector("[data-fader-handle]");
        if (!track || !fill || !handle) return;

        const isActive = () => article.dataset.hasCamera === "true";

        const valueFromEvent = (evt) => {
            const rect = track.getBoundingClientRect();
            const pct = (rect.bottom - evt.clientY) / rect.height;
            return Math.min(1, Math.max(0, pct));
        };

        const paint = (value) => {
            fill.style.height = value * 100 + "%";
            handle.style.bottom = value * 100 + "%";
        };

        const send = (value, final) => {
            if (ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ type: "set_iris", channel: channelIndex, value, final }));
        };

        let dragging = false;

        track.addEventListener("pointerdown", (evt) => {
            if (!isActive()) return;
            dragging = true;
            track.setPointerCapture(evt.pointerId);
            const value = valueFromEvent(evt);
            paint(value);
            send(value, false);
        });

        track.addEventListener("pointermove", (evt) => {
            if (!dragging) return;
            const value = valueFromEvent(evt);
            paint(value);
            send(value, false);
        });

        const release = (evt) => {
            if (!dragging) return;
            dragging = false;
            const value = valueFromEvent(evt);
            paint(value);
            send(value, true);
        };
        track.addEventListener("pointerup", release);
        track.addEventListener("pointercancel", release);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initEncoderFunctionSelect();
    initCameraConnectButtons();
    initCameraNameInputs();
    initButtonAssignmentSelects();
    initCompanionConfigForm();
    initCompanionTargetInputs();

    if (document.querySelector(".surface-channel")) {
        const ws = connectSurfaceSocket();
        initFaderDrag(ws);
        initEncoderKnob(ws);
        initFeatureButtons();
        initFeatureGearMenu();
        initSelectButtons();
    }
});
