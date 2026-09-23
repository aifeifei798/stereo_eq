from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from .models import AppState, EqPreset
from .presets import default_presets


def _config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "stereo-eq"


def _state_path() -> Path:
    return _config_dir() / "state.json"


def _presets_path() -> Path:
    return _config_dir() / "presets.json"


def load_state() -> AppState:
    path = _state_path()
    try:
        return AppState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return AppState()


def save_state(state: AppState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class PresetStore:
    def __init__(self) -> None:
        self._presets = default_presets()
        self._load_custom()

    @property
    def presets(self) -> list[EqPreset]:
        return list(self._presets)

    def find(self, preset_id: str) -> EqPreset | None:
        return next((preset for preset in self._presets if preset.preset_id == preset_id), None)

    def _load_custom(self) -> None:
        try:
            data = json.loads(_presets_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, list):
            return
        for item in data:
            try:
                preset = EqPreset.from_dict(item)
                preset.built_in = False
                if self.find(preset.preset_id) is None:
                    self._presets.append(preset)
            except (TypeError, ValueError):
                continue

    def save(self, preset: EqPreset) -> None:
        preset = preset.copy()
        preset.built_in = False
        if preset.preset_id in {item.preset_id for item in self._presets if item.built_in}:
            raise ValueError("自定义预设不能覆盖内置预设编号")
        self._presets = [item for item in self._presets if item.preset_id != preset.preset_id]
        self._presets.append(preset)
        custom = [item.to_dict() for item in self._presets if not item.built_in]
        path = _presets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def import_file(self, path: str | Path) -> EqPreset:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            if not data:
                raise ValueError("预设文件为空")
            data = data[0]
        preset = EqPreset.from_dict(data)
        self.save(preset)
        return preset

    def export_file(self, preset: EqPreset, path: str | Path) -> None:
        Path(path).write_text(json.dumps(preset.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def remove(self, preset_id: str) -> None:
        preset = self.find(preset_id)
        if preset is None or preset.built_in:
            raise ValueError("只能删除自定义预设")
        self._presets = [item for item in self._presets if item.preset_id != preset_id]
        custom = [item.to_dict() for item in self._presets if not item.built_in]
        path = _presets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(custom, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def duplicate(self, preset: EqPreset, name: str | None = None) -> EqPreset:
        suffix = 2
        base_name = name or f"{preset.name} 副本"
        candidate_name = base_name
        existing_names = {item.name for item in self._presets}
        while candidate_name in existing_names:
            candidate_name = f"{base_name} {suffix}"
            suffix += 1
        candidate = replace(
            preset.copy(),
            preset_id=f"custom-{len(self._presets) + 1}-{candidate_name}",
            name=candidate_name,
            built_in=False,
        )
        self.save(candidate)
        return candidate
