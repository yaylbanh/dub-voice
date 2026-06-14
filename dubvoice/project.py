"""Mô hình Project / Block và lưu .dubproj.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .srt import SrtCue, parse as parse_srt
from .voices import VoiceConfig

PROJECT_EXT = ".dubproj.json"


@dataclass
class Block:
    index: int
    start_ms: int
    end_ms: int
    text: str
    voice_label: str = ""    # tham chiếu tới VoiceConfig.label; "" = chưa gán
    enabled: bool = True     # False = bỏ qua (vd dòng nhạc nền "...")

    @property
    def slot_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @classmethod
    def from_cue(cls, cue: SrtCue) -> "Block":
        text = cue.text.strip()
        # Tự tắt các dòng chỉ chứa dấu chấm/khoảng trắng.
        enabled = bool(text) and text.strip(". \t") != ""
        return cls(cue.index, cue.start_ms, cue.end_ms, text, "", enabled)


@dataclass
class Project:
    name: str = "Untitled"
    srt_path: str = ""
    video_path: str = ""
    locale: str = "vi-VN"
    blocks: list[Block] = field(default_factory=list)
    voices: list[VoiceConfig] = field(default_factory=list)
    default_voice: str = ""        # label dùng cho block chưa gán
    keep_original_audio: bool = True
    original_volume: float = 0.12  # âm lượng audio gốc khi giữ làm nền
    max_tempo: float = 1.5

    # ---- tạo / nạp ----
    @classmethod
    def from_srt(cls, srt_path: str | Path, **kw) -> "Project":
        cues = parse_srt(srt_path)
        blocks = [Block.from_cue(c) for c in cues]
        name = Path(srt_path).stem
        voices = _default_voice_set()
        proj = cls(
            name=name, srt_path=str(srt_path), blocks=blocks,
            voices=voices, default_voice=voices[0].label, **kw,
        )
        return proj

    def voice_map(self) -> dict[str, VoiceConfig]:
        return {v.label: v for v in self.voices}

    def has_explicit_voice(self, block: Block) -> bool:
        return bool(block.voice_label and block.voice_label in self.voice_map())

    def resolve_voice(self, block: Block) -> VoiceConfig | None:
        vm = self.voice_map()
        if block.voice_label and block.voice_label in vm:
            return vm[block.voice_label]
        if self.default_voice in vm:
            return vm[self.default_voice]
        return self.voices[0] if self.voices else None

    # ---- thống kê ----
    def stats(self) -> dict:
        active = [b for b in self.blocks if b.enabled]
        unassigned = sum(1 for b in active if not b.voice_label)
        return {
            "total": len(self.blocks),
            "active": len(active),
            "unassigned": unassigned,
        }

    # ---- lưu / mở ----
    def save(self, path: str | Path) -> None:
        data = asdict(self)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["blocks"] = [Block(**b) for b in data.get("blocks", [])]
        data["voices"] = [VoiceConfig(**v) for v in data.get("voices", [])]
        return cls(**data)


def _default_voice_set() -> list[VoiceConfig]:
    """Bộ giọng mặc định: nam/nữ chính + phụ, phân biệt bằng pitch."""
    return [
        VoiceConfig("Nam chính", "vi-VN-NamMinhNeural", 0, 0, 0, "#2563eb"),
        VoiceConfig("Nữ chính", "vi-VN-HoaiMyNeural", 0, 0, 0, "#7c3aed"),
        VoiceConfig("Nam phụ", "vi-VN-NamMinhNeural", 0, -8, 0, "#dc2626"),
        VoiceConfig("Nữ phụ", "vi-VN-HoaiMyNeural", 0, 10, 0, "#16a34a"),
    ]
