from __future__ import annotations

import numpy as np
import pytest

from stereo_eq_app.dsp import BiquadBank, DspEngine, coefficients
from stereo_eq_app.models import EqBand, EqPreset


def peaking_preset(gain_db: float, frequency: float = 1000.0) -> EqPreset:
    return EqPreset(
        preset_id="test",
        name="test",
        category="test",
        description="",
        bands=[EqBand(frequency=frequency, q=0.707, gain_db=gain_db)],
    )


def test_flat_eq_is_unity() -> None:
    preset = peaking_preset(0.0)
    frequencies = np.geomspace(20.0, 20000.0, 512)
    response = BiquadBank(preset, 48000, 2).response_db(frequencies)
    assert np.max(np.abs(response)) < 1.0e-6


def test_peaking_eq_matches_center_gain() -> None:
    preset = peaking_preset(6.0)
    frequencies = np.array([1000.0])
    response = BiquadBank(preset, 48000, 2).response_db(frequencies)
    assert response[0] == pytest.approx(6.0, abs=0.05)


def test_invalid_band_is_rejected() -> None:
    with pytest.raises(ValueError):
        coefficients(EqBand(frequency=24000.0), 48000, 1.0)
    with pytest.raises(ValueError):
        coefficients(EqBand(q=0.0), 48000, 1.0)


def test_streaming_state_keeps_filter_continuous() -> None:
    engine = DspEngine(peaking_preset(3.0), 48000, 1)
    first = engine.process(np.zeros(128, dtype=np.float32))
    second = engine.process(np.ones(128, dtype=np.float32))
    assert first.shape == (128,)
    assert second.shape == (128,)
    assert np.all(np.isfinite(second))


def test_preset_switch_crossfades_without_nonfinite_output() -> None:
    engine = DspEngine(peaking_preset(0.0), 48000, 1)
    engine.set_preset(peaking_preset(6.0))
    for _ in range(20):
        output = engine.process(np.ones(128, dtype=np.float32))
        assert np.all(np.isfinite(output))
