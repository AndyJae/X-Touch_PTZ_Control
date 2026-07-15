// Surface-Ansicht: Button 1 wählt die Funktion des Encoders (Drehrad) pro Kanalzug.
// Demo-Werte, da die Seite aktuell ein statisches UI-Mockup ohne Live-MIDI-/Kamera-Daten ist.
const ENCODER_FUNCTIONS = [
    { label: "GAIN", value: "+3 dB" },
    { label: "SHUTTER", value: "1/250" },
    { label: "MASTER BLACK", value: "0" },
];

function initEncoderFunctionSelect() {
    document.querySelectorAll(".surface-channel").forEach((channel) => {
        const button = channel.querySelector("[data-encoder-fn-select]");
        const fnLabel = channel.querySelector("[data-encoder-fn]");
        const valLabel = channel.querySelector("[data-encoder-val]");
        if (!button || !fnLabel || !valLabel) return;

        let index = 0;

        const render = () => {
            const fn = ENCODER_FUNCTIONS[index];
            fnLabel.textContent = fn.label;
            valLabel.textContent = fn.value;
            button.textContent = fn.label;
        };

        button.addEventListener("click", () => {
            index = (index + 1) % ENCODER_FUNCTIONS.length;
            render();
        });

        render();
    });
}

// Setup-Seite: Connect-Camera-Button pro Zeile in "Kamera- & Tastenbelegung".
// Rein clientseitiger Platzhalter-Toggle (rot = nicht verbunden, grün = verbunden),
// da hier noch keine echte Kamera-Verbindung (Treiber/HTTP) angebunden ist.
const DEMO_CAMERA_TYPE = "AW-UE160";

function initCameraConnectButtons() {
    document.querySelectorAll("[data-camera-row]").forEach((row) => {
        const button = row.querySelector("[data-connect-btn]");
        const dot = row.querySelector("[data-status-dot]");
        const typeLabel = row.nextElementSibling ? row.nextElementSibling.querySelector("[data-camera-type]") : null;
        if (!button || !dot) return;

        let connected = false;

        const render = () => {
            button.textContent = connected ? "Connected" : "Connect Camera";
            button.classList.toggle("is-connected", connected);
            dot.classList.toggle("is-connected", connected);
            if (typeLabel) typeLabel.textContent = connected ? DEMO_CAMERA_TYPE : "—";
        };

        button.addEventListener("click", () => {
            connected = !connected;
            render();
        });

        render();
    });
}

// Setup-Seite: "Reconnect"-Button im schlanken "Camera Status"-Block (§10.1)
// -- ruft echt POST /api/cameras/{id}/connect auf, im Unterschied zum reinen
// Demo-Toggle in initCameraConnectButtons() (Kamera-/Tastenbelegungs-Tabelle,
// bleibt unangetastetes Mockup, siehe Implementierungsplan).
function initCameraReconnectButtons() {
    document.querySelectorAll("[data-camera-status-row]").forEach((row) => {
        const button = row.querySelector("[data-reconnect-btn]");
        const dot = row.querySelector(".status-dot");
        const text = row.querySelector("[data-camera-status-text]");
        const cameraId = row.dataset.cameraId;
        if (!button || !cameraId) return;

        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                const res = await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/connect`, {
                    method: "POST",
                });
                const data = await res.json();
                if (dot) dot.classList.toggle("is-connected", !!data.connected);
                if (text) {
                    text.textContent = data.connected
                        ? `online${data.model ? " — " + data.model : ""}`
                        : (data.error || "offline");
                }
            } catch (err) {
                if (text) text.textContent = "Verbindungsfehler (siehe Log)";
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

        const pct = ch.iris != null ? Math.round(ch.iris * 100) : 0;
        const fill = article.querySelector("[data-fader-fill]");
        const handle = article.querySelector("[data-fader-handle]");
        if (fill) fill.style.height = pct + "%";
        if (handle) handle.style.bottom = pct + "%";

        const irisReadout = article.querySelector("[data-iris-readout]");
        if (irisReadout) irisReadout.textContent = ch.camera_id ? pct + "%" : "—";

        const gainVal = article.querySelector("[data-encoder-val]");
        if (gainVal) gainVal.textContent = ch.gain_db != null ? ch.gain_db + " dB" : "—";

        const dot = article.querySelector("[data-tally-dot]");
        if (dot) {
            dot.classList.toggle("is-tally-green", !!ch.connected);
            dot.classList.toggle("is-tally-red", !ch.connected && !!ch.camera_id);
            dot.title = ch.error || "";
        }
    });
}

function initFaderDrag(ws) {
    document.querySelectorAll(".surface-channel[data-has-camera='true']").forEach((article) => {
        const channelIndex = Number(article.dataset.channel);
        const track = article.querySelector("[data-fader-track]");
        const fill = article.querySelector("[data-fader-fill]");
        const handle = article.querySelector("[data-fader-handle]");
        if (!track || !fill || !handle) return;

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
    initCameraReconnectButtons();

    if (document.querySelector(".surface-channel")) {
        const ws = connectSurfaceSocket();
        initFaderDrag(ws);
    }
});
