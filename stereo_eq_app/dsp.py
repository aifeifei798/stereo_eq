from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .effects import EffectChain
from .models import EqBand, EqPreset, FilterType


def _require_scipy():
    try:
        from scipy import signal
    except ImportError as error:
        raise RuntimeError("缺少 scipy，请先安装项目依赖: uv sync") from error
    return signal


def _gain(band: EqBand, side: str) -> float:
    value = band.left_gain() if side == "left" else band.right_gain()
    if not math.isfinite(value):
        raise ValueError("增益必须是有限数值")
    return value


def coefficients(
    band: EqBand,
    sample_rate: int,
    gain_db: float,
) -> tuple[np.ndarray, np.ndarray]:
    if not math.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("采样率必须是正数")
    band.validate(sample_rate)
    if not math.isfinite(gain_db) or abs(gain_db) > 60.0:
        raise ValueError("增益必须位于 -60 到 60 dB")
    filter_type = FilterType(band.filter_type)
    frequency = float(band.frequency)
    quality = float(band.q)
    omega = 2.0 * math.pi * frequency / sample_rate
    cosine = math.cos(omega)
    sine = math.sin(omega)
    amplitude = 10.0 ** (gain_db / 40.0)
    if filter_type is FilterType.PEAKING:
        alpha = sine / (2.0 * quality)
        b0 = 1.0 + alpha * amplitude
        b1 = -2.0 * cosine
        b2 = 1.0 - alpha * amplitude
        a0 = 1.0 + alpha / amplitude
        a1 = -2.0 * cosine
        a2 = 1.0 - alpha / amplitude
    elif filter_type is FilterType.LOW_SHELF:
        alpha = sine / 2.0 * math.sqrt(2.0 * (amplitude + 1.0 / amplitude))
        sqrt_amplitude = math.sqrt(amplitude)
        b0 = amplitude * ((amplitude + 1.0) - (amplitude - 1.0) * cosine + 2.0 * sqrt_amplitude * alpha)
        b1 = 2.0 * amplitude * ((amplitude - 1.0) - (amplitude + 1.0) * cosine)
        b2 = amplitude * ((amplitude + 1.0) - (amplitude - 1.0) * cosine - 2.0 * sqrt_amplitude * alpha)
        a0 = (amplitude + 1.0) + (amplitude - 1.0) * cosine + 2.0 * sqrt_amplitude * alpha
        a1 = -2.0 * ((amplitude - 1.0) + (amplitude + 1.0) * cosine)
        a2 = (amplitude + 1.0) + (amplitude - 1.0) * cosine - 2.0 * sqrt_amplitude * alpha
    elif filter_type is FilterType.HIGH_SHELF:
        alpha = sine / 2.0 * math.sqrt(2.0 * (amplitude + 1.0 / amplitude))
        sqrt_amplitude = math.sqrt(amplitude)
        b0 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cosine + 2.0 * sqrt_amplitude * alpha)
        b1 = -2.0 * amplitude * ((amplitude - 1.0) + (amplitude + 1.0) * cosine)
        b2 = amplitude * ((amplitude + 1.0) + (amplitude - 1.0) * cosine - 2.0 * sqrt_amplitude * alpha)
        a0 = (amplitude + 1.0) - (amplitude - 1.0) * cosine + 2.0 * sqrt_amplitude * alpha
        a1 = 2.0 * ((amplitude - 1.0) - (amplitude + 1.0) * cosine)
        a2 = (amplitude + 1.0) - (amplitude - 1.0) * cosine - 2.0 * sqrt_amplitude * alpha
    elif filter_type is FilterType.LOW_PASS:
        alpha = sine / (2.0 * quality)
        b0 = (1.0 - cosine) / 2.0
        b1 = 1.0 - cosine
        b2 = (1.0 - cosine) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosine
        a2 = 1.0 - alpha
    else:
        alpha = sine / (2.0 * quality)
        b0 = (1.0 + cosine) / 2.0
        b1 = -(1.0 + cosine)
        b2 = (1.0 + cosine) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cosine
        a2 = 1.0 - alpha
    b = np.array([b0, b1, b2], dtype=np.float32) / np.float32(a0)
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float32)
    if not np.all(np.isfinite(b)) or not np.all(np.isfinite(a)):
        raise ValueError("生成了无效的滤波器系数")
    return b, a


@dataclass
class _Side:
    b: np.ndarray
    a: np.ndarray
    zi: np.ndarray


class BiquadBank:
    def __init__(self, preset: EqPreset, sample_rate: int, channels: int) -> None:
        if channels < 1:
            raise ValueError("声道数必须大于零")
        preset.validate(sample_rate)
        self.sample_rate = sample_rate
        self.channels = channels
        self.preamp = 10.0 ** (preset.preamp_db / 20.0)
        self._sides: dict[str, list[_Side]] = {
            "left": [],
            "right": [],
        }
        for band in preset.bands:
            if not band.enabled:
                continue
            for side in self._sides:
                b, a = coefficients(band, sample_rate, _gain(band, side))
                self._sides[side].append(_Side(b=b, a=a, zi=np.zeros((2, channels), dtype=np.float32)))

    @property
    def section_count(self) -> int:
        return len(self._sides["left"])

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim == 1:
            source = source[:, np.newaxis]
        if source.ndim != 2 or source.shape[1] < 1:
            raise ValueError("音频数据必须是采样帧乘声道数")
        result = source.copy()
        active_channels = min(2, self.channels, source.shape[1])
        signal = _require_scipy()
        for channel in range(active_channels):
            side_name = "left" if channel == 0 else "right"
            current = source[:, channel]
            for index, section in enumerate(self._sides[side_name]):
                filtered, state = signal.lfilter(section.b, section.a, current, zi=section.zi[:, channel])
                section.zi[:, channel] = state
                current = filtered
            result[:, channel] = current * self.preamp
        return result.astype(np.float32, copy=False)

    def response_db(self, frequencies: np.ndarray) -> np.ndarray:
        signal = _require_scipy()
        responses = []
        for side in ("left", "right"):
            response = np.ones_like(frequencies, dtype=np.complex128)
            for section in self._sides[side]:
                _, current = signal.freqz(section.b, section.a, worN=frequencies, fs=self.sample_rate)
                response *= current
            responses.append(20.0 * np.log10(np.maximum(self.preamp * np.abs(response), 1.0e-12)))
        return np.maximum(responses[0], responses[1])


class PeakLimiter:
    def __init__(self, ceiling: float = 0.98, release_ms: float = 80.0, sample_rate: int = 48000) -> None:
        self.ceiling = ceiling
        self.release = math.exp(-1.0 / max(1.0, sample_rate * release_ms / 1000.0))
        self.gain = 1.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        target = min(1.0, self.ceiling / peak) if peak > self.ceiling else 1.0
        if target < self.gain:
            self.gain = target
        else:
            self.gain = self.release * self.gain + (1.0 - self.release) * target
        return (audio * self.gain).astype(np.float32, copy=False)

    def reset(self) -> None:
        self.gain = 1.0


class DspEngine:
    def __init__(self, preset: EqPreset, sample_rate: int = 48000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._active = BiquadBank(preset, sample_rate, channels)
        self._active_effects = EffectChain(preset.effects, sample_rate, channels)
        self._target: BiquadBank | None = None
        self._target_effects: EffectChain | None = None
        self._crossfade_remaining = 0
        self._crossfade_total = max(1, sample_rate // 100)
        self._crossfade_weights = np.linspace(1.0, 0.0, self._crossfade_total, dtype=np.float32)[:, np.newaxis]
        self.bypass = False
        self._limiter = PeakLimiter(sample_rate=sample_rate)
        self.latest_peak = 0.0

    def configure(self, sample_rate: int, channels: int) -> None:
        if sample_rate == self.sample_rate and channels == self.channels:
            return
        raise ValueError("DSP 格式已改变，需要重新创建引擎")

    def set_preset(self, preset: EqPreset) -> None:
        target = BiquadBank(preset, self.sample_rate, self.channels)
        target_effects = EffectChain(preset.effects, self.sample_rate, self.channels)
        self._target = target
        self._target_effects = target_effects
        self._crossfade_remaining = self._crossfade_total

    def set_bypass(self, enabled: bool) -> None:
        self.bypass = enabled

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = np.asarray(audio, dtype=np.float32)
        was_one_dimensional = source.ndim == 1
        if self.bypass:
            self.latest_peak = float(np.max(np.abs(source))) if source.size else 0.0
            return source
        elif self._target is None:
            result = self._active_effects.process(self._active.process(source))
        else:
            current = self._active_effects.process(self._active.process(source))
            target = (
                self._target_effects.process(self._target.process(source))
                if self._target_effects is not None
                else self._target.process(source)
            )
            count = min(source.shape[0], self._crossfade_remaining)
            if count:
                old_weight = self._crossfade_weights[self._crossfade_total - count :]
                result = current.copy()
                result[:count] = current[:count] * old_weight + target[:count] * (1.0 - old_weight)
                if source.shape[0] > count:
                    result[count:] = target[count:]
            else:
                result = target
            self._crossfade_remaining -= count
            if self._crossfade_remaining <= 0:
                self._active = self._target
                if self._target_effects is not None:
                    self._active_effects = self._target_effects
                self._target = None
                self._target_effects = None
        result = self._limiter.process(result)
        self.latest_peak = float(np.max(np.abs(result))) if result.size else 0.0
        return result[:, 0] if was_one_dimensional and result.ndim == 2 else result
