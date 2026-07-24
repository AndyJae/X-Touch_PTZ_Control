# X-Touch PTZ Control

A MIDI shading/iris controller for Panasonic PTZ cameras, built around the
Behringer X-Touch Extender and a local web UI. Pull a fader — physical or
on-screen — and the camera's iris follows live, plus gain, pedestal and ND
filter control, all from one 8-channel surface.

## What it does

- **Live iris control** per channel via a motorized fader (physical X-Touch
  Extender) or the web UI — both stay in sync, including iris changes made
  from the camera's own web interface.
- **One encoder per channel** cycles through Gain, Pedestal, ND filter and
  Camera Info (the REC button switches function; turning the encoder
  adjusts the active one live).
- **Two assignable Solo/Mute buttons** per channel trigger camera-specific
  toggle features (e.g. Auto Focus, Knee, DRS — depends on the camera
  model).
- **A SELECT button** per channel can optionally trigger a Bitfocus
  Companion button.
- Everything is controlled from a local web UI — it works standalone, the
  X-Touch Extender is optional.

## Requirements

- **Windows** (the app uses Windows-specific APIs for the system tray icon
  and single-instance check)
- Python 3.11+
- A supported Panasonic PTZ camera (see below), reachable over the network
- Optional: a Behringer X-Touch Extender, connected via USB, **set to MC
  (Mackie Control) mode** — hold Select 1 while powering the unit on to
  switch modes (see the X-Touch Extender manual). Other modes are not
  recognized by this software.
- Optional: a Bitfocus Companion instance for the SELECT button
- A modern browser — we recommend the latest Google Chrome, that's what
  this project is developed and tested with

## Supported cameras

Only the Panasonic AW-series CGI protocol is currently supported. 17 models
are recognized automatically via their `QID` response:

AK-UB300, AW-HE40, AW-HE42, AW-HE50, AW-HE60, AW-HE120, AW-HE130, AW-HE145
(alias AW-UE145), AW-HR140, AW-UE30, AW-UE40, AW-UE50, AW-UE70, AW-UE80,
AW-UE100, AW-UE150A (alias AW-UE150), AW-UE160.

Feature support varies per model — gain/pedestal ranges and the available
toggle features (DRS, Knee, White Clip, ...) are looked up from the
detected model, checked against Panasonic's interface specification PDFs
where one was available. Iris control (fader → f-number display) is only
verified against a real AW-UE160; other models are expected to behave the
same but haven't been confirmed on real hardware.

An unrecognized camera model still connects, just without any of the
model-specific features.

## Quick start

1. If you're using the physical X-Touch Extender, set it to **MC (Mackie
   Control) mode** (hold Select 1 while powering it on) and connect it via
   USB **before** starting the app — it's detected once at startup, not
   while the app is already running. Other controller modes are not
   supported.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` (optional — a missing
   `config.yaml` is treated the same as the example, and the app creates
   one as soon as you save anything).
4. Start the app: `python main.py` — the web UI opens automatically at
   `http://127.0.0.1:8600/`. It also adds an icon to the system tray and
   keeps running there. Closing the browser tab/window does **not** stop
   the app — click the tray icon (or right-click it and choose **Open**) to
   reopen the web UI, and right-click it and choose **Quit** to actually
   shut the app down.
5. Open **Setup** and register a camera per channel (name, IP, port), then
   click **Connect Camera**.
6. The X-Touch Extender is picked up automatically if it's connected;
   without one, the on-screen controls in the web UI work the same way.

See the in-app **Help** page for a walkthrough of the Control, Setup and
Logs pages.

## Configuration

`config.yaml` holds MIDI port overrides (only needed if auto-detection
doesn't find your controller), the optional Companion host, and global
settings (rate limit, log level, web port). It's read and written by the
app itself — day-to-day configuration (cameras, button assignments,
Companion targets) happens through the Setup page, not by hand editing.
See `config.example.yaml` for the full schema with comments.

`config.yaml` is not committed to this repository (it holds your camera
IPs and other local details) — start from `config.example.yaml` instead.

## Building a standalone exe

The steps above run the app from source with `python main.py`. To build a
single portable `.exe` that doesn't need a Python install:

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller main.spec
```

This produces `dist/X-Touch PTZ Control.exe` — a single file with the
Python runtime, all dependencies, the web UI assets, and the tray icon
bundled in. Copy it wherever you like; `config.yaml` is created next to it
on first save, same as running from source. It's built windowed (no
console) — if it fails to start, check `ptz_control.log` next to the exe.

## How it works

For anyone curious what actually happens between moving a fader and the
camera's iris changing — or debugging a controller/camera at the protocol
level.

### Controller → software (MIDI)

The X-Touch Extender runs in Mackie Control mode and talks plain MIDI over
USB. The app doesn't use a MIDI callback thread — it polls the input port
every 10&nbsp;ms (`midi/fader.py`) and reacts to a fixed set of messages,
one instance of each per channel (channels are numbered 1–8, matching the
8 physical strips):

| Message | Meaning |
| --- | --- |
| Pitchbend on MIDI channel *N* | Fader *N* position (14-bit, 0–16383) |
| Note On 104–111, velocity > 0 / 0 | Fader touch pressed / released, channel *N* = note − 103 |
| Note On 0–7, velocity > 0 | REC pressed, channel *N* = note + 1 |
| Note On 8–15, velocity > 0 | Solo pressed, channel *N* = note − 7 |
| Note On 16–23, velocity > 0 | Mute pressed, channel *N* = note − 15 |
| Note On 24–31, velocity > 0 | Select pressed, channel *N* = note − 23 |
| Control Change 16–23 | Encoder turned, channel *N* = controller − 15; value 1–7 = clockwise steps, 65–71 = counter-clockwise |
| Note On 32–39, velocity > 0 | Encoder pushed, channel *N* = note − 31 |

Touching a fader only marks it as "held" — the actual iris command is sent
continuously while dragging (through the rate limiter below), with one
final, unthrottled send on release. Turning the encoder sends a live
command immediately (also rate-limited); pushing it doesn't send anything
to the camera, it only flags the value as "saved" in the UI.

Feedback goes back over the same USB connection: the motorized fader is
driven by sending a Pitchbend message back (skipped while the fader is
being physically touched, so the motor doesn't fight your hand), the two
scribble-strip text lines per channel are set via SysEx (device ID `0x15`
— the plain X-Touch uses `0x14`, the Extender needs `0x15` or the display
stays blank), and REC/Solo/Mute/Select LEDs are driven by sending Note
On back on the same note numbers (velocity 127 = on, 0 = off — no
blinking, no color control; the Extender's LED colors are fixed per
button type in hardware).

### Software → camera (Panasonic CGI over HTTP)

Every camera command is a plain HTTP GET to the camera's CGI interface,
e.g. `GET /cgi-bin/aw_ptz?cmd=%23AXI888&res=1` to set the iris to a given
position (`#AXI` followed by a 3-hex-digit position between `555` and
`FFF`, `#` URL-encoded as `%23`) or `GET /cgi-bin/aw_cam?cmd=OGU:0D&res=1`
to set gain to a given value (`OGU:` followed by a 2-hex-digit value). Other commands follow the
same shape — pedestal, ND filter, toggle features (Auto Focus, DRS, Knee,
...) and preset recall each have their own command string, some of which
differ by camera model (`drivers/panasonic_models/*.py` holds the
per-model command/range tables). The camera answers with the same command
echoed back on success, or an `ER1`/`ER2`/`ER3`/... error code, which the
driver turns into an exception.

Separately, while connected, the app keeps a second, long-lived TCP
connection open to the camera's "update notification" feed. The camera
pushes a line over this connection every time *any* setting changes —
including changes made from somewhere else entirely, like the camera's
own web interface or another controller on the network. The driver parses
these pushes the same way it parses a normal command response, so an iris
move made outside this app still updates the motorized fader, the web UI
slider, and the scribble strip.

### End to end

Physical fader move → Pitchbend → `midi/fader.py` (Rx polling loop) →
`core/application.py`'s `apply_iris()` → `core/mapping.py` resolves the
channel to a camera → `core/ratelimit.py` throttles it (configurable, 15
commands/second by default) → `drivers/panasonic_aw.py` translates it into
the HTTP GET shown above.

Every state change — from a physical control, the web UI, or an external
change picked up via the notification feed — is published on one shared
event bus (`core/bus.py`). The WebSocket connection to the web UI and the
MIDI output path (motorized fader, scribble strips, LEDs) both subscribe
to the same events, so whichever source changed something, every other
display updates to match.

## Contributing

This project grew out of one specific shading setup, so its scope so far
reflects that. Contributions are very welcome, especially:

- **New camera drivers.** Only Panasonic's AW-series CGI protocol is
  supported today. `drivers/base.py`'s `CameraDriver` is the interface a
  new driver needs to implement; `drivers/panasonic_aw.py` is the
  reference implementation.
- **New controller support.** The MIDI layer (`midi/fader.py`) is
  currently written specifically for the Behringer X-Touch Extender
  (Mackie Control protocol assumptions, its particular SysEx
  scribble-strip layout). Supporting a different controller would mean
  factoring out a more generic interface first — a good target for a
  larger contribution.
- **Code quality, tests, and bug fixes** in general — the test suite isn't
  part of this repository, so bring or build your own test setup to verify
  changes.
- **Ideas for where this should go next** — open an issue if you have
  thoughts on scope or direction.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
