"""Sinh audio qua Edge TTS, có cache theo nội dung.

Cache key = hash(text + voice + rate + pitch + volume) → không sinh lại
block không đổi giữa các lần render (tiết kiệm thời gian & băng thông).
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

from .voices import VoiceConfig

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "tts"


class TtsError(RuntimeError):
    pass


def cache_key(text: str, cfg: VoiceConfig) -> str:
    payload = "|".join(
        [text, cfg.voice, cfg.edge_rate(), cfg.edge_pitch(), cfg.edge_volume()]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


async def _synth_async(text: str, cfg: VoiceConfig, out_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        voice=cfg.voice,
        rate=cfg.edge_rate(),
        pitch=cfg.edge_pitch(),
        volume=cfg.edge_volume(),
    )
    await communicate.save(str(out_path))


class TtsEngine:
    _path_locks: dict[str, threading.Lock] = {}
    _path_locks_guard = threading.Lock()

    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, text: str, cfg: VoiceConfig) -> Path:
        return self.cache_dir / f"{cache_key(text, cfg)}.mp3"

    def _lock_for(self, out: Path) -> threading.Lock:
        key = str(out.resolve())
        with self._path_locks_guard:
            lock = self._path_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._path_locks[key] = lock
            return lock

    def synth(self, text: str, cfg: VoiceConfig, *, use_cache: bool = True) -> Path:
        """Trả về đường dẫn file mp3 (cache nếu đã có). Raise TtsError nếu lỗi."""
        if not text.strip():
            raise TtsError("Text rỗng")
        out = self.path_for(text, cfg)
        lock = self._lock_for(out)
        with lock:
            if use_cache and out.exists() and out.stat().st_size > 0:
                return out
            try:
                asyncio.run(_synth_async(text, cfg, out))
            except Exception as e:  # noqa: BLE001 — gom mọi lỗi mạng/Edge
                out.unlink(missing_ok=True)
                raise TtsError(f"Edge TTS lỗi: {e}") from e
            if not out.exists() or out.stat().st_size == 0:
                raise TtsError("Edge TTS không trả về audio (text có thể chứa ký tự lạ)")
            return out
