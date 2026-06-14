"""Logic khớp thời lượng (auto time-fit).

Mỗi block có khoảng thời gian (slot) theo SRT. Giọng TTS sinh ra có thể dài/ngắn
hơn slot. Ta tăng tốc giọng (atempo) trong giới hạn an toàn để khớp; phần vẫn
tràn thì để chồng sang block sau (tự nhiên trong hội thoại nhanh).
"""
from __future__ import annotations

from dataclasses import dataclass

# Giới hạn tăng tốc để giọng không "réo" như robot.
MIN_TEMPO = 1.0
MAX_TEMPO = 1.5
# Ngưỡng coi là "lệch nặng" để UI cảnh báo (mili-giây).
HEAVY_DRIFT_MS = 1000


@dataclass
class FitResult:
    tempo: float          # hệ số atempo áp lên giọng (>=1.0)
    fitted_ms: int        # thời lượng sau khi tăng tốc
    slot_ms: int          # thời lượng slot theo SRT
    overflow_ms: int      # phần tràn ra sau slot (0 nếu vừa/ngắn)

    @property
    def drift_ms(self) -> int:
        """Lệch so với slot: dương = giọng dài hơn slot, âm = ngắn hơn."""
        return self.fitted_ms - self.slot_ms

    @property
    def is_heavy(self) -> bool:
        return abs(self.drift_ms) >= HEAVY_DRIFT_MS

    @property
    def status(self) -> str:
        d = self.drift_ms
        if abs(d) <= 200:
            return "ok"
        return "tight" if d > 0 else "loose"


def compute(natural_ms: int, slot_ms: int, *, max_tempo: float = MAX_TEMPO) -> FitResult:
    """Tính fit cho một block.

    natural_ms : thời lượng giọng TTS gốc (tempo 1.0)
    slot_ms    : thời lượng slot SRT
    """
    slot_ms = max(1, slot_ms)
    if natural_ms <= slot_ms:
        # Giọng đã vừa hoặc ngắn hơn — không tăng tốc.
        return FitResult(MIN_TEMPO, natural_ms, slot_ms, 0)

    needed = natural_ms / slot_ms
    tempo = min(max_tempo, needed)
    tempo = max(MIN_TEMPO, round(tempo, 3))
    fitted = int(round(natural_ms / tempo))
    overflow = max(0, fitted - slot_ms)
    return FitResult(tempo, fitted, slot_ms, overflow)
