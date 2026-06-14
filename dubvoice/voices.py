"""Danh mục giọng Edge TTS (đa ngôn ngữ) + cấu hình giọng theo nhân vật.

Toàn bộ ~322 giọng / 142 locale được lấy động từ Edge và cache ra JSON.
Nếu offline, dùng danh sách rút gọn các locale phổ biến cho review phim.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_CACHE = Path(__file__).resolve().parent / "_voice_catalog.json"
_CACHE_TTL = 14 * 24 * 3600  # 14 ngày

# Locale hay dùng cho kênh review phim — hiện lên đầu danh sách.
PRIORITY_LOCALES = [
    "vi-VN", "zh-CN", "zh-TW", "en-US", "en-GB",
    "ko-KR", "ja-JP", "th-TH", "es-ES", "es-MX",
]

# Fallback tối thiểu khi không gọi được mạng.
_FALLBACK = [
    {"short_name": "vi-VN-HoaiMyNeural", "locale": "vi-VN", "gender": "Female", "friendly": "Hoài My"},
    {"short_name": "vi-VN-NamMinhNeural", "locale": "vi-VN", "gender": "Male", "friendly": "Nam Minh"},
    {"short_name": "zh-CN-XiaoxiaoNeural", "locale": "zh-CN", "gender": "Female", "friendly": "Xiaoxiao"},
    {"short_name": "zh-CN-YunxiNeural", "locale": "zh-CN", "gender": "Male", "friendly": "Yunxi"},
    {"short_name": "en-US-AriaNeural", "locale": "en-US", "gender": "Female", "friendly": "Aria"},
    {"short_name": "en-US-GuyNeural", "locale": "en-US", "gender": "Male", "friendly": "Guy"},
]


@dataclass
class Voice:
    short_name: str          # vd 'vi-VN-NamMinhNeural' — id thật gửi cho Edge
    locale: str              # vd 'vi-VN'
    gender: str              # Male / Female
    friendly: str            # tên ngắn hiển thị


@dataclass
class VoiceConfig:
    """Cấu hình một 'nhân vật' — đa giọng phân biệt bằng pitch/rate."""
    label: str                       # tên nhân vật, vd 'Nam chính'
    voice: str = "vi-VN-NamMinhNeural"  # short_name của giọng Edge
    rate_pct: int = 0                # tốc độ nền -50..+100 (%)
    pitch_hz: int = 0                # cao độ -50..+50 (Hz) để phân biệt nhân vật
    volume_pct: int = 0              # âm lượng -50..+50 (%)
    color: str = "#2563eb"           # màu chấm hiển thị trong UI

    def edge_rate(self) -> str:
        return f"{'+' if self.rate_pct >= 0 else ''}{self.rate_pct}%"

    def edge_pitch(self) -> str:
        return f"{'+' if self.pitch_hz >= 0 else ''}{self.pitch_hz}Hz"

    def edge_volume(self) -> str:
        return f"{'+' if self.volume_pct >= 0 else ''}{self.volume_pct}%"


def _load_cache() -> list[Voice] | None:
    if not _CACHE.exists():
        return None
    try:
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        if time.time() - data.get("fetched_at", 0) > _CACHE_TTL:
            return None
        return [Voice(**v) for v in data["voices"]]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _save_cache(voices: list[Voice]) -> None:
    try:
        _CACHE.write_text(
            json.dumps(
                {"fetched_at": time.time(), "voices": [asdict(v) for v in voices]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


async def _fetch_async() -> list[Voice]:
    import edge_tts

    raw = await edge_tts.list_voices()
    voices = []
    for v in raw:
        short = v["ShortName"]
        # friendly = phần tên giữa locale và 'Neural'
        friendly = short.split("-")[-1].replace("Neural", "").replace("Multilingual", " ML")
        voices.append(Voice(short, v["Locale"], v.get("Gender", ""), friendly))
    return voices


def all_voices(*, force_refresh: bool = False) -> list[Voice]:
    """Lấy toàn bộ giọng. Dùng cache; tự fetch khi cần."""
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached
    try:
        voices = asyncio.run(_fetch_async())
        if voices:
            _save_cache(voices)
            return voices
    except Exception:  # offline / lỗi mạng → fallback
        pass
    return [Voice(**v) for v in _FALLBACK]


def locales(voices: list[Voice] | None = None) -> list[str]:
    """Danh sách locale, locale phổ biến lên đầu."""
    voices = voices or all_voices()
    present = sorted({v.locale for v in voices})
    head = [loc for loc in PRIORITY_LOCALES if loc in present]
    tail = [loc for loc in present if loc not in PRIORITY_LOCALES]
    return head + tail


def by_locale(locale: str, voices: list[Voice] | None = None) -> list[Voice]:
    voices = voices or all_voices()
    return [v for v in voices if v.locale == locale]
