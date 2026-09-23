from __future__ import annotations

import pytest

from stereo_eq_app.models import EqBand, EqPreset
from stereo_eq_app.presets import default_presets


def test_default_preset_count_and_unique_ids() -> None:
    presets = default_presets()
    assert len(presets) == 60
    assert len({preset.preset_id for preset in presets}) == 60
    assert len([preset for preset in presets if preset.category == "电影"]) == 10


def test_default_presets_are_valid() -> None:
    for preset in default_presets():
        preset.validate(48000)
        assert preset.bands


def test_preset_round_trip() -> None:
    preset = default_presets()[0]
    restored = EqPreset.from_dict(preset.to_dict())
    assert restored.to_dict() == preset.to_dict()


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
