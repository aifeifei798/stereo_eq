from __future__ import annotations

import pytest

from stereo_eq_app.models import EqBand, EqPreset
from stereo_eq_app.presets import VLC_BAND_FREQUENCIES, default_presets


def test_default_preset_count_and_unique_ids() -> None:
    presets = default_presets()
    assert len(presets) == 60
    assert len({preset.preset_id for preset in presets}) == 60
    assert len([preset for preset in presets if preset.category == "电影"]) == 10


def test_default_presets_use_vlc_band_layout() -> None:
    for preset in default_presets():
        assert tuple(band.frequency for band in preset.bands) == VLC_BAND_FREQUENCIES
        assert not preset.effects.any_enabled()


def test_default_presets_are_valid() -> None:
    for preset in default_presets():
        preset.validate(48000)
        assert preset.bands


def test_preset_round_trip() -> None:
    preset = default_presets()[0]
    restored = EqPreset.from_dict(preset.to_dict())
    assert restored.to_dict() == preset.to_dict()


def test_effect_defaults_are_audible_when_enabled() -> None:
    from stereo_eq_app.models import EffectSettings

    settings = EffectSettings()
    assert settings.compressor.threshold_db < 0.0
    assert settings.spatial_locator.pan != 0.0
    assert settings.stereo_widener.width != 1.0
    assert settings.sound_booster.gain_db > 0.0


def test_effects_round_trip_and_old_preset_compatibility() -> None:
    preset = default_presets()[0]
    preset.effects.compressor.enabled = True
    preset.effects.spatial_locator.pan = -0.5
    preset.effects.stereo_widener.width = 1.4
    preset.effects.sound_booster.gain_db = 2.0
    restored = EqPreset.from_dict(preset.to_dict())
    assert restored.effects.compressor.enabled
    assert restored.effects.spatial_locator.pan == pytest.approx(-0.5)
    assert restored.effects.stereo_widener.width == pytest.approx(1.4)
    assert restored.effects.sound_booster.gain_db == pytest.approx(2.0)

    old_data = preset.to_dict()
    old_data.pop("effects")
    old_restored = EqPreset.from_dict(old_data)
    assert not old_restored.effects.any_enabled()


def test_all_disabled_preset_is_rejected() -> None:
    preset = EqPreset(
        preset_id="empty",
        name="empty",
        category="test",
        description="",
        bands=[EqBand(enabled=False)],
    )
    with pytest.raises(ValueError):
        preset.validate(48000)
