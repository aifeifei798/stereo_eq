# Stereo EQ

面向 Linux Mint 的实时立体声均衡器，提供 PyQt6 图形界面、麦克风监听 EQ、PipeWire 系统输出 EQ 和 60 个内置预设。

## 功能

- PyQt6 桌面界面
- 麦克风输入实时 EQ 和耳机/虚拟设备监听
- Linux Mint PipeWire 系统输出 EQ
- 60 个内置预设：
  - 参考：10 个
  - 原声：10 个
  - 爵士：10 个
  - 摇滚：10 个
  - 电子：10 个
  - 电影：10 个
- 频段参数编辑：启用、滤波器类型、频率、Q 值、左右声道增益
- 输入、EQ 后、监听输出、系统 EQ 前、系统 EQ 后电平表
- 预设搜索、导入、导出、另存为自定义预设
- 自动恢复上次设备、采样率、监听增益和预设
- PipeWire 启用失败时自动恢复原默认声卡

电影预设包括：对白清晰、动作大片、科幻空间、动画、喜剧、恐怖、悬疑、战争大片、家庭观看、纪录片。

## 环境要求

- Linux Mint 22.x / Ubuntu 24.04 系列
- Python 3.11 或更高版本
- `uv`
- PipeWire、WirePlumber、`pactl`、`wpctl`
- `parec`，用于显示系统 EQ 前后电平，通常由 `pulseaudio-utils` 提供

检查系统音频环境：

```bash
pactl info
wpctl status
systemctl --user status pipewire wireplumber
```

## 安装

在项目目录执行：

```bash
uv sync
```

`uv sync` 会创建项目自己的 `.venv`，不会修改系统 Python。依赖包括：

- PyQt6
- NumPy
- SciPy
- sounddevice
- pytest、ruff、mypy（开发依赖）

如果系统缺少 `parec`：

```bash
sudo apt install pulseaudio-utils
```

## 运行

推荐使用项目环境运行：

```bash
uv run python stereo_eq.py
```

也可以使用安装后的命令：

```bash
uv run stereo-eq
```

## 使用方式

### 麦克风监听

1. 在顶部选择麦克风、监听输出、采样率和块大小。
2. 勾选“开启监听”。
3. 点击“启动麦克风监听”。
4. 观察“输入”“EQ 后”“监听输出”三条电平表。

监听默认关闭，启用监听前请确认输出设备是耳机或合适的虚拟设备，避免扬声器反馈。

### 系统输出 EQ

1. 选择“系统目标”物理输出设备，或者保持“跟随系统默认输出”。
2. 点击“启用系统输出”。
3. 系统默认输出会切换到 `stereo_eq_input`。
4. EQ 经过后由 `stereo_eq_post` 输出到真实声卡。
5. 观察“系统 EQ 前”和“系统 EQ 后”电平表。

启动程序不会自动接管系统输出。第一次需要点击“启用系统输出”；启用后，点击左侧预设会自动更新系统 EQ，不需要再次点击启用按钮。

系统级预设更新会重启用户级 PipeWire/WirePlumber 服务，切换期间可能有一次短暂的声音中断。停用系统输出或启用失败时，程序会删除配置、恢复原默认声卡并重启音频服务。

### 自定义预设

- 点击“另存”创建自定义预设
- 点击“导出”保存 JSON 预设文件
- 点击“导入”加载 JSON 预设文件
- 内置预设不会被覆盖

配置目录：

```text
~/.config/stereo-eq/
```

其中包含界面状态和自定义预设。

## PipeWire 兼容实现

项目适配 Linux Mint 22.3 当前使用的 PipeWire 1.0.5：

- EQ 使用 `libpipewire-module-filter-chain`
- 滤波器使用 `bq_peaking`、`bq_lowshelf`、`bq_highshelf` 等内置 Biquad
- 后级虚拟 Sink 使用 `libpipewire-module-loopback`
- 默认设备切换使用 `wpctl set-default`
- 系统前后级电平分别读取：
  - `stereo_eq_input.monitor`：系统 EQ 前
  - `stereo_eq_post.monitor`：系统 EQ 后

生成的用户配置：

```text
~/.config/pipewire/pipewire.conf.d/99-stereo-eq.conf
```

点击“停用系统输出”会删除这个配置。

## 故障恢复

如果系统输出没有声音，先在界面点击“停用系统输出”。如果界面无法使用，可以在终端执行：

```bash
rm -f ~/.config/pipewire/pipewire.conf.d/99-stereo-eq.conf
systemctl --user restart pipewire wireplumber
```

然后检查真实声卡：

```bash
pactl list short sinks
pactl info
```

如果没有系统输出电平表，确认已经启用系统输出，并检查：

```bash
command -v parec
pactl list short sources
```

正常启用系统 EQ 后，应该能看到类似：

```text
stereo_eq_input.monitor
stereo_eq_post.monitor
```

## 开发检查

```bash
uv run pytest
uv run ruff check .
uv run mypy stereo_eq_app
uv build
```

## 项目结构

```text
stereo_eq_app/
├── audio.py       麦克风监听和系统输出电平采集
├── config.py      状态与自定义预设持久化
├── dsp.py         Biquad DSP、预设切换和限幅
├── models.py      频段、预设和状态模型
├── pipewire.py    PipeWire filter-chain/loopback 控制
├── presets.py     60 个内置预设
└── ui.py          PyQt6 界面

tests/              DSP、预设和项目配置测试
```

## 许可证

Apache License 2.0，详见 `LICENSE`。
