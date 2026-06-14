"""Định vị và bọc ffmpeg/ffprobe.

Toàn bộ xử lý audio (đổi tốc độ, ghép, mux video) dùng ffmpeg trực tiếp —
không phụ thuộc pydub/numpy, scale tốt với hàng nghìn block.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# Các vị trí có thể chứa ffmpeg đi kèm: ./ffmpeg_bin trong repo, hoặc
# ffmpeg_bin của tool kế bên (vd ../review-drama/ffmpeg_bin).
_REPO = Path(__file__).resolve().parents[1]
_BUNDLED_DIRS = [
    _REPO / "ffmpeg_bin",
    _REPO.parent / "review-drama" / "ffmpeg_bin",
]
# Có thể trỏ tay qua biến môi trường DUBVOICE_FFMPEG_DIR.
if os.environ.get("DUBVOICE_FFMPEG_DIR"):
    _BUNDLED_DIRS.insert(0, Path(os.environ["DUBVOICE_FFMPEG_DIR"]))

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@lru_cache(maxsize=4)
def _resolve(name: str) -> str:
    """Trả về đường dẫn tới ffmpeg/ffprobe: ưu tiên bundled, sau đó PATH."""
    exe = f"{name}.exe" if os.name == "nt" else name
    for d in _BUNDLED_DIRS:
        cand = d / exe
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Không tìm thấy {name}. Hãy cài ffmpeg và thêm vào PATH, "
        f"hoặc đặt ffmpeg_bin/ cạnh thư mục dự án."
    )


def ffmpeg_path() -> str:
    return _resolve("ffmpeg")


def ffprobe_path() -> str:
    return _resolve("ffprobe")


def ffplay_path() -> str:
    return _resolve("ffplay")


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Chạy ffmpeg với danh sách tham số (đã bỏ tên lệnh đầu)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi:\n{proc.stderr.strip()}")
    return proc


def probe_duration_ms(path: str | Path) -> int:
    """Lấy thời lượng file audio/video theo mili-giây."""
    cmd = [
        ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW
    )
    if proc.returncode != 0:
        return 0
    try:
        dur = float(json.loads(proc.stdout)["format"]["duration"])
        return int(round(dur * 1000))
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0
