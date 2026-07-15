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

document.addEventListener("DOMContentLoaded", () => {
    initEncoderFunctionSelect();
    initCameraConnectButtons();
});
