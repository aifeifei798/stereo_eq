from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .models import EqBand, EqPreset, FilterType

_FILTER_NAMES = {
    FilterType.PEAKING.value: "bq_peaking",
    FilterType.LOW_SHELF.value: "bq_lowshelf",
    FilterType.HIGH_SHELF.value: "bq_highshelf",
    FilterType.LOW_PASS.value: "bq_lowpass",
    FilterType.HIGH_PASS.value: "bq_highpass",
}


@dataclass(frozen=True)
class PipeWireSink:
    name: str
    description: str

    def label(self) -> str:
        return f"{self.description} ({self.name})"


class PipeWireController:
    def __init__(self) -> None:
        self.config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.config_path = self.config_home / "pipewire" / "pipewire.conf.d" / "99-stereo-eq.conf"
        module_dir = Path("/usr/lib/x86_64-linux-gnu/pipewire-0.3")
        self.filter_module_path = module_dir / "libpipewire-module-filter-chain.so"
        self.loopback_module_path = module_dir / "libpipewire-module-loopback.so"
        self.pre_monitor_source = "stereo_eq_input.monitor"
        self.post_monitor_source = "stereo_eq_post.monitor"
        self.previous_sink: str | None = None
        self.active = False
        self.effect_bridge_mode = False
        self.live_updates_supported = False
        if self.config_path.exists():
            try:
                self.effect_bridge_mode = "stereo_eq_effect_source" in self.config_path.read_text(encoding="utf-8")
            except OSError:
                self.effect_bridge_mode = False
            if self.default_sink() == "stereo_eq_input":
                self.active = True
                self.previous_sink = self._first_physical_sink() if self.effect_bridge_mode else None

    @property
    def available(self) -> bool:
        return not self.compatibility_error

    @property
    def compatibility_error(self) -> str:
        if not shutil.which("pactl"):
            return "未找到 pactl"
        if not shutil.which("systemctl"):
            return "未找到 systemctl"
        if not shutil.which("pipewire"):
            return "未找到 pipewire"
        if not self.filter_module_path.exists():
            return "未找到 PipeWire filter-chain 模块"
        if not self.loopback_module_path.exists():
            return "未找到 PipeWire loopback 模块"
        return ""

    def version(self) -> tuple[int, int, int]:
        result = subprocess.run(["pipewire", "--version"], capture_output=True, text=True, check=False)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        if match is None:
            return (0, 0, 0)
        values = match.groups()
        return (int(values[0]), int(values[1]), int(values[2]))

    def list_sinks(self) -> list[PipeWireSink]:
        if not shutil.which("pactl"):
            return []
        result = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return []
        sinks = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            name = fields[1]
            if name in {"stereo_eq_input", "stereo_eq_post"}:
                continue
            sinks.append(PipeWireSink(name, fields[2] if len(fields) > 2 else name))
        return sinks

    def default_sink(self) -> str | None:
        if shutil.which("wpctl"):
            status = subprocess.run(["wpctl", "status", "--name"], capture_output=True, text=True, check=False)
            if status.returncode == 0:
                for line in status.stdout.splitlines():
                    match = re.search(r"^\s*[│├└─ ]*\*\s*(\d+)\.\s+(\S+)", line)
                    if match is not None:
                        return match.group(2)
        if not shutil.which("pactl"):
            return None
        result = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    def _system_gain(self, band: EqBand) -> float:
        left = band.left_gain()
        right = band.right_gain()
        if abs(left - right) > 0.01:
            return (left + right) / 2.0
        return left

    def _filter_node(self, index: int, band: EqBand) -> str:
        label = _FILTER_NAMES.get(band.filter_type, "bq_peaking")
        return (
            f'{{ type = builtin name = eq_band_{index} label = "{label}" '
            f'control = {{ "Freq" = {band.frequency:.6f} "Q" = {band.q:.6f} '
            f'"Gain" = {self._system_gain(band):.6f} }} }}'
        )

    @staticmethod
    def _quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _write_config(self, preset: EqPreset, target_sink: str) -> None:
        enabled_bands = [band for band in preset.bands if band.enabled]
        if not enabled_bands:
            raise ValueError("系统级 EQ 至少需要一个启用的频段")
        if target_sink in {"stereo_eq_input", "stereo_eq_post"}:
            raise ValueError("系统输出目标不能是 Stereo EQ 自己的虚拟设备")
        use_bridge = self.effect_bridge_mode or preset.effects.any_enabled()
        self.effect_bridge_mode = use_bridge

        if use_bridge:
            # PipeWire 1.0.x 没有可用的 FFmpeg filtergraph。这里只创建一个
            # 虚拟输入，Python 的 SystemEffectBridge 负责 EQ 和动态效果，
            # 再通过 pacat 输出到真实声卡，避免依赖 LADSPA/FFmpeg 插件。
            nodes = ['{ type = builtin name = stereo_eq_bridge_copy label = "copy" }']
            graph_inputs = ["stereo_eq_bridge_copy:In"]
            graph_outputs = ["stereo_eq_bridge_copy:Out"]
            content = f'''context.modules = [
  {{
    name = libpipewire-module-filter-chain
    args = {{
      node.name = "stereo_eq"
      node.description = "Stereo EQ"
      media.name = "Stereo EQ"
      audio.rate = 48000
      audio.channels = 2
      audio.position = [ FL FR ]
      filter.graph = {{
        nodes = [
          {" ".join(nodes)}
        ]
        links = [
        ]
        inputs = [ {" ".join(f'"{value}"' for value in graph_inputs)} ]
        outputs = [ {" ".join(f'"{value}"' for value in graph_outputs)} ]
      }}
      capture.props = {{
        node.name = "stereo_eq_input"
        media.class = Audio/Sink
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
      playback.props = {{
        node.name = "stereo_eq_effect_source"
        media.class = Audio/Source
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
    }}
  }}
]
'''
        else:
            nodes = []
            links: list[str] = []
            first_node = ""
            current_node = ""
            if abs(preset.preamp_db) > 0.001:
                nodes.append(
                    '{ type = builtin name = eq_preamp label = "bq_highshelf" '
                    f'control = {{ "Freq" = 0.0 "Q" = 1.0 "Gain" = {preset.preamp_db:.6f} }} }}'
                )
                current_node = "eq_preamp"
                first_node = current_node
            for index, band in enumerate(enabled_bands, start=1):
                node_name = f"eq_band_{index}"
                if not first_node:
                    first_node = node_name
                nodes.append(self._filter_node(index, band))
                if current_node:
                    links.append(f'{{ output = "{current_node}:Out" input = "{node_name}:In" }}')
                current_node = node_name
            graph_inputs = [f"{first_node}:In"]
            graph_outputs = [f"{current_node}:Out"]
            target = self._quote(target_sink)
            content = f'''context.modules = [
  {{
    name = libpipewire-module-filter-chain
    args = {{
      node.name = "stereo_eq"
      node.description = "Stereo EQ"
      media.name = "Stereo EQ"
      audio.rate = 48000
      audio.channels = 2
      audio.position = [ FL FR ]
      filter.graph = {{
        nodes = [
          {" ".join(nodes)}
        ]
        links = [
          {" ".join(links)}
        ]
        inputs = [ {" ".join(f'"{value}"' for value in graph_inputs)} ]
        outputs = [ {" ".join(f'"{value}"' for value in graph_outputs)} ]
      }}
      capture.props = {{
        node.name = "stereo_eq_input"
        media.class = Audio/Sink
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
      playback.props = {{
        node.name = "stereo_eq_output"
        node.passive = true
        target.object = "stereo_eq_post"
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
    }}
  }},
  {{
    name = libpipewire-module-loopback
    args = {{
      node.name = "stereo_eq_post"
      node.description = "Stereo EQ Post"
      media.name = "Stereo EQ Post"
      capture.props = {{
        node.name = "stereo_eq_post"
        media.class = Audio/Sink
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
      playback.props = {{
        node.name = "stereo_eq_post_output"
        node.passive = true
        target.object = "{target}"
        stream.dont-remix = true
        audio.channels = 2
        audio.position = [ FL FR ]
      }}
    }}
  }}
]
'''

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.config_path)

    def _restart_pipewire(self) -> None:
        command = ["systemctl", "--user", "restart", "pipewire", "wireplumber"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # PipeWire may be in a restart backoff after a bad generated config.
            # Clear that state before trying the same restart once more.
            subprocess.run(
                ["systemctl", "--user", "reset-failed", "pipewire", "wireplumber"],
                capture_output=True,
                text=True,
                check=False,
            )
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "重启 PipeWire 失败")

    def _sink_exists(self, name: str) -> bool:
        if shutil.which("wpctl"):
            status = subprocess.run(["wpctl", "status", "--name"], capture_output=True, text=True, check=False)
            if status.returncode == 0:
                for line in status.stdout.splitlines():
                    if re.search(r"^\s*[│├└─ ]*\*?\s*\d+\.\s+" + re.escape(name) + r"(?:\s|$)", line):
                        return True
        if not shutil.which("pactl"):
            return False
        result = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True, check=False)
        return result.returncode == 0 and any(f"\t{name}\t" in f"{line}\t" for line in result.stdout.splitlines())

    def _wait_for_sink(self, name: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._sink_exists(name):
                return True
            time.sleep(0.1)
        return False

    def _first_physical_sink(self) -> str | None:
        sinks = self.list_sinks()
        return sinks[0].name if sinks else None

    def _remove_config(self) -> None:
        try:
            self.config_path.unlink()
        except FileNotFoundError:
            pass

    def _set_default_sink(self, name: str) -> None:
        if shutil.which("wpctl"):
            status = subprocess.run(["wpctl", "status", "--name"], capture_output=True, text=True, check=False)
            if status.returncode == 0:
                for line in status.stdout.splitlines():
                    match = re.search(r"^\s*[│├└─ ]*\*?\s*(\d+)\.\s+" + re.escape(name) + r"(?:\s|$)", line)
                    if match is not None:
                        result = subprocess.run(
                            ["wpctl", "set-default", match.group(1)],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if result.returncode == 0:
                            return
                        raise RuntimeError(result.stderr.strip() or f"无法设置默认输出设备: {name}")
        result = subprocess.run(["pactl", "set-default-sink", name], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"无法设置默认输出设备: {name}")

    def _restore_after_failure(self, old_config: str | None, previous_sink: str | None) -> None:
        if old_config is None:
            self._remove_config()
        else:
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(old_config, encoding="utf-8")
            temporary.replace(self.config_path)
        subprocess.run(
            ["systemctl", "--user", "reset-failed", "pipewire", "wireplumber"],
            capture_output=True,
            text=True,
            check=False,
        )
        self._restart_pipewire()
        if previous_sink and previous_sink not in {"stereo_eq_input", "stereo_eq_post"}:
            self._wait_for_sink(previous_sink)
            self._set_default_sink(previous_sink)

    def activate(self, preset: EqPreset, target_sink: str | None = None) -> None:
        if not self.available:
            raise RuntimeError(self.compatibility_error)
        previous_sink = self.previous_sink or self.default_sink()
        if previous_sink in {"stereo_eq_input", "stereo_eq_post"}:
            previous_sink = self._first_physical_sink()
        routing_target = target_sink or previous_sink
        if routing_target is None:
            raise RuntimeError("没有找到可用的真实输出设备")
        old_config = self.config_path.read_text(encoding="utf-8") if self.active and self.config_path.exists() else None
        try:
            self._write_config(preset, routing_target)
            self._restart_pipewire()
            if not self._wait_for_sink("stereo_eq_input"):
                raise RuntimeError("Stereo EQ 输入虚拟输出没有成功创建")
            if not self.effect_bridge_mode and not self._wait_for_sink("stereo_eq_post"):
                raise RuntimeError("Stereo EQ 后级虚拟输出没有成功创建")
            self._set_default_sink("stereo_eq_input")
        except (OSError, RuntimeError, ValueError) as error:
            try:
                self._restore_after_failure(old_config, previous_sink)
                self.effect_bridge_mode = (
                    old_config is not None and "stereo_eq_effect_source" in old_config
                )
            except (OSError, RuntimeError) as restore_error:
                raise RuntimeError(f"系统输出启用失败，自动恢复也失败: {restore_error}") from error
            self.active = False
            raise RuntimeError(f"系统输出启用失败，已恢复原声卡: {error}") from error
        self.previous_sink = previous_sink
        self.active = True

    def update(self, preset: EqPreset, target_sink: str | None = None) -> None:
        if not self.active:
            self.activate(preset, target_sink)
            return
        if self.effect_bridge_mode:
            # EQ and dynamic effects are processed by SystemEffectBridge in Python.
            return
        if not self.available:
            raise RuntimeError(self.compatibility_error)
        old_config = self.config_path.read_text(encoding="utf-8")
        previous_sink = self.previous_sink or self.default_sink()
        if previous_sink in {"stereo_eq_input", "stereo_eq_post"}:
            previous_sink = self._first_physical_sink()
        try:
            self._write_config(preset, target_sink or previous_sink or "")
            self._restart_pipewire()
            if not self._wait_for_sink("stereo_eq_input"):
                raise RuntimeError("Stereo EQ 输入虚拟输出没有成功创建")
            if not self.effect_bridge_mode and not self._wait_for_sink("stereo_eq_post"):
                raise RuntimeError("Stereo EQ 后级虚拟输出没有成功创建")
            self._set_default_sink("stereo_eq_input")
        except (OSError, RuntimeError, ValueError) as error:
            try:
                self._restore_after_failure(old_config, previous_sink)
                self.effect_bridge_mode = (
                    old_config is not None and "stereo_eq_effect_source" in old_config
                )
            except (OSError, RuntimeError) as restore_error:
                raise RuntimeError(f"系统输出更新失败，自动恢复也失败: {restore_error}") from error
            raise RuntimeError(f"系统输出更新失败，已恢复原声卡: {error}") from error

    def deactivate(self) -> None:
        if not self.active and not self.config_path.exists():
            self.effect_bridge_mode = False
            return
        previous_sink = self.previous_sink or self.default_sink()
        if previous_sink in {"stereo_eq_input", "stereo_eq_post"}:
            previous_sink = self._first_physical_sink()
        try:
            if previous_sink and previous_sink not in {"stereo_eq_input", "stereo_eq_post"}:
                self._set_default_sink(previous_sink)
            self._remove_config()
            self._restart_pipewire()
            if previous_sink and previous_sink not in {"stereo_eq_input", "stereo_eq_post"}:
                self._wait_for_sink(previous_sink)
                self._set_default_sink(previous_sink)
        except (OSError, RuntimeError) as error:
            self._remove_config()
            try:
                self._restart_pipewire()
                if previous_sink and previous_sink not in {"stereo_eq_input", "stereo_eq_post"}:
                    self._wait_for_sink(previous_sink)
                    self._set_default_sink(previous_sink)
            except (OSError, RuntimeError) as restore_error:
                raise RuntimeError(f"系统输出停用失败，自动恢复也失败: {restore_error}") from error
            raise RuntimeError(f"系统输出停用失败，已恢复原声卡: {error}") from error
        self.active = False
        self.effect_bridge_mode = False
