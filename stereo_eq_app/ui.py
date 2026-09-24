from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audio import (
    AudioDevice,
    MicMonitor,
    SystemEffectBridge,
    SystemOutputMonitor,
    list_input_devices,
    list_output_devices,
)
from .config import PresetStore, load_state, save_state
from .dsp import BiquadBank, DspEngine
from .models import AppState, EqBand, EqPreset, FilterType
from .pipewire import PipeWireController


class EqGraph(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._response = np.zeros(0, dtype=np.float64)
        self._frequencies = np.geomspace(20.0, 20000.0, 300)
        self._sample_rate = 48000

    def set_preset(self, preset: EqPreset, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        try:
            bank = BiquadBank(preset, sample_rate, 2)
            self._response = bank.response_db(self._frequencies)
        except (RuntimeError, ValueError):
            self._response = np.zeros_like(self._frequencies)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#15191f"))
        left, top, right, bottom = 42, 18, self.width() - 18, self.height() - 30
        painter.setPen(QPen(QColor("#37404b"), 1))
        for index in range(5):
            y = top + (bottom - top) * index / 4
            painter.drawLine(left, int(y), right, int(y))
            painter.drawText(4, int(y + 4), f"{18 - index * 9:+d} dB")
        for index in range(7):
            x = left + (right - left) * index / 6
            painter.drawLine(int(x), top, int(x), bottom)
            frequency = 20 * (20000 / 20) ** (index / 6)
            painter.drawText(int(x - 14), bottom + 18, f"{frequency:.0f}")
        if self._response.size != self._frequencies.size:
            return
        painter.setPen(QPen(QColor("#61dafb"), 2))
        points = []
        for frequency, gain in zip(self._frequencies, self._response):
            x = left + (right - left) * math.log10(frequency / 20.0) / math.log10(20000.0 / 20.0)
            y = top + (bottom - top) * (1.0 - (gain + 18.0) / 36.0)
            points.append((int(x), int(y)))
        for first, second in zip(points, points[1:]):
            painter.drawLine(first[0], first[1], second[0], second[1])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stereo EQ")
        self.resize(1280, 820)
        self.state: AppState = load_state()
        self.store = PresetStore()
        self.pipewire = PipeWireController()
        self.system_meter = SystemOutputMonitor(
            post_source_name=None if self.pipewire.effect_bridge_mode else "stereo_eq_post.monitor"
        )
        self.dsp: DspEngine | None = None
        self.system_bridge: SystemEffectBridge | None = None
        self.monitor: MicMonitor | None = None
        self._loading = False
        self._last_selected_id = self.state.selected_preset_id
        self.band_sliders: dict[int, QSlider] = {}
        self.band_slider_labels: dict[int, QLabel] = {}
        self.band_gain_spins: dict[int, QDoubleSpinBox] = {}
        self.effect_enabled_checks: dict[str, QCheckBox] = {}
        self.effect_sliders: dict[str, dict[str, QSlider]] = {}
        self.effect_labels: dict[str, dict[str, QLabel]] = {}
        self.effect_scales: dict[str, dict[str, float]] = {}
        self.effect_decimals: dict[str, dict[str, int]] = {}
        self.effect_units: dict[str, dict[str, str]] = {}
        self._effect_system_timer = QTimer(self)
        self._effect_system_timer.setSingleShot(True)
        self._effect_system_timer.timeout.connect(self._effect_system_update)
        self._system_eq_update_timer = QTimer(self)
        self._system_eq_update_timer.setSingleShot(True)
        self._system_eq_update_timer.timeout.connect(self._system_eq_update)
        self._system_bridge_watchdog = QTimer(self)
        self._system_bridge_watchdog.setInterval(1000)
        self._system_bridge_watchdog.timeout.connect(self._check_system_bridge)
        self._system_bridge_watchdog.start()
        self._build_ui()
        self._refresh_devices()
        self._refresh_presets()
        self._select_preset(self.state.selected_preset_id)
        if self.pipewire.active:
            if self.pipewire.effect_bridge_mode:
                preset = self._current_preset()
                if preset is not None:
                    self._start_system_effect_bridge(preset)
            self._start_system_meter()
            self.status_label.setText("系统输出已接管；系统输出电平正在监听")
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(100)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)
        self.setCentralWidget(root)

        control_group = QGroupBox("音频链路")
        control_layout = QHBoxLayout(control_group)
        self.input_combo = QComboBox()
        self.input_combo.setMinimumWidth(230)
        self.monitor_output_combo = QComboBox()
        self.monitor_output_combo.setMinimumWidth(230)
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100", "48000"])
        self.sample_rate_combo.setCurrentText(str(self.state.sample_rate))
        self.block_size_combo = QComboBox()
        self.block_size_combo.addItems(["128", "256", "512", "1024"])
        self.block_size_combo.setCurrentText(str(self.state.block_size))
        control_layout.addWidget(QLabel("麦克风"))
        control_layout.addWidget(self.input_combo)
        control_layout.addWidget(QLabel("监听输出"))
        control_layout.addWidget(self.monitor_output_combo)
        control_layout.addWidget(QLabel("采样率"))
        control_layout.addWidget(self.sample_rate_combo)
        control_layout.addWidget(QLabel("块大小"))
        control_layout.addWidget(self.block_size_combo)
        control_layout.addStretch(1)
        root_layout.addWidget(control_group)

        self.preset_search = QLineEdit()
        self.preset_search.setPlaceholderText("搜索预设或分类")
        self.preset_search.textChanged.connect(self._refresh_presets)
        self.preset_list = QListWidget()
        self.preset_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.preset_list.currentItemChanged.connect(self._preset_selected)
        self.preset_list.setMinimumWidth(230)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.preset_search)
        left_layout.addWidget(self.preset_list, 1)
        preset_buttons = QHBoxLayout()
        self.import_button = QPushButton("导入")
        self.export_button = QPushButton("导出")
        self.save_button = QPushButton("另存")
        self.import_button.clicked.connect(self._import_preset)
        self.export_button.clicked.connect(self._export_preset)
        self.save_button.clicked.connect(self._save_preset)
        preset_buttons.addWidget(self.import_button)
        preset_buttons.addWidget(self.export_button)
        preset_buttons.addWidget(self.save_button)
        left_layout.addLayout(preset_buttons)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.graph = EqGraph()
        right_layout.addWidget(self.graph, 1)
        self.band_table = QTableWidget(0, 7)
        self.band_table.setHorizontalHeaderLabels(["启用", "类型", "频率 Hz", "Q", "左增益 dB", "右增益 dB", "删除"])
        vertical_header = self.band_table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self.band_table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setStretchLastSection(False)
            horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        band_tab = QWidget()
        band_tab_layout = QVBoxLayout(band_tab)
        band_tab_layout.setContentsMargins(4, 4, 4, 4)
        band_tab_layout.addWidget(self._build_band_slider_panel())
        band_tab_layout.addStretch(1)

        advanced_eq_tab = QWidget()
        advanced_eq_layout = QVBoxLayout(advanced_eq_tab)
        advanced_eq_layout.setContentsMargins(4, 4, 4, 4)
        advanced_eq_layout.addWidget(self.band_table, 1)
        add_button = QPushButton("添加频段")
        add_button.clicked.connect(self._add_band)
        advanced_eq_layout.addWidget(add_button, 0, Qt.AlignmentFlag.AlignLeft)

        effect_tab = QWidget()
        effect_tab_layout = QVBoxLayout(effect_tab)
        effect_tab_layout.setContentsMargins(4, 4, 4, 4)
        effect_tab_layout.addWidget(self._build_effect_panel())
        effect_tab_layout.addStretch(1)

        self.control_tabs = QTabWidget()
        self.control_tabs.addTab(band_tab, "九段 EQ")
        self.control_tabs.addTab(advanced_eq_tab, "高级九段 EQ")
        self.control_tabs.addTab(effect_tab, "音频效果")
        right_layout.addWidget(self.control_tabs, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([260, 960])
        root_layout.addWidget(splitter, 1)

        action_group = QGroupBox("运行控制")
        action_layout = QHBoxLayout(action_group)
        self.start_button = QPushButton("启动麦克风监听")
        self.stop_button = QPushButton("停止")
        self.bypass_check = QCheckBox("旁路")
        self.bypass_check.stateChanged.connect(self._bypass_changed)
        self.monitor_check = QCheckBox("开启监听")
        self.monitor_check.setChecked(self.state.monitor_enabled)
        self.monitor_check.stateChanged.connect(self._monitor_changed)
        self.monitor_gain = QSlider(Qt.Orientation.Horizontal)
        self.monitor_gain.setRange(-60, 12)
        self.monitor_gain.setValue(int(self.state.monitor_gain_db))
        self.monitor_gain.setMaximumWidth(180)
        self.monitor_gain.valueChanged.connect(self._monitor_gain_changed)
        self.system_sink_combo = QComboBox()
        self.system_sink_combo.setMinimumWidth(220)
        self.system_button = QPushButton("启用系统输出")
        self.system_stop_button = QPushButton("停用系统输出")
        self.system_button.clicked.connect(self._enable_system_output)
        self.system_stop_button.clicked.connect(self._disable_system_output)
        self.system_button.setEnabled(True)
        self.system_stop_button.setEnabled(True)
        self.system_button.setToolTip("点击后会检查 PipeWire 兼容性，不会自动接管系统输出")
        self.system_stop_button.setToolTip("停止系统级 EQ；未启用时不会有动作")
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.bypass_check)
        action_layout.addWidget(self.monitor_check)
        action_layout.addWidget(QLabel("监听增益"))
        action_layout.addWidget(self.monitor_gain)
        action_layout.addStretch(1)
        action_layout.addWidget(QLabel("系统目标"))
        action_layout.addWidget(self.system_sink_combo)
        action_layout.addWidget(self.system_button)
        action_layout.addWidget(self.system_stop_button)
        self.start_button.clicked.connect(self._start_monitor)
        self.stop_button.clicked.connect(self._stop_monitor)
        root_layout.addWidget(action_group)

        self.status_label = QLabel("系统输出未接管；当前系统输出只由 PipeWire 管理")
        (
            self.input_meter,
            self.eq_meter,
            self.output_meter,
            self.system_input_meter,
            self.system_eq_meter,
        ) = self._create_meters()
        meter_group = QGroupBox("实时电平")
        meter_layout = QHBoxLayout(meter_group)
        meter_layout.addWidget(QLabel("输入"))
        meter_layout.addWidget(self.input_meter)
        meter_layout.addWidget(QLabel("EQ 后"))
        meter_layout.addWidget(self.eq_meter)
        meter_layout.addWidget(QLabel("监听输出"))
        meter_layout.addWidget(self.output_meter)
        meter_layout.addWidget(QLabel("系统 EQ 前"))
        meter_layout.addWidget(self.system_input_meter)
        meter_layout.addWidget(QLabel("系统 EQ 后"))
        meter_layout.addWidget(self.system_eq_meter)
        root_layout.addWidget(meter_group)
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        root_layout.addLayout(status_layout)
        self._update_system_controls()

    def _build_band_slider_panel(self) -> QGroupBox:
        panel = QGroupBox("九段 EQ（竖向调节）")
        layout = QHBoxLayout(panel)
        self.band_slider_frequency_labels: dict[int, QLabel] = {}
        for index in range(9):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(2, 2, 2, 2)
            frequency_label = QLabel()
            frequency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(frequency_label)
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-200, 200)
            slider.setSingleStep(1)
            slider.setPageStep(10)
            slider.setMinimumHeight(105)
            slider.setMaximumWidth(42)
            slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            slider.setToolTip("左右声道共同增益：±20 dB，滚轮/键盘上下 0.1 dB")

            def slider_changed(value: int, band_index: int = index) -> None:
                self._band_slider_changed(band_index, value)

            slider.valueChanged.connect(slider_changed)
            column_layout.addWidget(slider)
            value_label = QLabel("0.0 dB")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(value_label)
            gain_spin = QDoubleSpinBox()
            gain_spin.setRange(-20.0, 20.0)
            gain_spin.setSingleStep(0.1)
            gain_spin.setDecimals(1)
            gain_spin.setSuffix(" dB")
            gain_spin.setMaximumWidth(90)
            gain_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            gain_spin.setToolTip("直接输入增益：±20 dB，步进 0.1 dB")

            def spin_changed(value: float, band_index: int = index) -> None:
                self._band_spin_changed(band_index, value)

            gain_spin.valueChanged.connect(spin_changed)
            column_layout.addWidget(gain_spin)
            layout.addWidget(column)
            self.band_sliders[index] = slider
            self.band_slider_frequency_labels[index] = frequency_label
            self.band_slider_labels[index] = value_label
            self.band_gain_spins[index] = gain_spin
        return panel

    @staticmethod
    def _format_frequency(frequency: float) -> str:
        if frequency >= 1000.0:
            return f"{frequency / 1000.0:g}k"
        return f"{frequency:g}"

    def _populate_band_sliders(self, preset: EqPreset) -> None:
        for index in range(9):
            slider = self.band_sliders[index]
            frequency_label = self.band_slider_frequency_labels[index]
            value_label = self.band_slider_labels[index]
            gain_spin = self.band_gain_spins[index]
            if index >= len(preset.bands):
                slider.setVisible(False)
                frequency_label.setVisible(False)
                value_label.setVisible(False)
                gain_spin.setVisible(False)
                continue
            band = preset.bands[index]
            gain = (band.left_gain() + band.right_gain()) / 2.0
            slider.setVisible(True)
            frequency_label.setVisible(True)
            value_label.setVisible(True)
            gain_spin.setVisible(True)
            frequency_label.setText(f"{self._format_frequency(band.frequency)} Hz")
            slider.blockSignals(True)
            slider.setValue(int(round(gain * 10.0)))
            slider.blockSignals(False)
            gain_spin.blockSignals(True)
            gain_spin.setValue(round(gain, 1))
            gain_spin.blockSignals(False)
            value_label.setText(f"{gain:.1f} dB")

    def _apply_band_gain(self, row: int, gain: float) -> None:
        preset = self._current_preset()
        if preset is None or row >= len(preset.bands):
            return
        band = preset.bands[row]
        band.gain_db = gain
        band.left_gain_db = gain
        band.right_gain_db = gain
        for column in (4, 5):
            spin = cast(QDoubleSpinBox, self.band_table.cellWidget(row, column))
            spin.blockSignals(True)
            spin.setValue(gain)
            spin.blockSignals(False)
        slider = self.band_sliders[row]
        slider.blockSignals(True)
        slider.setValue(int(round(gain * 10.0)))
        slider.blockSignals(False)
        gain_spin = self.band_gain_spins[row]
        gain_spin.blockSignals(True)
        gain_spin.setValue(round(gain, 1))
        gain_spin.blockSignals(False)
        self.band_slider_labels[row].setText(f"{gain:.1f} dB")
        self.graph.set_preset(preset, int(self.sample_rate_combo.currentText()))
        self._apply_preset(preset)
        self._schedule_system_eq_update()

    def _band_slider_changed(self, row: int, value: int) -> None:
        if self._loading:
            return
        self._apply_band_gain(row, value / 10.0)

    def _band_spin_changed(self, row: int, value: float) -> None:
        if self._loading:
            return
        gain = round(float(value), 1)
        gain = max(-20.0, min(20.0, gain))
        self._apply_band_gain(row, gain)

    def _build_effect_panel(self) -> QGroupBox:
        specs: dict[str, tuple[str, list[tuple[str, str, float, float, float, int, str]]]] = {
            "compressor": (
                "压缩器",
                [
                    ("threshold_db", "阈值", -60.0, 0.0, 10.0, 1, " dB"),
                    ("ratio", "压缩比", 1.0, 20.0, 10.0, 1, ":1"),
                    ("attack_ms", "启动", 0.1, 2000.0, 10.0, 1, " ms"),
                    ("release_ms", "释放", 1.0, 9000.0, 1.0, 0, " ms"),
                    ("knee_db", "拐点", 0.0, 24.0, 1.0, 0, " dB"),
                    ("makeup_gain_db", "补偿", -24.0, 24.0, 1.0, 0, " dB"),
                    ("mix", "混合", 0.0, 1.0, 100.0, 0, ""),
                ],
            ),
            "spatial_locator": (
                "声场定位器",
                [
                    ("pan", "左右", -1.0, 1.0, 100.0, 2, ""),
                    ("mix", "混合", 0.0, 1.0, 100.0, 0, ""),
                ],
            ),
            "stereo_widener": (
                "立体声扩展器",
                [
                    ("width", "宽度", 0.0, 2.0, 100.0, 2, "×"),
                    ("mix", "混合", 0.0, 1.0, 100.0, 0, ""),
                ],
            ),
            "sound_booster": (
                "声音放大器",
                [
                    ("gain_db", "增益", 0.0, 12.0, 10.0, 1, " dB"),
                    ("mix", "混合", 0.0, 1.0, 100.0, 0, ""),
                ],
            ),
        }
        panel = QGroupBox("音频效果（竖向调节）")
        panel_layout = QHBoxLayout(panel)
        for effect, (title, controls) in specs.items():
            effect_group = QGroupBox(title)
            effect_layout = QHBoxLayout(effect_group)
            enabled = QCheckBox("启用")
            enabled.toggled.connect(
                lambda checked, effect=effect: self._effect_enabled_changed(effect, checked)
            )
            effect_layout.addWidget(enabled)
            self.effect_enabled_checks[effect] = enabled
            self.effect_sliders[effect] = {}
            self.effect_labels[effect] = {}
            self.effect_scales[effect] = {}
            self.effect_decimals[effect] = {}
            self.effect_units[effect] = {}
            for key, label_text, minimum, maximum, scale, decimals, unit in controls:
                column = QWidget()
                column_layout = QVBoxLayout(column)
                column_layout.setContentsMargins(2, 2, 2, 2)
                column_layout.addWidget(QLabel(label_text))
                slider = QSlider(Qt.Orientation.Vertical)
                slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
                slider.setSingleStep(max(1, int(round(scale))))
                slider.setMinimumHeight(115)
                slider.setMaximumWidth(42)
                slider.setToolTip(f"{label_text}: {minimum:g} 到 {maximum:g}{unit}")

                def value_changed(
                    value: int,
                    effect_name: str = effect,
                    parameter: str = key,
                    scale_value: float = scale,
                    precision: int = decimals,
                    suffix: str = unit,
                ) -> None:
                    self._effect_value_changed(
                        effect_name,
                        parameter,
                        value / scale_value,
                        precision,
                        suffix,
                    )

                slider.valueChanged.connect(value_changed)
                column_layout.addWidget(slider)
                value_label = QLabel("0")
                value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                column_layout.addWidget(value_label)
                effect_layout.addWidget(column)
                self.effect_sliders[effect][key] = slider
                self.effect_labels[effect][key] = value_label
                self.effect_scales[effect][key] = scale
                self.effect_decimals[effect][key] = decimals
                self.effect_units[effect][key] = unit
            panel_layout.addWidget(effect_group)
        return panel

    def _populate_effects(self, preset: EqPreset) -> None:
        for effect, check in self.effect_enabled_checks.items():
            effect_settings: Any = getattr(preset.effects, effect)
            check.blockSignals(True)
            check.setChecked(bool(effect_settings.enabled))
            check.blockSignals(False)
            for key, slider in self.effect_sliders[effect].items():
                value = float(getattr(effect_settings, key))
                scale = self.effect_scales[effect][key]
                decimals = self.effect_decimals[effect][key]
                unit = self.effect_units[effect][key]
                slider.blockSignals(True)
                slider.setValue(int(round(value * scale)))
                slider.setEnabled(bool(effect_settings.enabled))
                slider.blockSignals(False)
                self.effect_labels[effect][key].setText(f"{value:.{decimals}f}{unit}")

    def _effect_enabled_changed(self, effect: str, enabled: bool) -> None:
        if self._loading:
            return
        preset = self._current_preset()
        if preset is None:
            return
        effect_settings: Any = getattr(preset.effects, effect)
        effect_settings.enabled = enabled
        for slider in self.effect_sliders[effect].values():
            slider.setEnabled(enabled)
        self._effect_changed(preset)

    def _effect_value_changed(self, effect: str, key: str, value: float, decimals: int, unit: str) -> None:
        if self._loading:
            return
        preset = self._current_preset()
        if preset is None:
            return
        effect_settings: Any = getattr(preset.effects, effect)
        setattr(effect_settings, key, float(value))
        self.effect_labels[effect][key].setText(f"{value:.{decimals}f}{unit}")
        self._effect_changed(preset)

    def _effect_changed(self, preset: EqPreset) -> None:
        if self.dsp is not None:
            try:
                self.dsp.set_preset(preset)
            except (RuntimeError, ValueError) as error:
                self.status_label.setText(f"监听效果更新失败：{error}")
        if not self.pipewire.active:
            return
        if self.system_bridge is not None:
            try:
                self.system_bridge.dsp.set_preset(preset)
            except (RuntimeError, ValueError) as error:
                self.status_label.setText(f"系统效果更新失败：{error}")
            return
        # 还没有桥接时防抖，避免拖动滑杆时反复重启 PipeWire
        self._effect_system_timer.start(250)

    def _schedule_system_eq_update(self) -> None:
        if self.system_bridge is not None:
            preset = self._current_preset()
            if preset is not None:
                self.system_bridge.dsp.set_preset(preset)
        elif self.pipewire.active:
            self._system_eq_update_timer.start(350)

    def _system_eq_update(self) -> None:
        preset = self._current_preset()
        if preset is None or not self.pipewire.active or self.system_bridge is not None:
            return
        try:
            self.pipewire.update(preset, self.system_sink_combo.currentData())
            self.system_meter.stop()
            self._start_system_meter()
        except (RuntimeError, OSError, ValueError) as error:
            self.status_label.setText(f"系统 EQ 更新失败：{error}")

    def _effect_system_update(self) -> None:
        preset = self._current_preset()
        if preset is None or not self.pipewire.active:
            return
        if self.system_bridge is not None:
            try:
                self.system_bridge.dsp.set_preset(preset)
            except (RuntimeError, ValueError) as error:
                self.status_label.setText(f"系统效果更新失败：{error}")
            return
        try:
            if preset.effects.any_enabled():
                self._switch_to_system_effect_bridge(preset)
                self.status_label.setText(f"系统输出已自动切换到：{preset.name}（效果桥接）")
            else:
                self.pipewire.update(preset, self.system_sink_combo.currentData())
        except (RuntimeError, OSError, ValueError) as error:
            self.status_label.setText(f"音频效果更新失败：{error}")

    def _physical_system_target(self) -> str | None:
        target = self.system_sink_combo.currentData() or self.pipewire.previous_sink
        if target in {None, "stereo_eq_input", "stereo_eq_post"}:
            target = next((sink.name for sink in self.pipewire.list_sinks()), None)
        return target

    def _start_system_effect_bridge(self, preset: EqPreset) -> None:
        if self.system_bridge is not None:
            self.system_bridge.stop()
        target = self._physical_system_target()
        if target is None:
            raise RuntimeError("没有找到可用的真实输出设备")
        bridge = SystemEffectBridge(
            DspEngine(preset, 48000, 2),
            self.pipewire.pre_monitor_source,
            target,
        )
        bridge.start()
        self.system_bridge = bridge
        self.system_meter.source_names = {"post": f"{target}.monitor"}
        self.system_meter.stop()
        self._start_system_meter()

    def _check_system_bridge(self) -> None:
        if self.system_bridge is None or not self.pipewire.active or self.system_bridge.running:
            return
        preset = self._current_preset()
        if preset is None:
            return
        self.system_bridge.stop()
        self.system_bridge = None
        try:
            self._start_system_effect_bridge(preset)
        except (RuntimeError, OSError, ValueError) as error:
            self.status_label.setText(f"系统效果桥接重连失败：{error}")

    def _switch_to_system_effect_bridge(self, preset: EqPreset) -> None:
        target = self._physical_system_target()
        if target is None:
            raise RuntimeError("没有找到可用的真实输出设备")
        if self.system_bridge is not None:
            self.system_bridge.stop()
            self.system_bridge = None
        # 已在纯 EQ 模式时只重启一次，直接 update 到桥接配置
        if self.pipewire.active and not self.pipewire.effect_bridge_mode:
            self.pipewire.update(preset, target)
        elif not self.pipewire.active:
            self.pipewire.activate(preset, target)
        self._start_system_effect_bridge(preset)

    def _create_meters(self) -> tuple[QProgressBar, QProgressBar, QProgressBar, QProgressBar, QProgressBar]:
        meters = []
        for _ in range(5):
            meter = QProgressBar()
            meter.setRange(0, 100)
            meter.setMaximumWidth(150)
            meter.setFormat("-inf dBFS")
            meters.append(meter)
        return meters[0], meters[1], meters[2], meters[3], meters[4]

    def _start_system_meter(self) -> None:
        try:
            self.system_meter.start()
        except RuntimeError as error:
            self.status_label.setText(str(error))

    def _update_system_controls(self) -> None:
        version = ".".join(str(value) for value in self.pipewire.version())
        if self.pipewire.available:
            self.status_label.setText("系统输出未接管；点击“启用系统输出”后才会生效")
            self.system_button.setText("启用系统输出")
        else:
            self.status_label.setText(f"系统输出不可用：当前 PipeWire {version}，需要 1.6+")
            self.system_button.setText("启用系统输出（当前不支持）")
        self.system_stop_button.setEnabled(True)

    @staticmethod
    def _meter_value(peak: float) -> tuple[int, str]:
        if peak <= 1.0e-6:
            return 0, "-inf dBFS"
        db = 20.0 * math.log10(max(0.0, peak))
        value = int(max(0, min(100, (db + 60.0) / 60.0 * 100.0)))
        return value, f"{db:.1f} dBFS"

    def _refresh_devices(self) -> None:
        try:
            inputs = list_input_devices()
            outputs = list_output_devices()
        except RuntimeError as error:
            self.status_label.setText(str(error))
            return
        self._fill_combo(self.input_combo, inputs, self.state.input_device_id)
        selected_output = self.state.monitor_output_device_id or self.state.output_device_id
        self._fill_combo(self.monitor_output_combo, outputs, selected_output)
        try:
            sinks = self.pipewire.list_sinks()
        except RuntimeError:
            sinks = []
        self.system_sink_combo.clear()
        self.system_sink_combo.addItem("跟随系统默认输出", None)
        for sink in sinks:
            self.system_sink_combo.addItem(sink.label(), sink.name)
        index = self.system_sink_combo.findData(self.state.pipewire_target_sink)
        if index >= 0:
            self.system_sink_combo.setCurrentIndex(index)

    def _fill_combo(self, combo: QComboBox, devices: list[AudioDevice], selected: int | None) -> None:
        combo.blockSignals(True)
        combo.clear()
        for device in devices:
            combo.addItem(device.label(), device.device_id)
        combo.blockSignals(False)
        if selected is not None:
            index = combo.findData(selected)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _refresh_presets(self) -> None:
        query = self.preset_search.text().strip().lower()
        self.preset_list.clear()
        for preset in self.store.presets:
            text = f"{preset.name} {preset.category} {preset.description}".lower()
            if query and query not in text:
                continue
            item = QListWidgetItem(f"{preset.category} · {preset.name}")
            item.setData(Qt.ItemDataRole.UserRole, preset.preset_id)
            item.setToolTip(preset.description)
            self.preset_list.addItem(item)
            if preset.preset_id == self._last_selected_id:
                self.preset_list.setCurrentItem(item)

    def _select_preset(self, preset_id: str) -> None:
        for index in range(self.preset_list.count()):
            item = self.preset_list.item(index)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == preset_id:
                self.preset_list.setCurrentItem(item)
                return
        if self.preset_list.count():
            self.preset_list.setCurrentRow(0)

    def _preset_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        preset = self.store.find(current.data(Qt.ItemDataRole.UserRole))
        if preset is None:
            return
        self._last_selected_id = preset.preset_id
        self.state.selected_preset_id = preset.preset_id
        self._loading = True
        self._populate_bands(preset)
        self._populate_effects(preset)
        self.graph.set_preset(preset, int(self.sample_rate_combo.currentText()))
        self._loading = False
        self._apply_preset(preset, apply_system=True)

    def _populate_bands(self, preset: EqPreset) -> None:
        self.band_table.setRowCount(len(preset.bands))
        for row, band in enumerate(preset.bands):
            enabled = QCheckBox()
            enabled.setChecked(band.enabled)
            enabled.stateChanged.connect(lambda _state, row=row: self._band_changed(row))
            self.band_table.setCellWidget(row, 0, enabled)
            type_combo = QComboBox()
            for filter_type in FilterType:
                type_combo.addItem(filter_type.value, filter_type.value)
            type_combo.setCurrentIndex(type_combo.findData(band.filter_type))
            type_combo.currentIndexChanged.connect(lambda _index, row=row: self._band_changed(row))
            self.band_table.setCellWidget(row, 1, type_combo)
            self._set_spin(row, 2, band.frequency, 20.0, 20000.0, 1.0)
            self._set_spin(row, 3, band.q, 0.1, 20.0, 0.1)
            self._set_spin(row, 4, band.left_gain(), -20.0, 20.0, 0.1)
            self._set_spin(row, 5, band.right_gain(), -20.0, 20.0, 0.1)
            delete_button = QPushButton("×")
            delete_button.clicked.connect(lambda _checked=False, row=row: self._delete_band(row))
            self.band_table.setCellWidget(row, 6, delete_button)
        self._populate_band_sliders(preset)

    def _set_spin(self, row: int, column: int, value: float, minimum: float, maximum: float, step: float) -> None:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(1 if step < 1 else 0)
        spin.setValue(value)
        spin.valueChanged.connect(lambda _value, row=row: self._band_changed(row))
        self.band_table.setCellWidget(row, column, spin)

    def _current_preset(self) -> EqPreset | None:
        return self.store.find(self._last_selected_id)

    def _band_changed(self, row: int) -> None:
        if self._loading:
            return
        preset = self._current_preset()
        if preset is None or row >= len(preset.bands):
            return
        band = preset.bands[row]
        enabled = cast(QCheckBox, self.band_table.cellWidget(row, 0))
        type_combo = cast(QComboBox, self.band_table.cellWidget(row, 1))
        frequency_spin = cast(QDoubleSpinBox, self.band_table.cellWidget(row, 2))
        q_spin = cast(QDoubleSpinBox, self.band_table.cellWidget(row, 3))
        left_gain = cast(QDoubleSpinBox, self.band_table.cellWidget(row, 4))
        right_gain = cast(QDoubleSpinBox, self.band_table.cellWidget(row, 5))
        band.enabled = enabled.isChecked()
        band.filter_type = str(type_combo.currentData())
        band.frequency = frequency_spin.value()
        band.q = q_spin.value()
        band.left_gain_db = left_gain.value()
        band.right_gain_db = right_gain.value()
        self._populate_band_sliders(preset)
        self.graph.set_preset(preset, int(self.sample_rate_combo.currentText()))
        self._apply_preset(preset)
        self._schedule_system_eq_update()

    def _add_band(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        preset.bands.append(EqBand(frequency=1000.0, q=1.0, gain_db=0.0))
        self._populate_bands(preset)
        self.graph.set_preset(preset, int(self.sample_rate_combo.currentText()))
        self._apply_preset(preset)
        self._schedule_system_eq_update()

    def _delete_band(self, row: int) -> None:
        preset = self._current_preset()
        if preset is None or len(preset.bands) <= 1:
            return
        del preset.bands[row]
        self._populate_bands(preset)
        self.graph.set_preset(preset, int(self.sample_rate_combo.currentText()))
        self._apply_preset(preset)
        self._schedule_system_eq_update()

    def _apply_preset(self, preset: EqPreset, apply_system: bool = False) -> None:
        try:
            if self.dsp is not None:
                self.dsp.set_preset(preset)
            if self.system_bridge is not None:
                self.system_bridge.dsp.set_preset(preset)
                if apply_system:
                    self.status_label.setText(f"系统输出已自动切换到：{preset.name}")
            elif apply_system and self.pipewire.active:
                if preset.effects.any_enabled():
                    self._switch_to_system_effect_bridge(preset)
                else:
                    self.pipewire.update(preset, self.system_sink_combo.currentData())
                    self.system_meter.stop()
                    self._start_system_meter()
                self.status_label.setText(f"系统输出已自动切换到：{preset.name}")
        except (RuntimeError, OSError, ValueError) as error:
            self.status_label.setText(str(error))

    def _start_monitor(self) -> None:
        if self.monitor is not None and self.monitor.running:
            return
        preset = self._current_preset()
        if preset is None:
            return
        sample_rate = int(self.sample_rate_combo.currentText())
        try:
            self.dsp = DspEngine(preset, sample_rate, 2)
            self.monitor = MicMonitor(
                self.dsp,
                self.input_combo.currentData(),
                self.monitor_output_combo.currentData(),
                sample_rate,
                int(self.block_size_combo.currentText()),
                self.monitor_check.isChecked(),
                self.monitor_gain.value(),
            )
            self.monitor.start()
        except (RuntimeError, ValueError, OSError) as error:
            self.monitor = None
            self.dsp = None
            QMessageBox.critical(self, "无法启动监听", str(error))
            return
        self.bypass_check.setChecked(False)
        self.dsp.set_bypass(False)
        self.status_label.setText("麦克风监听已启动")

    def _stop_monitor(self) -> None:
        if self.monitor is not None:
            self.monitor.stop()
        self.status_label.setText("麦克风监听已停止")

    def _bypass_changed(self) -> None:
        if self.dsp is not None:
            self.dsp.set_bypass(self.bypass_check.isChecked())

    def _monitor_changed(self) -> None:
        if self.monitor is not None:
            try:
                self.monitor.set_monitor_enabled(self.monitor_check.isChecked())
            except (RuntimeError, OSError) as error:
                self.status_label.setText(str(error))

    def _monitor_gain_changed(self, value: int) -> None:
        if self.monitor is not None:
            self.monitor.set_monitor_gain_db(value)

    def _enable_system_output(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        try:
            if self.pipewire.active:
                if self.system_bridge is not None:
                    self.system_bridge.dsp.set_preset(preset)
                elif preset.effects.any_enabled():
                    self._switch_to_system_effect_bridge(preset)
                else:
                    self.pipewire.update(preset, self.system_sink_combo.currentData())
            else:
                self.pipewire.activate(preset, self.system_sink_combo.currentData())
                if preset.effects.any_enabled():
                    self._start_system_effect_bridge(preset)
        except (RuntimeError, OSError, ValueError) as error:
            if self.pipewire.active and self.system_bridge is None:
                try:
                    self.pipewire.deactivate()
                except (RuntimeError, OSError):
                    pass
            QMessageBox.critical(self, "无法启用系统输出", str(error))
            return
        self.state.system_output_enabled = True
        self.system_stop_button.setEnabled(True)
        self._start_system_meter()
        self.status_label.setText("系统输出已启用，所有应用输出经过 Stereo EQ")

    def _disable_system_output(self) -> None:
        try:
            if self.system_bridge is not None:
                self.system_bridge.stop()
                self.system_bridge = None
            self.pipewire.deactivate()
        except (RuntimeError, OSError) as error:
            QMessageBox.critical(self, "无法停用系统输出", str(error))
            return
        self.state.system_output_enabled = False
        self.system_stop_button.setEnabled(False)
        self.system_meter.stop()
        self.status_label.setText("系统输出已停用")

    def _save_preset(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        name, accepted = QInputDialog.getText(self, "另存预设", "预设名称")
        if not accepted or not name.strip():
            return
        custom = preset.copy()
        custom.preset_id = f"custom-{len(self.store.presets)}-{name.strip()}"
        custom.name = name.strip()
        custom.built_in = False
        try:
            self.store.save(custom)
        except ValueError as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return
        self._refresh_presets()
        self._select_preset(custom.preset_id)

    def _import_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入预设", "", "JSON (*.json)")
        if not path:
            return
        try:
            preset = self.store.import_file(path)
        except (OSError, ValueError, TypeError) as error:
            QMessageBox.warning(self, "导入失败", str(error))
            return
        self._refresh_presets()
        self._select_preset(preset.preset_id)

    def _export_preset(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出预设", f"{preset.name}.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.store.export_file(preset, path)
        except OSError as error:
            QMessageBox.warning(self, "导出失败", str(error))

    def _update_status(self) -> None:
        if self.system_bridge is not None:
            if self.system_bridge.last_error:
                self.status_label.setText(f"系统效果警告: {self.system_bridge.last_error}")
            elif not self.system_bridge.running:
                self.status_label.setText("系统效果桥接已停止，正在重连")
            # 桥接模式只显示真实链路：前=桥输入，后=真实声卡 monitor
            # 不再回退到内部 processed_peak，避免有条没声的误导
            for meter, peak in (
                (self.system_input_meter, self.system_bridge.input_peak),
                (self.system_eq_meter, self.system_meter.post_peak),
            ):
                value, text = self._meter_value(peak)
                meter.setValue(value)
                meter.setFormat(text)
        elif self.system_meter.running:
            for meter, peak in (
                (self.system_input_meter, self.system_meter.pre_peak),
                (self.system_eq_meter, self.system_meter.post_peak),
            ):
                value, text = self._meter_value(peak)
                meter.setValue(value)
                meter.setFormat(text)
        else:
            for meter in (self.system_input_meter, self.system_eq_meter):
                meter.setValue(0)
                meter.setFormat("-inf dBFS")
        if self.monitor is not None and self.monitor.running:
            levels = (
                (self.input_meter, self.monitor.input_peak),
                (self.eq_meter, self.monitor.processed_peak),
                (self.output_meter, self.monitor.output_peak),
            )
            for meter, peak in levels:
                value, text = self._meter_value(peak)
                meter.setValue(value)
                meter.setFormat(text)
            if self.monitor.last_error:
                self.status_label.setText(f"监听警告: {self.monitor.last_error}")
        else:
            for meter in (self.input_meter, self.eq_meter, self.output_meter):
                meter.setValue(0)
                meter.setFormat("-inf dBFS")
            if not self.pipewire.active and self.system_meter.last_error == "":
                self.status_label.setText("点击“启动麦克风监听”查看输入、EQ 后和监听输出电平")

    def _save_state(self) -> None:
        self.state.input_device_id = self.input_combo.currentData()
        self.state.monitor_output_device_id = self.monitor_output_combo.currentData()
        self.state.output_device_id = self.state.monitor_output_device_id
        self.state.sample_rate = int(self.sample_rate_combo.currentText())
        self.state.block_size = int(self.block_size_combo.currentText())
        self.state.monitor_enabled = self.monitor_check.isChecked()
        self.state.monitor_gain_db = self.monitor_gain.value()
        self.state.pipewire_target_sink = self.system_sink_combo.currentData()
        save_state(self.state)

    def closeEvent(self, event) -> None:
        self._effect_system_timer.stop()
        self._system_eq_update_timer.stop()
        self._system_bridge_watchdog.stop()
        if self.monitor is not None:
            self.monitor.stop()
        if self.system_bridge is not None:
            self.system_bridge.stop()
            self.system_bridge = None
        if self.pipewire.active:
            try:
                self.pipewire.deactivate()
            except (RuntimeError, OSError):
                pass
        self.system_meter.stop()
        self._save_state()
        event.accept()
