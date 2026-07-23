from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx

from core.state import CameraState
from drivers.base import CameraCommandError, CameraDriver
from drivers.panasonic_models.registry import resolve_model

# --- Iris (#AXI / #GI, §7.2): normalisiert 0.0-1.0 <-> 555h-FFFh, linear (Spec-Formel) ---
_IRIS_DATA_MIN = 0x555
_IRIS_DATA_MAX = 0xFFF

# --- Iris F-Nummer (QIF/OIF, §7.2): live gegen eine reale AW-UE160 verifiziert
# (2026-07-23, manuelle Kalibrierung -- Nutzer stufte die Iris am Kamera-OSD
# Klick fuer Klick durch, F-Nummer jeweils vom Kamera-eigenen Display abgelesen,
# Data-Wert per QIF direkt mitgeschnitten): Data/10 = F-Nummer, exakt bei allen
# 10 live gemessenen Punkten (Data 40/93/94/96/98/100/103/105/110 -> F4.0..F11.0)
# UND deckungsgleich mit den beiden in der Spec dokumentierten Ankerpunkten
# (0Eh=F1.4, A0h=F16, §7.2) -- deshalb hier als linearer Bereich 0Eh-A0h
# angewendet, obwohl live nur der Teilbereich 28h-6Eh durchlaufen wurde (die
# aktuelle Zoomposition/Optik liess die Iris nicht weiter als F4.0-F11.0 zu).
# FFh=CLOSE ist ein separater Sentinel, kein Teil der linearen Formel.
# Der Bereich A1h-FEh (zwischen dem F16-Anker und CLOSE) bleibt UNBESTAETIGT --
# zwei Live-Versuche (in beide Richtungen) sprangen jeweils in einem einzigen
# Kamera-Klick direkt von FFh (CLOSE) zu 6Eh (F11.0) bzw. zurueck, ohne einen
# Zwischenwert zu zeigen; bei der aktuellen Zoomposition scheint dieser Bereich
# ueber die normale Iris-Steuerung nicht einzeln anwaehlbar zu sein. Wird
# deshalb bewusst NICHT dekodiert (kein erfundener Wert), `query_f_number()`
# faellt dafuer auf den rohen Hex-Wert zurueck.
_F_NUMBER_DATA_MIN = 0x0E  # F1.4 (Spec-Anker)
_F_NUMBER_DATA_MAX = 0xA0  # F16.0 (Spec-Anker)
_F_NUMBER_CLOSE_DATA = 0xFF

# --- Gain (OGU/QGU): Data = 0x08 + db, 0x80 = AGC/Auto -- diese Anker sind laut
# AW-UE160_InterfaceSpecification_E.pdf UND HDIntegratedCamera_InterfaceSpecifications-E.pdf
# (§3.2.6) fuer JEDES dort dokumentierte Modell identisch, nur Bereich/Schrittweite
# unterscheiden sich -- deshalb hier als geteilte Konstante, waehrend
# GAIN_MIN_DB/GAIN_MAX_DB/GAIN_STEP_DB (die tatsaechlich camera-spezifischen Werte)
# aus dem per Modell-Registry aufgeloesten Modul kommen (siehe _apply_model_catalog()).
_GAIN_ZERO_DB_DATA = 0x08
_GAIN_AGC_DATA = 0x80

# --- R/B Gain Preset (OSL:36/38, §7.2): 418h(-1000)-800h(0)-BE8h(+1000) -> Data = 0x800 + value ---
_RB_GAIN_CENTER_DATA = 0x800

_ERROR_PREFIXES_CAM = ("ER1:", "ER2:", "ER3:")
_ERROR_PREFIXES_PTZ = ("eR1", "eR2", "eR3")
_ERROR_STATE_PREFIXES = ("rER", "OER")  # laut CameraState-Docstring in Spec §6

_REQUEST_TIMEOUT = 1.5  # §7.4: Default 1,5s Timeout, 1 Retry

# --- Update-Notification-Kanal (§7.3.1) + Lens-Info (§7.3.2) ---
# Frame-Layout (22B Reserve, 2B Size big-endian [=Payload-Laenge+8], 4B Reserve,
# Payload, 24B Reserve) live gegen die reale AW-UE160 verifiziert (Raw-TCP-
# Capture nach #LPC1-Registrierung) -- ebenso verifiziert: jede Notification
# kommt als eigene, kurzlebige TCP-Verbindung mit genau einem Frame, kein
# Dauer-Stream.
_NOTIFY_HEADER_RESERVE = 22
_NOTIFY_SIZE_FIELD_LEN = 2
_NOTIFY_MID_RESERVE = 4
_NOTIFY_HEADER_LEN = _NOTIFY_HEADER_RESERVE + _NOTIFY_SIZE_FIELD_LEN + _NOTIFY_MID_RESERVE
# §7.3.1: QSV-Notifications alle 60s als Heartbeat, >90s ohne Notification ->
# Verbindung als gestoert werten und neu registrieren. Hier wird JEDE
# empfangene Notification als Heartbeat gewertet (nicht nur QSV) -- waehrend
# aktivem #LPC1 kommt ohnehin alle 300ms ein lPI-Frame, das QSV-Intervall ist
# dann nur der Ruhezustand-Fallback.
_NOTIFY_HEARTBEAT_TIMEOUT = 90.0


def _parse_notification_payload(frame: bytes) -> str | None:
    """Payload-Rahmen ist `\\r\\n<Kommando>\\r\\n`, aufgefuellt mit Null-Bytes
    bis zur in `size` deklarierten Laenge (live gegen eine echte AW-UE160
    bestaetigt, 2026-07-20, Nutzerauftrag: `OGU`/`OSJ:0F`-Notifications kamen
    z. B. als `b'\\r\\nOGU:0D\\r\\n\\x00\\x00'` -- Null-Bytes sind KEIN
    Whitespace fuer `str.strip()`, blieben also bisher am Ende stehen und
    liessen `int(value, 16)` in `_handle_notification()` fehlschlagen,
    wodurch `gain_changed`/`pedestal_changed` fuer eine externe Aenderung
    stillschweigend nie feuerten -- Bugreport "Kamera-UI-Aenderung an Gain/
    Pedestal wird nicht erkannt"). `strip("\\x00\\r\\n \\t")` entfernt Null-
    Bytes und Whitespace von beiden Seiten in einem Durchgang."""
    if len(frame) < _NOTIFY_HEADER_LEN:
        return None
    size = int.from_bytes(
        frame[_NOTIFY_HEADER_RESERVE : _NOTIFY_HEADER_RESERVE + _NOTIFY_SIZE_FIELD_LEN], "big"
    )
    payload_len = size - 8
    if payload_len < 0 or len(frame) < _NOTIFY_HEADER_LEN + payload_len:
        return None
    payload = frame[_NOTIFY_HEADER_LEN : _NOTIFY_HEADER_LEN + payload_len]
    return payload.decode("ascii", errors="replace").strip("\x00\r\n \t")


def _parse_lens_info_iris(body: str) -> float | None:
    """`lPI[ZZZ][FFF][III]` (Spec §7.3.2, Zoom/Fokus/Iris je 3 Hex-Digits) --
    nur Iris (die letzten 3 Digits) wird ausgewertet, Zoom/Fokus ungenutzt."""
    if not body.startswith("lPI") or len(body) != 12:
        return None
    try:
        data = int(body[9:12], 16)
    except ValueError:
        return None
    return _data_to_iris(data)


def _iris_to_data(value: float) -> int:
    return _IRIS_DATA_MIN + round(value * (_IRIS_DATA_MAX - _IRIS_DATA_MIN))


def _data_to_iris(data: int) -> float:
    return (data - _IRIS_DATA_MIN) / (_IRIS_DATA_MAX - _IRIS_DATA_MIN)


def _decode_f_number(data: int) -> str | None:
    """QIF-Data -> F-Nummer-Label (siehe _F_NUMBER_DATA_MIN/-MAX/-CLOSE_DATA
    oben fuer die Herleitung). `None`, wenn `data` außerhalb des live/Spec-
    bestaetigten Bereichs liegt -- Aufrufer faellt dann auf den rohen Hex-Wert
    zurueck statt einen ungeprueften Wert zu erfinden."""
    if data == _F_NUMBER_CLOSE_DATA:
        return "CLOSE"
    if _F_NUMBER_DATA_MIN <= data <= _F_NUMBER_DATA_MAX:
        return f"F{data / 10:.1f}"
    return None


def _extract_value(body: str) -> str | None:
    """Wert nach dem letzten ':' — durchgängiges Antwortmuster der Befehlstabelle
    (z. B. 'OGU:08' -> '08', 'OID:AW-UE160' -> 'AW-UE160')."""
    if not body or ":" not in body:
        return None
    value = body.rsplit(":", 1)[-1].strip()
    return value or None


def _decode_gain_data(data: int) -> tuple[int | None, bool]:
    """Gain-Kodierung (Data = 0x08 + db, 0x80 = Auto/AGC), geteilt zwischen
    `_query_gain_state()` und der Update-Notification-Auswertung
    (`_handle_notification()`), da beide dieselbe Antwort-/Notification-
    Kodierung `OGU:[Data]` dekodieren (§4.2/§7.2). Auto ist seit
    Nutzerauftrag 2026-07-20 ein regulaerer dritter Gain-Zustand (live gegen
    AW-UE160 UND AW-UE100 bestaetigt, siehe CLAUDE.md), kein Fehler-/
    Unbekannt-Zustand mehr -- Rueckgabe (dB-Wert oder `None` bei Auto,
    ist_auto)."""
    if data == _GAIN_AGC_DATA:
        return None, True
    return data - _GAIN_ZERO_DB_DATA, False


def _match_toggle_feature(body: str, features: dict[str, dict]) -> tuple[str, bool] | None:
    """Ordnet eine Update-Notification-Payload (§4.2, exakt derselbe
    Kommando-String wie beim Senden, siehe HDIntegratedCamera_
    InterfaceSpecifications-E.pdf Fig. 4-4/4-5) einem Toggle-Feature aus
    `BUTTON_FEATURES` zu, indem `body` gegen jedes bekannte `on`/`off`-
    Kommando verglichen wird. Kein Treffer (z. B. Kommando ausserhalb des
    Katalogs) -> `None`, kein erfundener Zustand."""
    for key, feature in features.items():
        if feature.get("kind") != "toggle":
            continue
        for enabled, commands in ((True, feature.get("on")), (False, feature.get("off"))):
            if commands is None:
                continue
            command_list = commands if isinstance(commands, list) else [commands]
            if body in command_list:
                return key, enabled
    return None


class PanasonicAWDriver(CameraDriver):
    """AW-Serie (Referenz AW-UE160) über CGI/HTTP, §7 der Spec.

    Notification-Feedback-Kanal (§7.3): Lens-Info (#LPC1, nur Iris) ist über
    `start_lens_feedback()`/`stop_lens_feedback()` implementiert, siehe dort.
    Update-Notifications für andere Ereignisse (`OAW`, `OWS` etc., §7.3.1)
    laufen technisch über denselben Kanal und werden seit 2026-07-19 auch
    ausgewertet (Beleg: Kap. 4 der HDIntegratedCamera_
    InterfaceSpecifications-E.pdf, referenziert aus
    RemoteControllerInterfaceSpecifications-E.pdf §4.1.1) -- `_handle_
    notification()` gleicht die Payload neben `lPI` zusaetzlich gegen
    bekannte Toggle-Feature-/Gain-/Pedestal-Kommandos ab, siehe dortiger
    Docstring.

    **Scope-Grenze nach dem Modell-Registry-Umbau (§9a):** `BUTTON_FEATURES`/
    `BUTTON_FEATURE_LABELS` sowie Gain/Pedestal-Bereich/-Kommando (siehe
    `_apply_model_catalog()`) sind modellabhaengig und werden aus dem per
    `QID` erkannten Modell (`drivers/panasonic_models`) aufgeloest. Iris
    bleibt weiterhin NUR fuer AW-UE160 verifiziert (`_IRIS_DATA_MIN/MAX`) --
    fuer andere Modelle ist die Iris-Formel in der Spec nicht bestaetigt,
    das ist ein separater, noch offener Punkt (siehe CLAUDE.md).

    Gain-Encoding (Data = 0x08 + db, 0x80 = AGC) ist laut beiden lokalen
    Referenz-PDFs modellUNabhaengig identisch -- nur Bereich/Schrittweite
    (`gain_min_db`/`gain_max_db`/`gain_step_db`) variieren und kommen aus dem
    Modell-Modul. Pedestal hat dagegen laut
    `HDIntegratedCamera_InterfaceSpecifications-E.pdf` §3.2.14 DREI
    unterschiedliche Kommandofamilien je nach Modell (`OSJ:0F` Master
    Pedestal bei AW-UE150/AW-UE160/AW-UE100, `OTP`/`QTP` bei AW-HE50/60/120/
    130/HR140/HE40/UE70/HE42, `OSG:4A` bei AK-UB300) -- deshalb kommen
    Kommando, Zentraldatenwert, Skalierung und Hex-Breite hier vollstaendig
    aus dem Modell-Modul (`pedestal_command` u. ae., siehe
    `_apply_model_catalog()`). Modelle ohne Eintrag in einer der lokalen
    Referenz-PDFs (z. B. AW-UE80/UE30/40/50/UE145) haben bewusst KEINE
    Gain-/Pedestal-Werte -- Encoder zeigt fuer diese dann keinen
    Wertebereich (kein erfundener Fallback).
    """

    # Kamera-Feature-Buttons (Spec §9a: Button-2/3-Aktionen kommen aus der
    # pro Kameramodell verifizierten BUTTON_FEATURES/BUTTON_FEATURE_LABELS-
    # Definition, portiert aus dem externen Referenzprojekt
    # C:\smart_reset_work\camera_plugins\panasonic\*.py (dort UI_BUTTONS/
    # UI_BUTTON_LABELS, laut deren CLAUDE.md gegen reale Panasonic-Interface-
    # Specs verifiziert). Ursprünglich NICHT unabhängig gegen die lokalen
    # PDF-Referenzen (docs/specs/) nachverifiziert (PDF-Rendering war zu
    # Beginn nicht verfügbar) -- seit 2026-07-18 (`pdftotext`, siehe
    # CLAUDE.md Offene Punkte) sind `drs`/`knee` für alle Modelle mit
    # vorhandener PDF gegengeprüft (und korrigiert, wo falsch); der Rest des
    # Katalogs (auto_focus/auto_iris/awb/aww/osd/white_clip/matrix/...) ist
    # weiterhin nur gegen smart_reset_work verifiziert, nicht gegen die PDFs.
    #
    # Seit dem Modell-Registry-Umbau (§9a, Nutzerentscheid) sind das keine
    # festen Klassenattribute mehr, sondern Instanzattribute, die `connect()`
    # anhand des per `QID` erkannten Modells aus `drivers/panasonic_models`
    # auflöst (siehe `_apply_model_catalog()`) -- ein Treiber kann so je nach
    # verbundenem Modell einen anderen Katalog zeigen, statt fest auf
    # AW-UE160 zu stehen. Unbekanntes Modell -> leere Kataloge (kein
    # erfundener Fallback).
    #
    # "toggle": on/off-Kommando (einzelner String oder Liste, siehe
    #   trigger_button_feature()), kein Query verfügbar (auch in der
    #   Referenzquelle nicht — Zustand wird dort wie hier nur lokal
    #   getrackt, nicht kamera-verifiziert, siehe core/state.py).
    # "trigger": ein einmaliges Kommando, kein Ein/Aus-Zustand.
    # Mehrwertige Kamera-Parameter (Knee, DRS) sind seit Nutzerentscheid
    # 2026-07-18 KEIN eigener "cycle"-Feature-Typ mehr, sondern je ein
    # "toggle" pro sinnvollem Zielzustand (z. B. "knee_manual"/"knee_auto"
    # statt einem einzelnen "knee") -- Grund: Button 2/3 sind physische
    # Zwei-Zustand-Tasten mit einer einzigen (nicht mehrfarbigen) LED, ein
    # rundenweises Durchschalten mehrerer Zustaende laesst sich darauf nicht
    # sinnvoll anzeigen. Das Cycle-Konzept existiert weiterhin, aber nur bei
    # Button 1 (physisch Rec, Encoder-Funktionsauswahl Gain/Pedestal/Camera
    # Status, siehe core/application.py._ENCODER_FUNCTIONS) -- ein komplett
    # anderer, eigenstaendiger Mechanismus ohne Bezug zu BUTTON_FEATURES.
    BUTTON_FEATURES: dict[str, dict] = {}
    BUTTON_FEATURE_LABELS: dict[str, str] = {}

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self.model: str | None = None
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._callbacks: list[Callable[[dict], None]] = []
        self._notify_server: asyncio.Server | None = None
        self._notify_port: int | None = None
        self._notify_heartbeat_task: asyncio.Task[None] | None = None
        self._last_notification_at: float = 0.0
        # Instanzattribute (siehe Kommentar oben) -- ueberschreiben die leeren
        # Klassenattribute nach connect() anhand des erkannten Modells.
        self.BUTTON_FEATURES: dict[str, dict] = {}
        self.BUTTON_FEATURE_LABELS: dict[str, str] = {}
        # Gain/Pedestal-Modelldaten (siehe _apply_model_catalog()) -- `None`
        # heisst "kein Modell erkannt" oder "in keiner der beiden Referenz-
        # PDFs dokumentiert", kein erfundener Fallback.
        self.gain_min_db: int | None = None
        self.gain_max_db: int | None = None
        self.gain_step_db: int | None = None
        self.pedestal_command: str | None = None
        self.pedestal_query_command: str | None = None
        self.pedestal_min: int | None = None
        self.pedestal_max: int | None = None
        self.pedestal_center_data: int | None = None
        self.pedestal_scale: int | None = None
        self.pedestal_data_width: int | None = None
        # Super-Gain-Kopplung (Nutzerauftrag 2026-07-20, live gegen AW-UE100
        # verifiziert: Werte >36dB werden per ER3 abgelehnt, wenn Super Gain
        # aus ist) -- nur bei Modellen mit `GAIN_MAX_DB_SUPER_GAIN_OFF`
        # gesetzt (siehe _apply_model_catalog()), sonst bleibt beides `None`
        # und `effective_gain_max_db` liefert unveraendert `gain_max_db`.
        self.gain_max_db_super_gain_off: int | None = None
        self.super_gain_query_command: str | None = None
        # Zwischengespeicherter Super-Gain-Zustand, aufgefrischt bei jedem
        # get_state()-Aufruf (Connect UND Encoder-Funktionswechsel auf
        # "gain", siehe core/application.py::cycle_encoder_function()) --
        # `None` heisst "noch nicht abgefragt/nicht lesbar", wird dann
        # konservativ wie "aus" behandelt (schmalere Obergrenze).
        self.gain_super_gain_on: bool | None = None
        # ND-Filter-Katalog (siehe _apply_model_catalog()) -- geordnete
        # Liste (Data-Wert, Label), leer/`None` heisst "Modell hat laut den
        # lokalen Referenz-PDFs keinen physischen ND-Filter" (z. B.
        # AW-HE40/AW-HE50/AW-HE60), kein erfundener Fallback.
        self.nd_options: list[tuple[int, str]] | None = None

    # --- Lifecycle -----------------------------------------------------

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"http://{self.host}:{self.port}", timeout=_REQUEST_TIMEOUT
        )
        self.model = await self._query_model()
        self._connected = self.model is not None
        self._apply_model_catalog()

    def _apply_model_catalog(self) -> None:
        """Setzt BUTTON_FEATURES/BUTTON_FEATURE_LABELS sowie Gain-/Pedestal-
        Modelldaten anhand des per `QID` erkannten Modells (siehe
        Klassen-Docstring/§9a). Unbekanntes oder (noch) nicht verbundenes
        Modell -> leere Kataloge/`None`-Werte, kein erfundener Fallback --
        `available_button_features()` sowie `step_gain()`/`step_pedestal()`
        behandeln das bereits korrekt als "keine Optionen verfuegbar"."""
        module = resolve_model(self.model)
        self.BUTTON_FEATURES = dict(getattr(module, "BUTTON_FEATURES", {})) if module else {}
        self.BUTTON_FEATURE_LABELS = dict(getattr(module, "BUTTON_FEATURE_LABELS", {})) if module else {}
        self.gain_min_db = getattr(module, "GAIN_MIN_DB", None) if module else None
        self.gain_max_db = getattr(module, "GAIN_MAX_DB", None) if module else None
        self.gain_step_db = getattr(module, "GAIN_STEP_DB", None) if module else None
        self.pedestal_command = getattr(module, "PEDESTAL_COMMAND", None) if module else None
        self.pedestal_query_command = getattr(module, "PEDESTAL_QUERY_COMMAND", None) if module else None
        self.pedestal_min = getattr(module, "PEDESTAL_MIN", None) if module else None
        self.pedestal_max = getattr(module, "PEDESTAL_MAX", None) if module else None
        self.pedestal_center_data = getattr(module, "PEDESTAL_CENTER_DATA", None) if module else None
        self.pedestal_scale = getattr(module, "PEDESTAL_SCALE", None) if module else None
        self.pedestal_data_width = getattr(module, "PEDESTAL_DATA_WIDTH", None) if module else None
        self.gain_max_db_super_gain_off = (
            getattr(module, "GAIN_MAX_DB_SUPER_GAIN_OFF", None) if module else None
        )
        self.super_gain_query_command = getattr(module, "SUPER_GAIN_QUERY_COMMAND", None) if module else None
        nd_options = getattr(module, "ND_FILTER_OPTIONS", None) if module else None
        self.nd_options = list(nd_options) if nd_options else None

    async def disconnect(self) -> None:
        await self.stop_lens_feedback()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False

    # --- Lens-Info-Feedback (§7.3, Iris-Aenderungen durch andere Quellen) --
    # Nicht Teil der CameraDriver-ABC (wie BUTTON_FEATURES, §9a) -- die
    # Anwendungsschicht prueft per hasattr(), ob ein Treiber das anbietet.

    async def start_lens_feedback(self) -> None:
        """Registriert den Update-Notification-Kanal und aktiviert Lens-Info
        (#LPC1). Primaere Quelle fuer Iris-Feedback bei extern (z. B.
        Kamera-eigenes Web-UI) ausgeloesten Aenderungen, da `#AXI` laut Spec
        kein Update-Notification-Flag hat (§7.3.2)."""
        if self._client is None:
            raise CameraCommandError("not connected", command="event?connect=start")
        server = await asyncio.start_server(self._handle_notification, "0.0.0.0", 0)
        self._notify_server = server
        self._notify_port = server.sockets[0].getsockname()[1]
        await self._notify_request("start")
        await self._request("aw_ptz", "#LPC1")
        self._last_notification_at = time.monotonic()
        self._notify_heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_lens_feedback(self) -> None:
        if self._notify_heartbeat_task is not None:
            self._notify_heartbeat_task.cancel()
            try:
                await self._notify_heartbeat_task
            except asyncio.CancelledError:
                pass
            self._notify_heartbeat_task = None
        if self._notify_server is not None:
            try:
                await self._request("aw_ptz", "#LPC0")
            except CameraCommandError:
                pass
            try:
                await self._notify_request("stop")
            except httpx.HTTPError:
                pass
            self._notify_server.close()
            await self._notify_server.wait_closed()
            self._notify_server = None
            self._notify_port = None

    async def _notify_request(self, action: str) -> None:
        assert self._client is not None
        url = f"/cgi-bin/event?connect={action}&my_port={self._notify_port}&uid=0"
        await self._client.get(url)

    async def _handle_notification(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Jede Notification kommt als eigene, kurzlebige TCP-Verbindung mit
        genau einem Frame (live gegen die reale Kamera verifiziert).

        Ueber denselben, bereits fuer Lens-Info (`lPI`) registrierten
        Update-Notification-Kanal (§7.3.1) meldet die Kamera laut
        HDIntegratedCamera_InterfaceSpecifications-E.pdf Kap. 4 JEDE
        Aenderung eines Steuerkommandos -- unabhaengig davon, ob sie von
        PTZ_Control selbst oder einem anderen Terminal (z. B. der
        Kamera-eigenen Web-UI) ausgeloest wurde (Fig. 4-5). Die Payload ist
        dabei exakt derselbe Kommando-String wie beim Senden (z. B.
        'OGU:08'), deshalb reicht ein Abgleich gegen die bereits bekannten
        Kommandos aus BUTTON_FEATURES/Gain/Pedestal -- kein neues Parsing
        noetig. Laut Kap. 4.3.1 (Remarks) loesen einige Kommandos (OSD-Menue-
        Navigation, Pan/Tilt/Zoom/Focus/Iris, One-Touch-Focus, Contrast,
        Iris volume) KEINE Notification aus.

        **Live widerlegt (2026-07-20, echte AW-UE160):** frueher stand hier
        die Annahme, das beträfe keinen der geprueften Katalog-Eintraege --
        das ist falsch. `auto_focus` (`OAF`) und `auto_iris` (`ORS`) wurden
        direkt per CGI umgeschaltet (Kamera-UI bestaetigte den neuen Wert),
        aber weder die Solo- noch die Mute-LED (beide auf diese Features
        gemappt) reagierten -- die Kamera sendet fuer diese beiden Kommandos
        also tatsaechlich KEINE Notification, passend zur "Focus/Iris"-
        Ausnahme in Kap. 4.3.1. Betroffene Katalog-Eintraege bekommen dadurch
        nur beim naechsten expliziten Query (Zuweisung/App-Neustart) einen
        aktuellen Wert, nie push-basiert bei externer Aenderung -- siehe
        CLAUDE.md Offene Punkte.

        **Bugfix 2026-07-22 (Nutzerreport, echte AW-UE160):** `OFT` (ND-
        Filter) fehlte hier komplett -- eine am Kamera-eigenen Bedienfeld
        vorgenommene ND-Aenderung wurde deshalb nie erkannt, obwohl `OFT`
        (anders als `OAF`/`ORS`) NICHT in der Ausnahmeliste aus Kap. 4.3.1
        steht (nur OSD-Menue-Navigation, Pan/Tilt/Zoom/Focus/Iris, One-
        Touch-Focus, Contrast, Iris Volume sind dort ausgenommen)."""
        try:
            frame = await reader.read(65536)
        finally:
            writer.close()
        self._last_notification_at = time.monotonic()
        body = _parse_notification_payload(frame)
        if body is None:
            return
        iris = _parse_lens_info_iris(body)
        if iris is not None:
            for callback in self._callbacks:
                callback({"type": "iris_changed", "value": iris})
            return
        toggle_match = _match_toggle_feature(body, self.BUTTON_FEATURES)
        if toggle_match is not None:
            key, enabled = toggle_match
            for callback in self._callbacks:
                callback({"type": "feature_changed", "key": key, "enabled": enabled})
            return
        if body.startswith("OGU:"):
            value = _extract_value(body)
            if value is not None:
                try:
                    gain_db, gain_auto = _decode_gain_data(int(value, 16))
                except ValueError:
                    gain_db, gain_auto = None, None
                if gain_auto is not None:
                    for callback in self._callbacks:
                        callback({"type": "gain_changed", "value": gain_db, "auto": gain_auto})
            return
        if self.pedestal_command is not None and body.startswith(f"{self.pedestal_command}:"):
            value = _extract_value(body)
            if value is not None:
                try:
                    pedestal = self._decode_pedestal_data(int(value, 16))
                except ValueError:
                    pedestal = None
                if pedestal is not None:
                    for callback in self._callbacks:
                        callback({"type": "pedestal_changed", "value": pedestal})
            return
        if body.startswith("OFT:"):
            # ND-Filter (Nutzerauftrag 2026-07-22, Bugreport: externe
            # Aenderung -- z. B. am Kamera-eigenen Bedienfeld/Web-UI --
            # wurde bisher nicht erkannt, da dieser Zweig fehlte). Anders
            # als OGU/Pedestal ist das Data-Feld hier ein einfacher
            # Dezimalwert (siehe set_nd()/_query_nd()), kein Hex-String.
            value = _extract_value(body)
            if value is not None:
                try:
                    nd_index = int(value)
                except ValueError:
                    nd_index = None
                if nd_index is not None:
                    for callback in self._callbacks:
                        callback({"type": "nd_changed", "value": nd_index})

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                if time.monotonic() - self._last_notification_at > _NOTIFY_HEARTBEAT_TIMEOUT:
                    await self._reregister_lens_feedback()
        except asyncio.CancelledError:
            raise

    async def _reregister_lens_feedback(self) -> None:
        if self._notify_server is not None:
            self._notify_server.close()
            await self._notify_server.wait_closed()
        server = await asyncio.start_server(self._handle_notification, "0.0.0.0", 0)
        self._notify_server = server
        self._notify_port = server.sockets[0].getsockname()[1]
        await self._notify_request("start")
        self._last_notification_at = time.monotonic()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def effective_gain_max_db(self) -> int | None:
        """Tatsaechlich nutzbare Gain-Obergrenze -- bei Modellen mit
        dokumentierter Super-Gain-Kopplung (`gain_max_db_super_gain_off`,
        siehe `_apply_model_catalog()`: aw_ue100.py/aw_ue80.py (+UE30/40/50)/
        aw_ue150.py/aw_he145.py) 36dB statt `gain_max_db` (42dB), solange
        Super Gain nicht positiv als "an" bestaetigt ist (Nutzerauftrag
        2026-07-20, live gegen eine echte AW-UE100 verifiziert: Werte >36dB
        werden von der Kamera per `ER3` abgelehnt, wenn Super Gain aus ist).
        Unbekannter Zustand (`gain_super_gain_on` ist `None`, noch nicht
        abgefragt) wird konservativ wie "aus" behandelt, um ER3-Ablehnungen
        zu vermeiden. Modelle ohne diese Kopplung (`gain_max_db_super_gain_off`
        ist `None`) liefern unveraendert `gain_max_db`."""
        if self.gain_max_db_super_gain_off is not None and self.gain_super_gain_on is not True:
            return self.gain_max_db_super_gain_off
        return self.gain_max_db

    async def _query_super_gain(self) -> bool | None:
        if self.super_gain_query_command is None:
            return None
        try:
            body = await self._request("aw_cam", self.super_gain_query_command)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value, 16) == 1
        except ValueError:
            return None

    # --- Steuerung -------------------------------------------------------

    async def set_iris(self, value: float) -> None:
        data = _iris_to_data(value)
        await self._request("aw_ptz", f"#AXI{data:03X}")

    async def set_auto_iris(self, on: bool) -> None:
        await self._request("aw_cam", f"ORS:{1 if on else 0}")

    async def set_gain_db(self, db: int) -> None:
        data = _GAIN_ZERO_DB_DATA + db
        await self._request("aw_cam", f"OGU:{data:02X}")

    async def set_gain_auto(self) -> None:
        """Gain "Auto"/AGC (Data=0x80) -- Nutzerauftrag 2026-07-20, live
        gegen AW-UE160 UND AW-UE100 bestaetigt (siehe CLAUDE.md): regulaerer
        dritter Gain-Zustand, kein Fehler."""
        await self._request("aw_cam", f"OGU:{_GAIN_AGC_DATA:02X}")

    async def step_gain(self, delta_db: int) -> tuple[int | None, bool]:
        """Rueckgabe (neuer dB-Wert oder `None` bei Auto, ist_auto). Auto
        (Data=0x80) ist seit Nutzerauftrag 2026-07-20 ein regulaerer dritter
        Gain-Zustand am unteren Ende (live gegen AW-UE160 UND AW-UE100
        bestaetigt, siehe CLAUDE.md): Herunterdrehen unter `gain_min_db`
        wechselt in Auto, Hochdrehen aus Auto verlaesst Auto wieder.

        Der Ausstieg selbst ist proportional zum Dreh-Delta -- Auto wird
        dafuer als virtuelle Position "eine Stufe unter `gain_min_db`"
        behandelt (Nutzerentscheid 2026-07-20, revidiert: eine erste Version
        liess dabei jede Drehbewegung nach dem Ausstieg bewusst verwerfen
        und immer exakt bei `gain_min_db` landen, das fuehlte sich aber
        anders an als normales Drehen bei anderen Werten -- jetzt landet ein
        kraeftiges/schnelles Hochdrehen genauso proportional weiter oben wie
        bei jedem anderen Wert, nur weiterhin auf `effective_gain_max_db`
        geclampt). Weiteres Herunterdrehen waehrend Auto ist ein No-Op (kein
        tieferer Zustand als Auto)."""
        current_db, current_auto = await self._query_gain_state()
        if current_db is None and not current_auto:
            raise CameraCommandError("gain step ignored: gain unreadable", command="OGU")
        if self.gain_min_db is None or self.gain_max_db is None:
            raise CameraCommandError(
                "gain step ignored: no gain range known for this model", command="OGU"
            )
        if current_auto:
            if delta_db <= 0:
                return None, True
            new_db = min(self.effective_gain_max_db, self.gain_min_db + (delta_db - 1))
            await self.set_gain_db(new_db)
            return new_db, False
        new_db = current_db + delta_db
        if new_db < self.gain_min_db:
            await self.set_gain_auto()
            return None, True
        new_db = min(self.effective_gain_max_db, new_db)
        await self.set_gain_db(new_db)
        return new_db, False

    async def set_pedestal(self, value: int) -> None:
        if (
            self.pedestal_command is None
            or self.pedestal_center_data is None
            or self.pedestal_scale is None
            or self.pedestal_data_width is None
        ):
            raise CameraCommandError(
                "pedestal not supported for this model", command="pedestal"
            )
        data = self.pedestal_center_data + value * self.pedestal_scale
        await self._request("aw_cam", f"{self.pedestal_command}:{data:0{self.pedestal_data_width}X}")

    async def step_pedestal(self, delta: int) -> int:
        current = await self._query_pedestal()
        if current is None:
            raise CameraCommandError(
                "pedestal step ignored: pedestal unreadable",
                command=self.pedestal_command or "pedestal",
            )
        if self.pedestal_min is None or self.pedestal_max is None:
            raise CameraCommandError(
                "pedestal step ignored: no pedestal range known for this model",
                command=self.pedestal_command or "pedestal",
            )
        new_value = max(self.pedestal_min, min(self.pedestal_max, current + delta))
        await self.set_pedestal(new_value)
        return new_value

    async def set_rb_gain(self, r: int | None, b: int | None) -> None:
        if r is not None:
            data = _RB_GAIN_CENTER_DATA + r
            await self._request("aw_cam", f"OSL:36:{data:03X}")
        if b is not None:
            data = _RB_GAIN_CENTER_DATA + b
            await self._request("aw_cam", f"OSL:38:{data:03X}")

    async def set_nd(self, index: int) -> None:
        """`index` ist der Roh-Data-Wert (nicht die Listenposition) --
        modellabhaengig gueltig laut `self.nd_options` (siehe
        `_apply_model_catalog()`); manche Modelle haben eine lueckenhafte
        Werteliste (z. B. AW-HE130/AW-HR140: nur 0/3/4, siehe
        drivers/panasonic_models/aw_he130.py)."""
        if not self.nd_options:
            raise CameraCommandError("ND filter not supported for this model", command="OFT")
        valid_indices = {opt_index for opt_index, _ in self.nd_options}
        if index not in valid_indices:
            raise ValueError(f"ND index out of range: {index}")
        await self._request("aw_cam", f"OFT:{index}")

    async def cycle_nd(self) -> int:
        """Schaltet rundenweise (mit Wraparound) durch `self.nd_options` --
        anders als die Encoder-Funktion (`core/application.py::
        apply_encoder_turn`, Nutzerentscheid: Anschlag statt Wrap), da
        `cycle_nd()` fuer den urspruenglich vorgesehenen Mute-Button-Anwen-
        dungsfall (`channel_defaults.buttons.mute.action: nd_cycle`,
        weiterhin nicht verdrahtet) ein einzelner Druck ohne Richtung ist."""
        if not self.nd_options:
            raise CameraCommandError("ND filter not supported for this model", command="OFT")
        positions = [opt_index for opt_index, _ in self.nd_options]
        current = await self._query_nd()
        current_position = positions.index(current) if current in positions else -1
        new_index = positions[(current_position + 1) % len(positions)]
        await self.set_nd(new_index)
        return new_index

    async def trigger_awb(self) -> None:
        await self._request("aw_cam", "OWS")

    async def set_bars(self, on: bool) -> None:
        await self._request("aw_cam", f"DCB:{1 if on else 0}")

    async def recall_preset(self, number: int) -> None:
        if not 0 <= number <= 99:
            raise ValueError(f"preset number out of range: {number}")
        await self._request("aw_ptz", f"#R{number:02d}")

    # --- Kamera-Feature-Buttons (§9a, Katalog: BUTTON_FEATURES) -----------
    # Kein Teil der CameraDriver-ABC (Spec §6 bleibt unveraendert) -- die
    # Anwendungsschicht greift nur ueber getattr(driver, "BUTTON_FEATURES", {})
    # zu, ein Treiber ohne Katalog bietet dann einfach keine Optionen an.

    async def trigger_button_feature(self, key: str, *, enabled: bool | None = None) -> None:
        """Toggle (braucht `enabled`) oder Trigger (ignoriert `enabled`).
        `auto_iris` delegiert an die vorhandene typisierte Methode, um
        Kommando-Logik nicht doppelt zu halten.

        `feature["on"]`/`feature["off"]` sind normalerweise ein einzelner
        Kommando-String, koennen aber auch eine Liste sein (Nutzerentscheid
        2026-07-18: mehrwertige Kamera-Parameter wie Knee/DRS werden nicht
        mehr als eigenes Cycle-Feature gefuehrt, sondern als je ein Toggle
        pro Zielzustand, siehe drivers/panasonic_models/*.py -- AW-UE160s
        "Knee: Auto" braucht z. B. zwei Kommandos, `OSL:45:1` UND
        `OSA:2D:2`, in dieser Reihenfolge)."""
        if key == "auto_iris":
            if enabled is None:
                raise ValueError("'auto_iris' ist ein Toggle, 'enabled' erforderlich")
            await self.set_auto_iris(enabled)
            return
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None:
            raise ValueError(f"unbekanntes Button-Feature: {key!r}")
        if feature["kind"] == "toggle":
            if enabled is None:
                raise ValueError(f"{key!r} ist ein Toggle, 'enabled' erforderlich")
            commands = feature["on"] if enabled else feature["off"]
            if isinstance(commands, str):
                commands = [commands]
            for cmd in commands:
                await self._request("aw_cam", cmd)
        elif feature["kind"] == "trigger":
            await self._request("aw_cam", feature["cmd"])
        else:
            raise ValueError(f"{key!r}: unbekannte Feature-Art {feature['kind']!r}")

    async def query_button_feature(self, key: str) -> bool | None:
        """Fragt den Ist-Zustand eines Toggle-Button-Features ab (Nutzer-
        entscheid 2026-07-18: beim Zuweisen ueber die Web-UI sofort pruefen,
        ob an oder aus, statt den Zustand erst nach dem ersten Druck lokal
        zu kennen).

        `auto_iris` ist wie in `trigger_button_feature()` ein Sonderfall --
        nutzt die bereits vorhandene Iris-Abfrage (`#GI`-Mode-Bit) statt
        eines eigenen Query-Kommandos. Fuer alle anderen Toggle-Features
        liest diese Methode `feature["query"]`/`feature["query_on_value"]`
        (nur gesetzt, wo ein Query-Kommando direkt in den lokalen PDFs
        verifiziert wurde, siehe drivers/panasonic_models/*.py) -- fehlt
        eines von beiden, liefert diese Methode `None` (kein erfundener
        Fallback), Aufrufer behalten dann das bisherige Verhalten (Zustand
        erst nach dem ersten Druck lokal bekannt)."""
        if key == "auto_iris":
            _, auto_iris = await self._query_iris()
            return auto_iris
        feature = self.BUTTON_FEATURES.get(key)
        if feature is None or feature.get("kind") != "toggle":
            return None
        query_cmd = feature.get("query")
        query_on_value = feature.get("query_on_value")
        if query_cmd is None or query_on_value is None:
            return None
        try:
            body = await self._request("aw_cam", query_cmd)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value, 16) == int(query_on_value, 16)
        except ValueError:
            return None

    # --- Status ----------------------------------------------------------

    async def get_state(self) -> CameraState:
        iris, auto_iris = await self._query_iris()
        gain_db, gain_auto = await self._query_gain_state()
        # Aktualisiert den zwischengespeicherten Super-Gain-Zustand (siehe
        # `effective_gain_max_db`) -- get_state() wird sowohl bei connect()
        # als auch bei jedem Wechsel der Encoder-Funktion auf "gain"
        # aufgerufen (core/application.py::cycle_encoder_function()), damit
        # bleibt dieser Cache ohne zusaetzliche Wiring-Stelle einigermassen
        # frisch, ohne bei jedem einzelnen Encoder-Tick erneut abzufragen.
        if self.super_gain_query_command is not None:
            self.gain_super_gain_on = await self._query_super_gain()
        return CameraState(
            iris=iris,
            iris_f_number=await self.query_f_number(),
            auto_iris=auto_iris,
            gain_db=gain_db,
            gain_auto=gain_auto,
            pedestal=await self._query_pedestal(),
            nd_index=await self._query_nd(),
            bars=None,  # QBR-Response-Format nicht in Spec definiert (nur Query-Name, §11)
            error=await self._query_error(),
        )

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    # --- interne Query-Helfer (§11: #GI, QIF, QGU, QFT, QRS, QBR) ---------

    async def _query_model(self) -> str | None:
        try:
            body = await self._request("aw_cam", "QID")
        except CameraCommandError:
            return None
        return _extract_value(body)

    async def _query_iris(self) -> tuple[float | None, bool | None]:
        try:
            body = await self._request("aw_ptz", "#GI")
        except CameraCommandError:
            return None, None
        # Antwortformat gi[Pos][Mode]: "gi" + 3 Hex-Digits Pos + 1 Hex-Digit Mode (§7.2)
        if len(body) < 6 or not body.lower().startswith("gi"):
            return None, None
        try:
            pos = int(body[2:5], 16)
            mode = int(body[5:6], 16)
        except ValueError:
            return None, None
        return _data_to_iris(pos), (mode == 1)

    async def query_f_number(self) -> str | None:
        # OIF-Data->F-Nummer-Dekodierung siehe _decode_f_number() oben (live
        # gegen eine reale AW-UE160 kalibriert, 2026-07-23). Faellt auf den
        # rohen Hex-Wert zurueck, wenn `data` außerhalb des bestaetigten
        # Bereichs liegt (kein erfundener Wert) oder nicht als Hex parsbar ist.
        # Oeffentlich (kein Underscore-Praefix mehr, Nutzerauftrag
        # 2026-07-23): core/application.py::apply_iris() ruft dies bei JEDEM
        # Fader-Tick separat auf (statt nur bei final=True + vollem
        # get_state()), damit die F-Nummer live waehrend des Ziehens
        # mitlaeuft -- eine einzelne QIF-Abfrage ist klein genug, um das
        # nicht spuerbar zusaetzlich zu belasten.
        try:
            body = await self._request("aw_cam", "QIF")
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            data = int(value, 16)
        except ValueError:
            return value
        return _decode_f_number(data) or value

    async def _query_gain_state(self) -> tuple[int | None, bool | None]:
        # QGU als Query-Kommando live gegen AW-UE160 verifiziert (Spec §14
        # Punkt 2, siehe CLAUDE.md). Rueckgabe (dB-Wert oder None bei Auto,
        # ist_auto -- None heisst hier "nicht lesbar", nicht Auto).
        try:
            body = await self._request("aw_cam", "QGU")
        except CameraCommandError:
            return None, None
        value = _extract_value(body)
        if value is None:
            return None, None
        return _decode_gain_data(int(value, 16))

    def _decode_pedestal_data(self, data: int) -> int | None:
        """Pedestal-Kodierung des verbundenen Modells (`pedestal_center_data`/
        `pedestal_scale`, siehe `_apply_model_catalog()`), geteilt zwischen
        `_query_pedestal()` und der Update-Notification-Auswertung
        (`_handle_notification()`) -- beide dekodieren dieselbe `[Data]` aus
        Query-Antwort bzw. Notification-Payload (§4.2)."""
        if self.pedestal_center_data is None or self.pedestal_scale is None:
            return None
        return (data - self.pedestal_center_data) // self.pedestal_scale

    async def _query_pedestal(self) -> int | None:
        # Abfrage-Kommando kommt aus dem per Modell-Registry aufgeloesten
        # Modul (siehe _apply_model_catalog()) -- QSJ:0F fuer AW-UE150/
        # AW-UE160, QTP fuer AW-HE50/60/120/130/HR140/HE40/UE70/HE42, QSG:4A
        # fuer AK-UB300 (Dokumentenbeleg aus den beiden lokalen Referenz-PDFs,
        # nicht live am Geraet verifiziert, analog zu QGU, siehe CLAUDE.md
        # Offene Punkte). Unbekanntes/undokumentiertes Modell -> kein Query.
        if (
            self.pedestal_query_command is None
            or self.pedestal_center_data is None
            or self.pedestal_scale is None
        ):
            return None
        try:
            body = await self._request("aw_cam", self.pedestal_query_command)
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            data = int(value, 16)
        except ValueError:
            return None
        return self._decode_pedestal_data(data)

    async def _query_nd(self) -> int | None:
        try:
            body = await self._request("aw_cam", "QFT")
        except CameraCommandError:
            return None
        value = _extract_value(body)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def _query_error(self) -> str | None:
        try:
            body = await self._request("aw_cam", "QER")
        except CameraCommandError:
            return None
        if body.startswith(_ERROR_STATE_PREFIXES):
            return body
        return None

    # --- HTTP-Transport (§7.1, §7.4) --------------------------------------

    async def _request(self, endpoint: str, cmd: str) -> str:
        if self._client is None:
            raise CameraCommandError("not connected", command=cmd)

        encoded_cmd = cmd.replace("#", "%23")
        url = f"/cgi-bin/{endpoint}?cmd={encoded_cmd}&res=1"

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException:
            try:
                response = await self._client.get(url)  # §7.4: 1 Retry
            except httpx.HTTPError as exc:
                self._connected = False
                raise CameraCommandError(
                    f"timeout: {cmd}", command=cmd
                ) from exc
        except httpx.HTTPError as exc:
            self._connected = False
            raise CameraCommandError(
                f"connection error: {cmd}: {exc}", command=cmd
            ) from exc

        body = response.text.strip()
        error_prefixes = (
            _ERROR_PREFIXES_PTZ if endpoint == "aw_ptz" else _ERROR_PREFIXES_CAM
        )
        if body.startswith(error_prefixes):
            raise CameraCommandError(
                f"camera error for '{cmd}': {body}", command=cmd, response=body
            )
        return body
