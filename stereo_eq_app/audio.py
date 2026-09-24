from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .dsp import DspEngine

try:
    import sounddevice as sd
except ImportError:
    sd = None


@dataclass(frozen=True)
class AudioDevice:
    device_id: int
    name: str
    channels: int
    is_default: bool = False

    def label(self) -> str:
        suffix = " [默认]" if self.is_default else ""
        return f"{self.name} ({self.device_id}){suffix}"


def _require_sounddevice():
    if sd is None:
        raise RuntimeError("缺少 sounddevice，请先安装项目依赖: uv sync")
    return sd


def list_input_devices() -> list[AudioDevice]:
    module = _require_sounddevice()
    default = module.default.device[0]
    devices: list[AudioDevice] = []
    for index, info in enumerate(module.query_devices()):
        if int(info.get("max_input_channels", 0)) > 0:
            devices.append(AudioDevice(index, str(info["name"]), int(info["max_input_channels"]), index == default))
    return devices


def list_output_devices() -> list[AudioDevice]:
    module = _require_sounddevice()
    default = module.default.device[1]
    devices: list[AudioDevice] = []
    for index, info in enumerate(module.query_devices()):
        if int(info.get("max_output_channels", 0)) > 0:
            devices.append(AudioDevice(index, str(info["name"]), int(info["max_output_channels"]), index == default))
    return devices


class SystemOutputMonitor:
    def __init__(
        self,
        pre_source_name: str = "stereo_eq_input.monitor",
        post_source_name: str | None = "stereo_eq_post.monitor",
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> None:
        self.source_names = {"pre": pre_source_name}
        if post_source_name is not None:
            self.source_names["post"] = post_source_name
        self.sample_rate = sample_rate
        self.channels = channels
        self.peaks = {"pre": 0.0, "post": 0.0}
        self.last_error = ""
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._threads: dict[str, threading.Thread] = {}

    @property
    def running(self) -> bool:
        return bool(self._processes) and all(process.poll() is None for process in self._processes.values())

    @property
    def pre_peak(self) -> float:
        return self.peaks["pre"]

    @property
    def post_peak(self) -> float:
        return self.peaks["post"]

    def start(self) -> None:
        if self.running:
            return
        if not shutil.which("parec"):
            raise RuntimeError("未找到 parec，无法读取系统输出电平")
        self.last_error = ""
        try:
            for key, source_name in self.source_names.items():
                self._start_source(key, source_name)
        except (OSError, RuntimeError):
            self.stop()
            raise

    def _start_source(self, key: str, source_name: str) -> None:
        command = [
            "parec",
            "--device=" + source_name,
            "--format=float32le",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
            "--latency-msec=20",
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self._processes[key] = process
        thread = threading.Thread(
            target=self._read_loop,
            args=(key, process),
            name=f"stereo-eq-system-meter-{key}",
            daemon=True,
        )
        self._threads[key] = thread
        thread.start()

    def _read_loop(self, key: str, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None:
            return
        frame_bytes = self.channels * 4
        while process.poll() is None:
            data = process.stdout.read(4096 * frame_bytes)
            if not data:
                continue
            usable = len(data) - len(data) % frame_bytes
            if usable == 0:
                continue
            samples = np.frombuffer(data[:usable], dtype="<f4")
            self.peaks[key] = float(np.max(np.abs(samples))) if samples.size else 0.0
        if process.returncode not in (None, 0):
            self.last_error = f"系统输出监听器退出: {process.returncode}"

    def stop(self) -> None:
        for process in self._processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self._processes.values():
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for thread in self._threads.values():
            thread.join(timeout=1)
        self._processes.clear()
        self._threads.clear()
        self.peaks = {"pre": 0.0, "post": 0.0}


class SystemEffectBridge:
    """在不支持 FFmpeg/LADSPA 的 PipeWire 上用 Python 处理系统音频。"""

    def __init__(
        self,
        dsp: DspEngine,
        source_name: str,
        target_sink: str,
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> None:
        self.dsp = dsp
        self.source_name = source_name
        self.target_sink = target_sink
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_peak = 0.0
        self.processed_peak = 0.0
        self.last_error = ""
        self._capture: subprocess.Popen[bytes] | None = None
        self._playback: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        if not shutil.which("parec"):
            raise RuntimeError("未找到 parec，无法读取系统 EQ 输入")
        if not shutil.which("pacat"):
            raise RuntimeError("未找到 pacat，无法输出系统 EQ 后音频")
        self.last_error = ""
        capture_command = [
            "parec",
            "--device=" + self.source_name,
            "--format=float32le",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
            "--latency-msec=20",
        ]
        playback_command = [
            "pacat",
            "--device=" + self.target_sink,
            "--format=float32le",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
            "--latency-msec=20",
        ]
        try:
            self._capture = subprocess.Popen(
                capture_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            self._playback = subprocess.Popen(
                playback_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError:
            self.stop()
            raise
        self._thread = threading.Thread(target=self._run, name="stereo-eq-system-effect-bridge", daemon=True)
        self._running = True
        self._thread.start()

    def _read_exact(self, stream, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0 and self._running:
            data = stream.read(remaining)
            if not data:
                return None
            chunks.append(data)
            remaining -= len(data)
        if remaining > 0:
            return None
        return b"".join(chunks)

    def _run(self) -> None:
        capture = self._capture
        playback = self._playback
        if capture is None or capture.stdout is None or playback is None or playback.stdin is None:
            self.last_error = "系统效果桥接进程没有正确启动"
            self._running = False
            return
        frame_bytes = self.channels * np.dtype("<f4").itemsize
        chunk_frames = 1024
        chunk_bytes = chunk_frames * frame_bytes
        capture_stream = capture.stdout
        playback_stream = playback.stdin
        try:
            while self._running and capture.poll() is None:
                if playback.poll() is not None:
                    self.last_error = "系统输出 pacat 已退出，可能是输出设备被切换"
                    break
                data = self._read_exact(capture_stream, chunk_bytes)
                if data is None:
                    break
                block = np.frombuffer(data, dtype="<f4").reshape(-1, self.channels).copy()
                self.input_peak = float(np.max(np.abs(block))) if block.size else 0.0
                try:
                    processed = self.dsp.process(block)
                except (RuntimeError, ValueError) as error:
                    self.last_error = f"系统效果处理失败: {error}"
                    break
                if processed.shape[1] != self.channels:
                    fixed = np.zeros_like(block)
                    copy_channels = min(processed.shape[1], self.channels)
                    fixed[:, :copy_channels] = processed[:, :copy_channels]
                    processed = fixed
                payload = np.ascontiguousarray(processed, dtype="<f4").tobytes()
                try:
                    playback_stream.write(payload)
                    playback_stream.flush()
                except (BrokenPipeError, OSError, ValueError) as error:
                    self.last_error = f"系统效果输出断开: {error}"
                    break
                self.processed_peak = float(np.max(np.abs(processed))) if processed.size else 0.0
                if capture.poll() is not None:
                    break
        except (OSError, ValueError) as error:
            if self._running:
                self.last_error = f"系统效果桥接错误: {error}"
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        if self._capture is not None:
            if self._capture.poll() is None:
                self._capture.terminate()
            try:
                self._capture.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._capture.kill()
                self._capture.wait(timeout=1)
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._playback is not None:
            if self._playback.stdin is not None:
                try:
                    self._playback.stdin.close()
                except OSError:
                    pass
            if self._playback.poll() is None:
                self._playback.terminate()
            try:
                self._playback.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._playback.kill()
                self._playback.wait(timeout=1)
        self._capture = None
        self._playback = None
        self._thread = None
        self.input_peak = 0.0
        self.processed_peak = 0.0


class MicMonitor:
    def __init__(
        self,
        dsp: DspEngine,
        input_device_id: int | None,
        output_device_id: int | None,
        sample_rate: int,
        block_size: int,
        monitor_enabled: bool = False,
        monitor_gain_db: float = -12.0,
    ) -> None:
        self.dsp = dsp
        self.input_device_id = input_device_id
        self.output_device_id = output_device_id
        self.sample_rate = sample_rate
        self.block_size = max(64, int(block_size))
        self.monitor_enabled = monitor_enabled
        self.monitor_gain_db = monitor_gain_db
        self.latest_peak = 0.0
        self.input_peak = 0.0
        self.processed_peak = 0.0
        self.output_peak = 0.0
        self.last_error = ""
        self._input_stream: Any = None
        self._output_stream: Any = None
        self._running = False
        self._input_channels = 1
        self._output_channels = 2
        self._ring: np.ndarray | None = None
        self._ring_read = 0
        self._ring_write = 0
        self._lock = threading.Lock()
        self._conversion_buffer: np.ndarray | None = None
        self._gain_buffer: np.ndarray | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        module = _require_sounddevice()
        if self._running:
            return
        input_info = module.query_devices(self.input_device_id, "input")
        output_info = module.query_devices(self.output_device_id, "output")
        self._input_channels = min(2, int(input_info["max_input_channels"]))
        self._output_channels = min(2, int(output_info["max_output_channels"]))
        self._ring = np.zeros((max(8192, self.block_size * 8), self._input_channels), dtype=np.float32)
        self._conversion_buffer = np.zeros((self.block_size, self._output_channels), dtype=np.float32)
        self._gain_buffer = np.zeros((self.block_size, self._input_channels), dtype=np.float32)
        self._ring_read = 0
        self._ring_write = 0
        self.input_peak = 0.0
        self.processed_peak = 0.0
        self.output_peak = 0.0
        self._input_stream = module.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=self.input_device_id,
            channels=self._input_channels,
            dtype="float32",
            latency="low",
            callback=self._input_callback,
            finished_callback=self._finished_callback,
        )
        try:
            self._input_stream.start()
            if self.monitor_enabled:
                self._start_output(module)
        except Exception:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
            raise
        self._running = True

    def stop(self) -> None:
        with self._lock:
            if self._output_stream is not None:
                self._output_stream.stop()
                self._output_stream.close()
                self._output_stream = None
            if self._input_stream is not None:
                self._input_stream.stop()
                self._input_stream.close()
                self._input_stream = None
            self._running = False

    def set_monitor_enabled(self, enabled: bool) -> None:
        if enabled == self.monitor_enabled:
            return
        if not self._running:
            self.monitor_enabled = enabled
            return
        if enabled:
            try:
                self._start_output(_require_sounddevice())
            except Exception:
                if self._output_stream is not None:
                    self._output_stream.close()
                    self._output_stream = None
                raise
        else:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None
        self.monitor_enabled = enabled

    def set_monitor_gain_db(self, gain_db: float) -> None:
        self.monitor_gain_db = float(np.clip(gain_db, -60.0, 12.0))

    def _start_output(self, module: Any) -> None:
        if self._output_stream is not None:
            return
        self._output_stream = module.OutputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=self.output_device_id,
            channels=self._output_channels,
            dtype="float32",
            latency="low",
            callback=self._output_callback,
            finished_callback=self._finished_callback,
        )
        self._output_stream.start()

    def _finished_callback(self) -> None:
        self.last_error = "音频流已停止"

    def _input_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self.last_error = str(status)
        self.input_peak = float(np.max(np.abs(indata))) if indata.size else 0.0
        processed = self.dsp.process(indata)
        self.latest_peak = self.dsp.latest_peak
        self.processed_peak = self.latest_peak
        self._write_ring(processed)

    def _output_callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self.last_error = str(status)
        ring = self._ring
        gain_buffer = self._gain_buffer
        if ring is None or gain_buffer is None:
            outdata.fill(0.0)
            return
        available = (self._ring_write - self._ring_read) % ring.shape[0]
        count = min(frames, available)
        if count == 0:
            outdata.fill(0.0)
            self.output_peak = 0.0
            return
        start = self._ring_read
        end = start + count
        gain = 10.0 ** (self.monitor_gain_db / 20.0)
        if end <= ring.shape[0]:
            np.multiply(ring[start:end], gain, out=gain_buffer[:count])
        else:
            first = ring.shape[0] - start
            np.multiply(ring[start:], gain, out=gain_buffer[:first])
            np.multiply(ring[: count - first], gain, out=gain_buffer[first:count])
        self._convert_output(outdata[:count], gain_buffer[:count])
        if count < frames:
            outdata[count:].fill(0.0)
        self.output_peak = float(np.max(np.abs(outdata))) if outdata.size else 0.0
        self._ring_read = end % ring.shape[0]

    def _convert_output(self, outdata: np.ndarray, source: np.ndarray) -> None:
        input_channels = source.shape[1]
        output_channels = outdata.shape[1]
        if input_channels == output_channels:
            outdata[:] = source
        elif input_channels == 1 and output_channels >= 2:
            outdata[:, 0] = source[:, 0]
            outdata[:, 1] = source[:, 0]
            if output_channels > 2:
                outdata[:, 2:] = source[:, : output_channels - 2]
        elif output_channels == 1:
            np.mean(source[:, :2], axis=1, out=outdata[:, 0])
        else:
            outdata[:, 0] = source[:, 0]
            outdata[:, 1 : min(output_channels, input_channels)] = source[:, 1 : min(output_channels, input_channels)]
            if output_channels > input_channels:
                outdata[:, input_channels:] = source[:, -1 :]

    def _write_ring(self, data: np.ndarray) -> None:
        ring = self._ring
        if ring is None:
            return
        data = data[:, : self._input_channels]
        if data.shape[0] >= ring.shape[0]:
            data = data[-ring.shape[0] :]
        end = self._ring_write + data.shape[0]
        if end <= ring.shape[0]:
            ring[self._ring_write : end] = data
        else:
            first = ring.shape[0] - self._ring_write
            ring[self._ring_write :] = data[:first]
            ring[: data.shape[0] - first] = data[first:]
        self._ring_write = end % ring.shape[0]
