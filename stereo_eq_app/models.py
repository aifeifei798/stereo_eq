from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FilterType(str, Enum):
    PEAKING = "peaking"
    LOW_SHELF = "low_shelf"
    HIGH_SHELF = "high_shelf"
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"


@dataclass
class EqBand:
    filter_type: str = FilterType.PEAKING.value
    frequency: float = 1000.0
    q: float = 1.0
    gain_db: float = 0.0
    enabled: bool = True
    left_gain_db: float | None = None
    right_gain_db: float | None = None

    def left_gain(self) -> float:
        return self.gain_db if self.left_gain_db is None else self.left_gain_db

    def right_gain(self) -> float:
        return self.gain_db if self.right_gain_db is None else self.right_gain_db

    def validate(self, sample_rate: int) -> None:
        if self.filter_type not in {item.value for item in FilterType}:
            raise ValueError(f"不支持的滤波器类型: {self.filter_type}")
        if not 0.0 < self.frequency < sample_rate / 2.0:
            raise ValueError(f"频率必须位于 0 和 {sample_rate / 2.0:.1f} Hz 之间")
        if not 0.0 < self.q < 100.0:
            raise ValueError("Q 值必须位于 0 和 100 之间")
        for value in (self.gain_db, self.left_gain(), self.right_gain()):
            if not isinstance(value, (int, float)) or value != value or abs(value) > 60.0:
                raise ValueError("增益必须是 -60 到 60 dB 之间的有限数值")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EqBand:
        return cls(
            filter_type=str(data.get("filter_type", FilterType.PEAKING.value)),
            frequency=float(data.get("frequency", 1000.0)),
            q=float(data.get("q", 1.0)),
            gain_db=float(data.get("gain_db", 0.0)),
            enabled=bool(data.get("enabled", True)),
            left_gain_db=None if data.get("left_gain_db") is None else float(data["left_gain_db"]),
            right_gain_db=None if data.get("right_gain_db") is None else float(data["right_gain_db"]),
        )


@dataclass
class EqPreset:
    preset_id: str
    name: str
    category: str
    description: str
    preamp_db: float = 0.0
    bands: list[EqBand] = field(default_factory=list)
    built_in: bool = True

    def validate(self, sample_rate: int) -> None:
        if not self.name.strip():
            raise ValueError("预设名称不能为空")
        if not self.preamp_db == self.preamp_db or abs(self.preamp_db) > 30.0:
            raise ValueError("预增益必须是 -30 到 30 dB 之间的有限数值")
        if not self.bands:
            raise ValueError("预设至少需要一个频段")
        if not any(band.enabled for band in self.bands):
            raise ValueError("至少需要启用一个频段")
        for band in self.bands:
            band.validate(sample_rate)

    def copy(self) -> EqPreset:
        return EqPreset(
            preset_id=self.preset_id,
            name=self.name,
            category=self.category,
            description=self.description,
            preamp_db=self.preamp_db,
            bands=[EqBand.from_dict(band.to_dict()) for band in self.bands],
            built_in=self.built_in,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "preamp_db": self.preamp_db,
            "bands": [band.to_dict() for band in self.bands],
            "built_in": self.built_in,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EqPreset:
        return cls(
            preset_id=str(data.get("preset_id", "custom")),
            name=str(data.get("name", "自定义")),
            category=str(data.get("category", "自定义")),
            description=str(data.get("description", "")),
            preamp_db=float(data.get("preamp_db", 0.0)),
            bands=[EqBand.from_dict(item) for item in data.get("bands", [])],
            built_in=bool(data.get("built_in", False)),
        )


@dataclass
class AppState:
    sample_rate: int = 48000
    block_size: int = 512
    input_device_id: int | None = None
    output_device_id: int | None = None
    monitor_output_device_id: int | None = None
    monitor_enabled: bool = False
    monitor_gain_db: float = -12.0
    master_gain_db: float = 0.0
    selected_preset_id: str = "reference-flat"
    system_output_enabled: bool = False
    pipewire_target_sink: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppState:
        defaults = cls()
        return cls(
            sample_rate=int(data.get("sample_rate", defaults.sample_rate)),
            block_size=int(data.get("block_size", defaults.block_size)),
            input_device_id=data.get("input_device_id", defaults.input_device_id),
            output_device_id=data.get("output_device_id", defaults.output_device_id),
            monitor_output_device_id=data.get("monitor_output_device_id", defaults.monitor_output_device_id),
            monitor_enabled=bool(data.get("monitor_enabled", defaults.monitor_enabled)),
            monitor_gain_db=float(data.get("monitor_gain_db", defaults.monitor_gain_db)),
            master_gain_db=float(data.get("master_gain_db", defaults.master_gain_db)),
            selected_preset_id=str(data.get("selected_preset_id", defaults.selected_preset_id)),
            system_output_enabled=bool(data.get("system_output_enabled", defaults.system_output_enabled)),
            pipewire_target_sink=data.get("pipewire_target_sink", defaults.pipewire_target_sink),
        )
