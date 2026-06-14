"""Đọc/ghi phụ đề SRT. Không phụ thuộc thư viện ngoài."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
_BLOCK_SEP = re.compile(r"\n\s*\n")


@dataclass
class SrtCue:
    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def parse_timecode(tc: str) -> int:
    m = _TIME_RE.search(tc)
    if not m:
        raise ValueError(f"Timecode không hợp lệ: {tc!r}")
    h, mm, ss, ms = m.groups()
    ms = (ms + "000")[:3]  # chuẩn hoá về mili-giây
    return ((int(h) * 60 + int(mm)) * 60 + int(ss)) * 1000 + int(ms)


def format_timecode(ms: int) -> str:
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse(path: str | Path) -> list[SrtCue]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    cues: list[SrtCue] = []
    for block in _BLOCK_SEP.split(raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # Dòng đầu có thể là số thứ tự (tuỳ chọn).
        idx_line = 0
        if lines[0].strip().isdigit() and "-->" in lines[1]:
            index = int(lines[0].strip())
            idx_line = 1
        else:
            index = len(cues) + 1
        if "-->" not in lines[idx_line]:
            continue
        start_s, _, end_s = lines[idx_line].partition("-->")
        text = "\n".join(lines[idx_line + 1:]).strip()
        try:
            start_ms = parse_timecode(start_s)
            end_ms = parse_timecode(end_s)
        except ValueError:
            continue
        cues.append(SrtCue(index, start_ms, end_ms, text))
    return cues


def write(path: str | Path, cues: list[SrtCue]) -> None:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(
            f"{i}\n{format_timecode(c.start_ms)} --> {format_timecode(c.end_ms)}\n{c.text}\n"
        )
    Path(path).write_text("\n".join(out), encoding="utf-8")
