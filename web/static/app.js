// Startup dialog ("Load previous config"/"Start new config"), checked on
// every page (GET /api/startup/status), not just the control page, in case
// another page or an old tab loads first. A grayed-out overlay keeps the
// web UI visible but non-interactive behind it (see app.css
// .startup-overlay/.app-shell.is-dimmed). "Start new config" disconnects
// every camera and resets config.yaml, so it's confirmed first.
function initStartupChoiceDialog() {
    const overlay = document.querySelector("[data-startup-overlay]");
    const shell = document.querySelector("[data-app-shell]");
    if (!overlay || !shell) return;

    fetch("/api/startup/status")
        .then((res) => res.json())
        .then((data) => {
            if (data.pending) {
                overlay.hidden = false;
                shell.classList.add("is-dimmed");
            }
        })
        .catch(() => {});

    const loadButton = overlay.querySelector("[data-startup-load-previous]");
    const newButton = overlay.querySelector("[data-startup-new-config]");

    async function answer(url) {
        loadButton.disabled = true;
        newButton.disabled = true;
        try {
            await fetch(url, { method: "POST" });
        } finally {
            location.reload();
        }
    }

    loadButton.addEventListener("click", () => answer("/api/startup/load-previous"));
    newButton.addEventListener("click", () => {
        if (confirm("Start new config? This disconnects all cameras and resets config.yaml.")) {
            answer("/api/startup/new-config");
        }
    });
}

// Surface view: button 1 selects the channel's encoder function (physical
// equivalent: the Rec key). Only triggers the selection server-side (POST
// /api/channels/{i}/encoder/select); the display update comes back via the
// WebSocket snapshot, see applySurfaceSnapshot().
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

// Surface view: encoder knob -- turning (mouse drag or scroll) sends a
// camera command live for gain/pedestal, through the rate limiter in
// apply_encoder_turn(); a click without dragging only triggers the visual
// "saved" feedback (commit_encoder_value()), no further camera command.
function initEncoderKnob(ws) {
    const PX_PER_TICK = 6; // UI feel tuning only

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
            if (!dragged) sendCommit(); // click without dragging = commit
        };
        knob.addEventListener("pointerup", endDrag);
        knob.addEventListener("pointercancel", endDrag);
    });
}

// Setup page: Connect Camera button per row. Connected -> click disconnects
// (POST .../camera/disconnect). Not connected -> click registers/updates
// the camera for this channel (name/IP/port from the sibling inputs) via
// POST /api/channels/{index}/camera. Reloads the page on success so the
// model display and button 2/3 catalog (which depend on the detected
// camera model) come consistently from the server render.
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
            const originalText = button.textContent;
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
                alert(data.error || "Error");
                button.textContent = originalText;
            } catch (err) {
                alert("Connection error");
                button.textContent = originalText;
            } finally {
                button.disabled = false;
            }
        });
    });
}

// Setup page: camera name per channel, independent of the Connect Camera
// button's connect/disconnect toggle (renaming shouldn't drop a
// connection). Saves on blur (change event) via
// POST /api/channels/{index}/camera/name.
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

// Setup page: the single global Bitfocus Companion instance (host/port),
// shared across all channels.
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

// Setup page: SELECT target (Companion page/row/column) per channel. All
// three fields of a row are saved together -- if one is missing, the server
// treats it as "no assignment" (see assign_channel_companion_target).
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

// Setup page: button 2/3 assignment per channel, persisted via
// POST /api/channels/{index}/buttons/{slot}.
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

// Overview page: button 2/3 fire the camera feature action assigned on the
// Setup page. The new state (on/off) comes back via the WebSocket snapshot,
// see applySurfaceSnapshot().
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

// Overview page: the gear icon next to button 2/3 opens a popover with the
// connected camera model's dynamic function catalog, fetched fresh on every
// open from GET /api/channels/{i}/available-buttons. Selecting an option
// calls the same POST /api/channels/{i}/buttons/{slot} as the Setup page;
// the resulting state comes back via the next WebSocket snapshot.
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

// Overview page: SELECT remotely fires the Companion target assigned on the
// Setup page. Unlike the feature buttons, SELECT has no persistent state --
// on failure the button briefly shows the error message instead of a
// persistent error icon.
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

// Overview page (surface.html): live state via WebSocket, iris controllable
// by dragging the fader.
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

        // Only an actually connected camera makes the channel strip
        // active -- a registered but disconnected camera should act like
        // an unassigned channel, not an active one with stale values.
        article.classList.toggle("is-unassigned", !ch.connected);
        article.dataset.hasCamera = ch.connected ? "true" : "false";

        const pct = ch.iris != null ? Math.round(ch.iris * 100) : 0;
        const fill = article.querySelector("[data-fader-fill]");
        const handle = article.querySelector("[data-fader-handle]");
        if (fill) fill.style.height = pct + "%";
        if (handle) handle.style.bottom = pct + "%";

        // Text comes directly from the server snapshot
        // (channel_line1_text()/channel_display_text()), so the web UI and
        // physical scribble strip never diverge.
        const displayLine1 = article.querySelector("[data-display-line1]");
        if (displayLine1) displayLine1.textContent = ch.connected ? ch.display_line1 : (ch.name || `CAM ${ch.index}`);
        const displayText = article.querySelector("[data-display-text]");
        if (displayText) displayText.textContent = ch.connected ? ch.display_text : "—";
        const scribbleStrip = displayText ? displayText.closest(".scribble-strip") : null;

        const enc = ch.encoder;
        const fnButton = article.querySelector("[data-encoder-fn-select]");
        const encKnob = article.querySelector("[data-encoder]");
        if (fnButton) fnButton.textContent = enc.function === "camera_status" ? "CAMERA INFO" : enc.function.replace(/_/g, " ").toUpperCase();
        // Red until the next turn tick, see commit_encoder_value()/apply_encoder_turn().
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

        // Mirrors the physical Select LED: filled background = last
        // channel a SELECT press targeted (physical or web), and this
        // channel has a Companion target assigned -- see
        // trigger_companion_select()/AppState.last_select_channel.
        const selectButton = article.querySelector("[data-select-btn]");
        if (selectButton) {
            selectButton.classList.toggle("is-on", !!(ch.companion && ch.select_active));
        }
    });
}

function initFaderDrag(ws) {
    // Attached to every channel strip, not just the ones connected on load
    // -- whether a strip reacts is checked live on every event via
    // data-has-camera, which applySurfaceSnapshot() keeps current.
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
        let lastValue = 0;

        track.addEventListener("pointerdown", (evt) => {
            if (!isActive()) return;
            dragging = true;
            track.setPointerCapture(evt.pointerId);
            const value = valueFromEvent(evt);
            lastValue = value;
            paint(value);
            send(value, false);
        });

        track.addEventListener("pointermove", (evt) => {
            if (!dragging) return;
            const value = valueFromEvent(evt);
            lastValue = value;
            paint(value);
            send(value, false);
        });

        track.addEventListener("pointerup", (evt) => {
            if (!dragging) return;
            dragging = false;
            const value = valueFromEvent(evt);
            lastValue = value;
            paint(value);
            send(value, true);
        });

        // pointercancel (fires on aborted interactions, e.g. focus
        // change/OS interruption) carries no reliable position per the
        // Pointer Events spec, so it falls back to the last known value
        // from pointerdown/-move instead of trusting the cancel position.
        track.addEventListener("pointercancel", () => {
            if (!dragging) return;
            dragging = false;
            paint(lastValue);
            send(lastValue, true);
        });
    });
}

// Logs view: level selection reloads the page with the chosen level as a
// query parameter, the server filters server-side.
function initLogLevelFilter() {
    const select = document.querySelector("[data-log-level-filter]");
    if (!select) {
        return;
    }
    select.addEventListener("change", () => {
        const url = new URL(window.location.href);
        url.searchParams.set("level", select.value);
        window.location.href = url.toString();
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initStartupChoiceDialog();
    initEncoderFunctionSelect();
    initCameraConnectButtons();
    initCameraNameInputs();
    initButtonAssignmentSelects();
    initCompanionConfigForm();
    initCompanionTargetInputs();
    initLogLevelFilter();

    if (document.querySelector(".surface-channel")) {
        const ws = connectSurfaceSocket();
        initFaderDrag(ws);
        initEncoderKnob(ws);
        initFeatureButtons();
        initFeatureGearMenu();
        initSelectButtons();
    }
});
