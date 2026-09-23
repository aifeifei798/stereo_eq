from __future__ import annotations

from collections.abc import Iterable

from .models import EqBand, EqPreset

_BANDS = (60.0, 250.0, 1000.0, 3500.0, 10000.0)
_Q = (0.8, 0.9, 0.9, 0.8, 0.7)
_TYPES = ("low_shelf", "peaking", "peaking", "peaking", "high_shelf")


def _band(index: int, gain: float) -> EqBand:
    return EqBand(
        filter_type=_TYPES[index],
        frequency=_BANDS[index],
        q=_Q[index],
        gain_db=gain,
    )


def _preset(
    preset_id: str,
    name: str,
    category: str,
    description: str,
    preamp_db: float,
    gains: Iterable[float],
) -> EqPreset:
    return EqPreset(
        preset_id=preset_id,
        name=name,
        category=category,
        description=description,
        preamp_db=preamp_db,
        bands=[_band(index, gain) for index, gain in enumerate(gains)],
    )


_REFERENCE = [
    ("reference-flat", "平直", "完全平直的参考曲线", 0.0, (0, 0, 0, 0, 0)),
    ("reference-warm", "温暖", "轻微收窄高频，增加厚度", -1.0, (2, 1, 0, -1, -2)),
    ("reference-bright", "明亮", "提升中高频细节", -1.0, (-1, 0, 1, 2, 3)),
    ("reference-smooth", "柔和", "减少刺激感，适合长时间聆听", -1.0, (1, 1, 0, -1, -2)),
    ("reference-night", "夜间", "降低高音量下的尖锐感", -2.0, (2, 1, 0, -2, -4)),
    ("reference-low-volume", "低音量", "提高小音量下的可听度", -1.0, (3, 1, 1, 2, 2)),
    ("reference-focus", "清晰", "突出中频并保持低频克制", -1.0, (-1, 0, 2, 2, 0)),
    ("reference-wide", "宽声场", "增加空间感和高频延展", -1.0, (0, 0, 1, 2, 4)),
    ("reference-clean", "干净", "抑制浑浊，保持中性", -1.0, (-1, -1, 1, 1, 1)),
    ("reference-light", "轻度染色", "加入少量暖色和亮度", 0.0, (1, 1, 0, 1, 1)),
]

_ACOUSTIC = [
    ("acoustic-natural", "原声自然", "木吉他和人声的自然平衡", -1.0, (1, 0, 1, 2, 1)),
    ("acoustic-guitar", "木吉他", "突出拨弦和木吉他瞬态", -1.0, (2, 1, 1, 2, 1)),
    ("acoustic-vocal", "原声人声", "清晰的人声与自然伴奏", -1.0, (0, -1, 2, 2, 1)),
    ("acoustic-folk", "民谣", "温暖的民谣和轻木质感", -1.0, (2, 1, 0, 1, -1)),
    ("acoustic-piano", "钢琴", "改善钢琴的力度和延展", -1.0, (1, 0, 1, 1, 2)),
    ("acoustic-room", "房间感", "适合小房间播放原声", -1.0, (1, 1, 1, 1, 1)),
    ("acoustic-intimate", "近距离", "缩短听感距离，突出细节", -1.0, (-1, 0, 2, 2, 1)),
    ("acoustic-bright", "明亮原声", "适合弦乐和明亮录音", -1.0, (0, 0, 1, 2, 3)),
    ("acoustic-bass-guitar", "低音吉他", "增加贝斯线条的存在感", -1.0, (3, 2, 0, 1, 0)),
    ("acoustic-stage", "舞台原声", "模拟小型舞台的空间和力度", -1.0, (1, 1, 1, 2, 2)),
]

_JAZZ = [
    ("jazz-vocal", "爵士人声", "突出近距离人声和齿音细节", -1.0, (0, -1, 2, 2, 1)),
    ("jazz-brushes", "爵士鼓刷", "柔和鼓刷和细腻的节奏纹理", -1.0, (1, 1, 0, 1, 1)),
    ("jazz-piano", "爵士钢琴", "适合钢琴独奏和 Rhodes", -1.0, (1, 0, 1, 1, 1)),
    ("jazz-upright", "低音提琴", "增加贝斯线条的厚度", -1.0, (3, 1, 0, 0, 0)),
    ("jazz-guitar", "爵士吉他", "清晰的尼龙弦和拨弦细节", -1.0, (1, 0, 1, 2, 1)),
    ("jazz-sax", "萨克斯", "突出中频 sax 的圆润度", -1.0, (1, 1, 2, 2, 1)),
    ("jazz-horns", "铜管", "让铜管更有厚度和亮度", -1.0, (2, 1, 1, 2, 2)),
    ("jazz-club", "爵士俱乐部", "温暖、紧凑的俱乐部质感", -1.0, (2, 1, 0, 1, 0)),
    ("jazz-smooth", "柔和爵士", "减少刺激感，适合背景聆听", -1.0, (1, 1, 0, -1, -1)),
    ("jazz-late", "深夜爵士", "低音量下仍然保持人声清晰", -2.0, (2, 0, 1, 2, 1)),
]

_ROCK = [
    ("rock-balanced", "均衡摇滚", "平衡电吉他、贝斯和鼓", -1.0, (1, 0, 1, 1, 1)),
    ("rock-modern", "现代摇滚", "清晰、有冲击力的现代摇滚", -1.0, (1, 0, 1, 2, 2)),
    ("rock-classic", "经典摇滚", "复古、温暖和略带沙砾感", -1.0, (2, 1, 0, 1, -1)),
    ("rock-metal", "金属", "提升吉他冲击力和高频攻击", -2.0, (2, 0, 1, 3, 2)),
    ("rock-indie", "独立摇滚", "保留粗糙质感并增加人声清晰度", -1.0, (1, 0, 1, 2, 1)),
    ("rock-bass", "摇滚贝斯", "强调贝斯和低频线条", -1.0, (3, 1, 0, 1, 0)),
    ("rock-guitar", "电吉他", "突出双吉他和失真纹理", -1.0, (1, 0, 2, 2, 1)),
    ("rock-vocal", "摇滚人声", "让主唱穿透乐队但不刺耳", -1.0, (0, -1, 2, 2, 0)),
    ("rock-aggressive", "强劲摇滚", "更大胆的轮廓和攻击感", -2.0, (2, 0, 1, 3, 2)),
    ("rock-concert", "现场摇滚", "模拟小型现场的空间感", -1.0, (2, 1, 1, 2, 2)),
]

_ELECTRONIC = [
    ("electronic-club", "俱乐部", "适合舞曲的强劲低频和清晰节奏", -2.0, (4, 1, 0, 1, 1)),
    ("electronic-bass", "电子低频", "强化 sub bass 和 kick", -2.0, (5, 1, 0, 1, 0)),
    ("electronic-synth", "合成器", "突出 synth 的层次和亮度", -1.0, (0, 0, 1, 2, 3)),
    ("electronic-edm", "EDM", "饱满、低频强、适合舞曲现场", -2.0, (4, 1, 0, 2, 2)),
    ("electronic-techno", "Techno", "紧致的低频和持续的高频能量", -2.0, (4, 0, 0, 2, 2)),
    ("electronic-house", "House", "适合电子舞曲的人声和节奏", -1.0, (3, 1, 1, 2, 1)),
    ("electronic-trance", "Trance", "宽广的高频和富有层次的铺垫", -2.0, (3, 0, 1, 2, 4)),
    ("electronic-lofi", "Lo-fi", "温暖、柔和、略带复古感", 0.0, (2, 1, 0, -1, -3)),
    ("electronic-headphone", "电子耳机", "平衡电子乐的频宽和低频", -1.0, (2, 0, 1, 2, 2)),
    ("electronic-live", "电子现场", "适合现场电子音乐播放", -1.0, (3, 1, 1, 2, 2)),
]


_MOVIE = [
    ("movie-dialogue", "对白清晰", "突出电影对白和剧情对白的清晰度", -1.0, (0, 0, 3, 2, -1)),
    ("movie-action", "动作大片", "强化低频冲击、节奏和爆炸细节", -2.0, (4, 1, -1, 1, 2)),
    ("movie-scifi", "科幻空间", "增加科幻场景的宽度、金属感和高频细节", -1.0, (2, 1, 0, 2, 4)),
    ("movie-animation", "动画", "平衡动画对白、明亮音效和音乐", -1.0, (-1, 0, 1, 2, 2)),
    ("movie-comedy", "喜剧", "突出对白和轻快节奏，减少声音发闷", -1.0, (0, -1, 2, 1, 0)),
    ("movie-horror", "恐怖", "增加低频压迫感和环境氛围", -2.0, (4, 2, 0, -1, -2)),
    ("movie-suspense", "悬疑", "强化紧张氛围，同时保留对白可辨识度", -2.0, (3, 1, -1, 0, -1)),
    ("movie-war", "战争大片", "强化爆炸、枪声和大规模低频", -2.0, (4, 1, -1, 1, 1)),
    ("movie-family", "家庭观看", "温和均衡，适合长时间家庭观影", -1.0, (0, 0, 1, 1, 0)),
    ("movie-documentary", "纪录片", "突出旁白、采访和现场环境声", -1.0, (0, -1, 3, 2, 1)),
]


def default_presets() -> list[EqPreset]:
    presets: list[EqPreset] = []
    for group, category in (
        (_REFERENCE, "参考"),
        (_ACOUSTIC, "原声"),
        (_JAZZ, "爵士"),
        (_ROCK, "摇滚"),
        (_ELECTRONIC, "电子"),
        (_MOVIE, "电影"),
    ):
        for preset_id, name, description, preamp, gains in group:
            presets.append(_preset(preset_id, name, category, description, preamp, gains))
    return presets
