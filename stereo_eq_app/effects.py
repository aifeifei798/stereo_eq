from __future__ import annotations

import math

import numpy as np

from .models import EffectSettings


class EffectChain:
    """状态化立体声效果链，供监听和系统桥接 DSP 使用。"""

    def __init__(self, settings: EffectSettings, sample_rate: int, channels: int) -> None:
        if sample_rate <= 0 or channels < 1:
            raise ValueError("效果处理器的采样率和声道数无效")
        settings.validate()
        self.settings = settings
        self.sample_rate = sample_rate
        self.channels = channels
        self._envelope = 0.0
        self._comp_gain = 1.0
        compressor = settings.compressor
        self._attack = math.exp(-1.0 / max(1.0, sample_rate * compressor.attack_ms / 1000.0))
        self._release = math.exp(-1.0 / max(1.0, sample_rate * compressor.release_ms / 1000.0))

    def process(self, audio: np.ndarray) -> np.ndarray:
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim == 1:
            source = source[:, np.newaxis]
        if source.ndim != 2 or source.shape[1] < 1:
            raise ValueError("效果处理器需要采样帧乘声道数的数据")
        if not self.settings.compressor.enabled:
            comp_out = source
        else:
            comp_out = self._compressor(source)
        wide_out = self._stereo_widener(comp_out)
        loc_out = self._spatial_locator(wide_out)
        out = self._sound_booster(loc_out)
        if not np.all(np.isfinite(out)):
            out = np.nan_to_num(out, nan=0.0, posinf=0.98, neginf=-0.98).astype(np.float32)
        return out

    def _compressor(self, source: np.ndarray) -> np.ndarray:
        settings = self.settings.compressor
        active_channels = min(2, self.channels, source.shape[1])
        if active_channels < 1 or source.shape[0] < 1:
            return source
        frames = source.shape[0]
        # 按块计算 RMS，避免逐采样跟踪波形本身导致的谐波失真（杂音）
        block_data = source[:, :active_channels].astype(np.float64)
        rms = float(np.sqrt(np.mean(block_data * block_data))) if block_data.size else 0.0
        # 块率平滑系数：attack/release 原本是每采样系数，这里按块长度折算
        attack_block = self._attack**frames
        release_block = self._release**frames
        envelope = self._envelope
        if rms > envelope:
            envelope = attack_block * envelope + (1.0 - attack_block) * rms
        else:
            envelope = release_block * envelope + (1.0 - release_block) * rms
        threshold = settings.threshold_db
        ratio = max(1.0, settings.ratio)
        knee = max(0.0, settings.knee_db)
        makeup = 10.0 ** (settings.makeup_gain_db / 20.0)
        inv_ratio = 1.0 - 1.0 / ratio
        if envelope < 1.0e-9:
            target = makeup
        else:
            level_db = 20.0 * math.log10(max(envelope, 1.0e-9))
            over_db = level_db - threshold
            if over_db <= 0.0:
                target = makeup
            elif knee > 0.0 and over_db < knee:
                gain_db = -0.5 * inv_ratio * over_db * over_db / knee
                target = (10.0 ** (gain_db / 20.0)) * makeup
            else:
                gain_db = -over_db * inv_ratio
                if knee > 0.0:
                    gain_db += 0.5 * inv_ratio * knee
                target = (10.0 ** (gain_db / 20.0)) * makeup
        comp_gain = self._comp_gain
        coeff = attack_block if target < comp_gain else release_block
        comp_gain = coeff * comp_gain + (1.0 - coeff) * target
        if not math.isfinite(comp_gain):
            comp_gain = 1.0
        comp_gain = min(max(comp_gain, 0.0), 8.0)
        self._envelope = envelope
        self._comp_gain = comp_gain
        result = source.copy()
        result[:, :active_channels] = source[:, :active_channels] * comp_gain
        if settings.mix < 1.0:
            result[:, :active_channels] = (
                source[:, :active_channels] * (1.0 - settings.mix)
                + result[:, :active_channels] * settings.mix
            )
        return result

    def _stereo_widener(self, source: np.ndarray) -> np.ndarray:
        settings = self.settings.stereo_widener
        if not settings.enabled or source.shape[1] < 2:
            return source
        result = source.copy()
        left = source[:, 0].astype(np.float64)
        right = source[:, 1].astype(np.float64)
        middle = (left + right) * 0.5
        side = (left - right) * 0.5 * float(settings.width)
        widened_left = middle + side
        widened_right = middle - side
        widened = np.column_stack((widened_left, widened_right)).astype(np.float32)
        base = source[:, :2]
        result[:, :2] = base * (1.0 - settings.mix) + widened * settings.mix
        return result

    def _spatial_locator(self, source: np.ndarray) -> np.ndarray:
        settings = self.settings.spatial_locator
        if not settings.enabled or source.shape[1] < 2:
            return source
        result = source.copy()
        angle = (float(settings.pan) + 1.0) * math.pi / 4.0
        left_gain = math.cos(angle) / math.sqrt(0.5)
        right_gain = math.sin(angle) / math.sqrt(0.5)
        positioned = np.column_stack(
            (source[:, 0] * left_gain, source[:, 1] * right_gain)
        ).astype(np.float32)
        result[:, :2] = source[:, :2] * (1.0 - settings.mix) + positioned * settings.mix
        return result

    def _sound_booster(self, source: np.ndarray) -> np.ndarray:
        settings = self.settings.sound_booster
        if not settings.enabled:
            return source
        result = source.copy()
        active_channels = min(2, self.channels, source.shape[1])
        gain = 10.0 ** (float(settings.gain_db) / 20.0)
        boosted = source[:, :active_channels] * gain
        result[:, :active_channels] = (
            source[:, :active_channels] * (1.0 - settings.mix) + boosted * settings.mix
        )
        return result
