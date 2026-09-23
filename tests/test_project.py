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


def test_pipewire_config_contains_stereo_filters(tmp_path: Path) -> None:
    controller = PipeWireController()
    controller.config_path = tmp_path / "99-stereo-eq.conf"
    controller._write_config(default_presets()[0], "alsa_output.test")
    text = controller.config_path.read_text(encoding="utf-8")
    assert "libpipewire-module-filter-chain" in text
    assert "libpipewire-module-loopback" in text
    assert "bq_peaking" in text
    assert "eq_band_1:In" in text
    assert "param_eq" not in text
    assert "stereo_eq_input" in text
    assert "stereo_eq_post" in text
    assert "stereo_eq_post_output" in text
