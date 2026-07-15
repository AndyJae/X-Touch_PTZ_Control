from __future__ import annotations

from core.ratelimit import RateLimiter


class FakeClock:
    """Steuerbare Zeitquelle, ersetzt time.monotonic() im Test."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _patch_clock(limiter: RateLimiter, clock: FakeClock, monkeypatch) -> None:
    monkeypatch.setattr("core.ratelimit.time.monotonic", clock)


def test_first_value_is_sent(monkeypatch) -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_hz=15.0)
    _patch_clock(limiter, clock, monkeypatch)

    assert limiter.should_send(0.5) is True


def test_repeated_calls_within_interval_are_throttled(monkeypatch) -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_hz=10.0)  # 100ms Mindestabstand
    _patch_clock(limiter, clock, monkeypatch)

    assert limiter.should_send(0.1) is True
    clock.advance(0.05)  # < 100ms seit letztem Send
    assert limiter.should_send(0.2) is False
    clock.advance(0.06)  # jetzt insgesamt 110ms seit letztem Send
    assert limiter.should_send(0.2) is True


def test_unchanged_value_is_not_resent_even_after_interval(monkeypatch) -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_hz=100.0, hysteresis=0.01)
    _patch_clock(limiter, clock, monkeypatch)

    assert limiter.should_send(0.3) is True
    clock.advance(1.0)
    # Wert hat sich nicht (nennenswert) geaendert -> Delta-Filter greift,
    # unabhaengig davon, dass der Bucket laengst wieder frei waere.
    assert limiter.should_send(0.3005) is False


def test_change_beyond_hysteresis_is_sent_after_interval(monkeypatch) -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_hz=100.0, hysteresis=0.01)
    _patch_clock(limiter, clock, monkeypatch)

    assert limiter.should_send(0.3) is True
    clock.advance(1.0)
    assert limiter.should_send(0.5) is True


def test_final_bypasses_bucket_and_hysteresis(monkeypatch) -> None:
    clock = FakeClock()
    limiter = RateLimiter(max_hz=1.0, hysteresis=0.5)  # sehr restriktiv
    _patch_clock(limiter, clock, monkeypatch)

    assert limiter.should_send(0.3) is True
    # Ohne final wuerde weder Bucket (max_hz=1) noch Hysterese (0.5) das
    # Senden direkt danach erlauben.
    assert limiter.should_send(0.31, final=False) is False
    assert limiter.should_send(0.31, final=True) is True


def test_latest_wins_no_queueing() -> None:
    """Spec §8: bei Ueberlauf wird nur der neueste Wert gehalten, keine
    Queue-Bildung. Der Rate-Limiter selbst haelt keine verworfenen
    Zwischenwerte vor -- der Aufrufer bekommt nur True/False pro Aufruf."""
    limiter = RateLimiter(max_hz=1.0)

    assert limiter.should_send(0.1) is True
    # Schnelle Folge-Updates werden verworfen (nicht gequeued), das jeweils
    # aktuellste `value` haette der Aufrufer trotzdem zur Hand.
    assert limiter.should_send(0.2) is False
    assert limiter.should_send(0.3) is False
