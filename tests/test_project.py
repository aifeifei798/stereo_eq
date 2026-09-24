from __future__ import annotations

from pathlib import Path

from stereo_eq_app.config import PresetStore
from stereo_eq_app.pipewire import PipeWireController
from stereo_eq_app.presets import default_presets


def test_custom_preset_persistence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = PresetStore()
    preset = default_presets()[0].copy()
    preset.preset_id = "custom-test"
    preset.name = "自定义"
    preset.built_in = False
    store.save(preset)
    restored = PresetStore().find("custom-test")
    assert restored is not None
    assert restored.name == "自定义"


def test_pipewire_config_contains_vlc_bands(tmp_path: Path) -> None:
    controller = PipeWireController()
    controller.config_path = tmp_path / "99-stereo-eq.conf"
    controller.effect_bridge_mode = False
    controller._write_config(default_presets()[0], "alsa_output.test")
    text = controller.config_path.read_text(encoding="utf-8")
    for frequency in (60, 170, 310, 600, 1000, 3000, 12000, 14000, 16000):
        assert f'"Freq" = {float(frequency):.6f}' in text


def test_pipewire_config_uses_python_effect_bridge_when_enabled(tmp_path: Path) -> None:
    controller = PipeWireController()
    controller.config_path = tmp_path / "99-stereo-eq.conf"
    preset = default_presets()[0]
    preset.effects.compressor.enabled = True
    preset.effects.stereo_widener.enabled = True
    preset.effects.sound_booster.enabled = True
    controller._write_config(preset, "alsa_output.test")
    text = controller.config_path.read_text(encoding="utf-8")
    assert "stereo_eq_effect_source" in text
    assert "stereo_eq_post" not in text
    assert controller.effect_bridge_mode


def test_pipewire_config_contains_stereo_filters(tmp_path: Path) -> None:
    controller = PipeWireController()
    controller.config_path = tmp_path / "99-stereo-eq.conf"
    controller.effect_bridge_mode = False
    controller._write_config(default_presets()[0], "alsa_output.test")
    text = controller.config_path.read_text(encoding="utf-8")
    assert "libpipewire-module-filter-chain" in text
    assert "libpipewire-module-loopback" in text
    assert "bq_peaking" in text
    assert 'label = "bq_peaking"' in text
    assert "eq_band_1:In" in text
    assert "param_eq" not in text
    assert "stereo_eq_input" in text
    assert "stereo_eq_post" in text
    assert "stereo_eq_post_output" in text
