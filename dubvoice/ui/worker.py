"""Worker chạy render trong thread riêng để UI không treo."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..assemble import export_voice_segments, run_full
from ..project import Project
from ..tts import TtsEngine


class RenderWorker(QThread):
    progress = Signal(int, int, str)   # done, total, message
    finished_ok = Signal(str, int, int)  # out_path, n_errors, n_heavy
    failed = Signal(str)

    def __init__(self, project: Project, out_path: str, *, mode: str = "final"):
        super().__init__()
        self.project = project
        self.out_path = out_path
        self.mode = mode
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            runner = export_voice_segments if self.mode == "segments" else run_full
            _, renders = runner(
                self.project,
                Path(self.out_path),
                engine=TtsEngine(),
                progress=lambda d, t, m: self.progress.emit(d, t, m),
                should_stop=lambda: self._stop,
            )
            errs = sum(1 for r in renders if r.error)
            heavy = sum(1 for r in renders if r.fit and r.fit.is_heavy)
            self.finished_ok.emit(self.out_path, errs, heavy)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
