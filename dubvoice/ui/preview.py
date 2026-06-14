"""Nghe thử / tạo lại giọng cho một block (không chặn UI)."""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QThread, Signal

from .. import ffmpeg
from ..text import clean as clean_text
from ..tts import TtsEngine, TtsError
from ..voices import VoiceConfig

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class PreviewWorker(QThread):
    """Sinh (hoặc tạo lại) giọng 1 block rồi phát bằng ffplay."""
    ready = Signal(str)    # đường dẫn file đã sinh
    failed = Signal(str)

    def __init__(self, text: str, cfg: VoiceConfig, locale: str, *, regenerate: bool):
        super().__init__()
        self.text = text
        self.cfg = cfg
        self.locale = locale
        self.regenerate = regenerate

    def run(self) -> None:
        txt = clean_text(self.text, locale=self.locale)
        if not txt:
            self.failed.emit("Text rỗng sau khi làm sạch")
            return
        try:
            engine = TtsEngine()
            path = engine.synth(txt, self.cfg, use_cache=not self.regenerate)
            self.ready.emit(str(path))
        except TtsError as e:
            self.failed.emit(str(e))


class PreviewPlayer:
    """Quản lý phát ffplay — chỉ một luồng phát tại một thời điểm."""
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._worker: PreviewWorker | None = None

    def play(self, text, cfg, locale, *, regenerate=False,
             on_error=None, on_state=None) -> None:
        self.stop()
        if on_state:
            on_state("Đang tạo giọng…")
        self._worker = PreviewWorker(text, cfg, locale, regenerate=regenerate)
        self._worker.ready.connect(lambda p: self._on_ready(p, on_state))
        if on_error:
            self._worker.failed.connect(on_error)
        self._worker.start()

    def _on_ready(self, path: str, on_state):
        if on_state:
            on_state("")
        try:
            self._proc = subprocess.Popen(
                [ffmpeg.ffplay_path(), "-nodisp", "-autoexit",
                 "-loglevel", "quiet", path],
                creationflags=_CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            pass  # không có ffplay → bỏ qua phát, file vẫn đã sinh

    def play_source(
        self,
        media_path: str,
        *,
        start_ms: int,
        end_ms: int,
        on_error=None,
        on_state=None,
    ) -> None:
        self.stop()
        duration_s = max(0.1, (end_ms - start_ms) / 1000)
        start_s = max(0.0, start_ms / 1000)
        if on_state:
            on_state("Đang phát tiếng gốc…")
        try:
            self._proc = subprocess.Popen(
                [
                    ffmpeg.ffplay_path(),
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-ss",
                    f"{start_s:.3f}",
                    "-t",
                    f"{duration_s:.3f}",
                    media_path,
                ],
                creationflags=_CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            if on_error:
                on_error("Không tìm thấy ffplay để phát tiếng gốc.")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
