from __future__ import annotations

import numpy as np
import pytest

from stereo_eq_app.dsp import BiquadBank, DspEngine, coefficients
from stereo_eq_app.effects import EffectChain
from stereo_eq_app.models import EffectSettings, EqBand, EqPreset


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


def test_vlc_preset_uses_nine_sections() -> None:
    from stereo_eq_app.presets import default_presets

    bank = BiquadBank(default_presets()[0], 48000, 2)
    assert bank.section_count == 9


def test_effects_are_finite_and_widen_stereo() -> None:
    settings = EffectSettings()
    settings.stereo_widener.enabled = True
    settings.stereo_widener.width = 2.0
    chain = EffectChain(settings, 48000, 2)
    source = np.column_stack((np.ones(128, dtype=np.float32), -np.ones(128, dtype=np.float32)))
    output = chain.process(source)
    assert output.shape == source.shape
    assert np.all(np.isfinite(output))
    assert np.max(np.abs(output[:, 0] - output[:, 1])) > 2.0


def test_compressor_returns_to_unity_after_loud_block() -> None:
    settings = EffectSettings()
    settings.compressor.enabled = True
    settings.compressor.attack_ms = 0.1
    settings.compressor.release_ms = 10.0
    chain = EffectChain(settings, 48000, 2)
    loud = np.full((4800, 2), 0.8, dtype=np.float32)
    chain.process(loud)
    quiet = np.zeros((4800, 2), dtype=np.float32)
    output = chain.process(quiet)
    assert np.max(np.abs(output)) == pytest.approx(0.0, abs=1.0e-6)


def test_widener_mix_preserves_stereo_base() -> None:
    settings = EffectSettings()
    settings.stereo_widener.enabled = True
    settings.stereo_widener.width = 0.0
    settings.stereo_widener.mix = 0.5
    chain = EffectChain(settings, 48000, 2)
    left = np.full(64, 0.6, dtype=np.float32)
    right = np.full(64, -0.2, dtype=np.float32)
    source = np.column_stack((left, right))
    output = chain.process(source)
    # width=0 -> mono (0.2, 0.2), mix=0.5 -> ((0.6+0.2)/2=0.4, (-0.2+0.2)/2=0.0)
    assert output[0, 0] == pytest.approx(0.4, abs=1e-5)
    assert output[0, 1] == pytest.approx(0.0, abs=1e-5)


def test_compressor_block_gain_is_constant_within_block() -> None:
    settings = EffectSettings()
    settings.compressor.enabled = True
    settings.compressor.threshold_db = -20.0
    settings.compressor.ratio = 4.0
    chain = EffectChain(settings, 48000, 2)
    source = np.full((1024, 2), 0.5, dtype=np.float32)
    output = chain.process(source)
    ratios = output[:, 0] / source[:, 0]
    assert np.max(ratios) - np.min(ratios) < 1e-6
    assert np.all(np.isfinite(output))


def test_booster_and_bypass_effects() -> None:
    settings = EffectSettings()
    chain = EffectChain(settings, 48000, 2)
    source = np.full((16, 2), 0.25, dtype=np.float32)
    assert np.array_equal(chain.process(source), source)

    settings.sound_booster.enabled = True
    settings.sound_booster.gain_db = 6.0
    boosted = EffectChain(settings, 48000, 2).process(source)
    assert np.max(np.abs(boosted)) > np.max(np.abs(source))


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
