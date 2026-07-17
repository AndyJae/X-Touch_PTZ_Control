from __future__ import annotations

from midi.mackie import MackieControlProtocol


def test_encoder_cc_to_delta_low_values_are_positive() -> None:
    protocol = MackieControlProtocol()
    assert protocol.encoder_cc_to_delta(1) == 1
    assert protocol.encoder_cc_to_delta(7) == 7


def test_encoder_cc_to_delta_high_values_are_negative() -> None:
    protocol = MackieControlProtocol()
    assert protocol.encoder_cc_to_delta(65) == -1
    assert protocol.encoder_cc_to_delta(71) == -7
