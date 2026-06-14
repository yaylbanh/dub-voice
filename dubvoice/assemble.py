"""Dựng track audio tổng từ các block và ghép vào video bằng ffmpeg.

Chiến lược (scale tới hàng nghìn block, không cần pydub/numpy):
  1. Sinh giọng từng block (Edge TTS, có cache) → đo thời lượng → tính time-fit.
  2. Chuyển mỗi block sang wav chuẩn (44.1k stereo) + áp atempo nếu cần.
  3. Ghép tuần tự theo mốc start SRT, chèn khoảng lặng giữa các block
     (concat demuxer). Block tràn sẽ đẩy block sau trễ lại tới khi gặp khoảng
     trống — tự khớp lại, đúng cảm giác hội thoại nhanh.
  4. Mux vào video: giữ tiếng gốc làm nền (tuỳ chọn) hoặc thay hoàn toàn.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .fit import FitResult, compute as compute_fit
from .project import Block, Project
from .text import clean as clean_text
from .tts import TtsEngine, TtsError

SAMPLE_RATE = 44100
CHANNELS = 2
ProgressFn = Callable[[int, int, str], None]  # done, total, message


@dataclass
class BlockRender:
    block: Block
    wav_path: Path | None
    fit: FitResult | None
    error: str | None = None


def _to_fitted_wav(src_mp3: Path, tempo: float, dst_wav: Path) -> None:
    """Chuyển mp3 → wav chuẩn, áp atempo nếu tempo > 1."""
    af = []
    if tempo > 1.001:
        af = ["-filter:a", f"atempo={tempo:.4f}"]
    ffmpeg.run([
        "-i", str(src_mp3), *af,
        "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le", str(dst_wav),
    ])


def _silence_wav(duration_ms: int, dst_wav: Path) -> None:
    ffmpeg.run([
        "-f", "lavfi", "-i",
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
        "-t", f"{duration_ms / 1000:.3f}",
        "-c:a", "pcm_s16le", str(dst_wav),
    ])


def render_blocks(
    project: Project,
    engine: TtsEngine,
    *,
    work_dir: Path,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[BlockRender]:
    """Sinh giọng + tính fit cho mọi block đang bật. Trả danh sách BlockRender."""
    active = [b for b in project.blocks if b.enabled and b.text.strip()]
    total = len(active)
    results: list[BlockRender] = []
    for i, block in enumerate(active, 1):
        if should_stop and should_stop():
            break
        cfg = project.resolve_voice(block)
        if cfg is None:
            results.append(BlockRender(block, None, None, "Chưa cấu hình giọng"))
            continue
        txt = clean_text(block.text, locale=project.locale)
        if not txt:
            results.append(BlockRender(block, None, None, "Text rỗng sau khi làm sạch"))
            continue
        try:
            mp3 = engine.synth(txt, cfg)
            natural = ffmpeg.probe_duration_ms(mp3)
            fit = compute_fit(natural, block.slot_ms, max_tempo=project.max_tempo)
            wav = work_dir / f"blk_{block.index:06d}.wav"
            _to_fitted_wav(mp3, fit.tempo, wav)
            results.append(BlockRender(block, wav, fit))
        except (TtsError, RuntimeError) as e:
            results.append(BlockRender(block, None, None, str(e)))
        if progress:
            progress(i, total, f"Block #{block.index}")
    return results


def assemble_audio(
    renders: list[BlockRender],
    out_wav: Path,
    *,
    work_dir: Path,
    tail_ms: int = 500,
) -> Path:
    """Ghép các block (đã có wav) thành một track audio tổng theo mốc SRT."""
    ok = [r for r in renders if r.wav_path and r.fit]
    if not ok:
        raise RuntimeError("Không có block nào render thành công để ghép.")
    ok.sort(key=lambda r: r.block.start_ms)

    concat_items: list[Path] = []
    cursor = 0
    sil_idx = 0
    for r in ok:
        start = r.block.start_ms
        if start > cursor:
            sil = work_dir / f"sil_{sil_idx:06d}.wav"
            _silence_wav(start - cursor, sil)
            concat_items.append(sil)
            sil_idx += 1
            cursor = start
        concat_items.append(r.wav_path)  # type: ignore[arg-type]
        cursor += r.fit.fitted_ms  # type: ignore[union-attr]

    if tail_ms > 0:
        tail = work_dir / "sil_tail.wav"
        _silence_wav(tail_ms, tail)
        concat_items.append(tail)

    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in concat_items), encoding="utf-8"
    )
    ffmpeg.run([
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:a", "pcm_s16le", str(out_wav),
    ])
    return out_wav


def mux(
    project: Project,
    dub_wav: Path,
    out_path: Path,
) -> Path:
    """Ghép track lồng tiếng vào video (hoặc xuất audio nếu không có video)."""
    if not project.video_path or not Path(project.video_path).exists():
        # Không có video → xuất luôn file audio.
        if out_path.suffix.lower() == ".wav":
            shutil.copyfile(dub_wav, out_path)
        else:
            ffmpeg.run(["-i", str(dub_wav), "-b:a", "192k", str(out_path)])
        return out_path

    video = project.video_path
    has_audio = ffmpeg.probe_duration_ms(dub_wav) > 0
    if project.keep_original_audio and _video_has_audio(video):
        vol = max(0.0, min(1.0, project.original_volume))
        ffmpeg.run([
            "-i", video, "-i", str(dub_wav),
            "-filter_complex",
            f"[0:a]volume={vol:.3f}[bg];[1:a]volume=1.0[dub];"
            f"[bg][dub]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ])
    else:
        ffmpeg.run([
            "-i", video, "-i", str(dub_wav),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(out_path),
        ])
    return out_path


def _video_has_audio(video: str) -> bool:
    import subprocess
    cmd = [
        ffmpeg.ffprobe_path(), "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", video,
    ]
    flags = 0x08000000 if __import__("os").name == "nt" else 0
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    return bool(proc.stdout.strip())


def run_full(
    project: Project,
    out_path: Path,
    *,
    engine: TtsEngine | None = None,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[Path, list[BlockRender]]:
    """Chạy toàn bộ pipeline: TTS → ghép audio → mux. Trả (out_path, renders)."""
    engine = engine or TtsEngine()
    with tempfile.TemporaryDirectory(prefix="dubvoice_") as tmp:
        work = Path(tmp)
        renders = render_blocks(
            project, engine, work_dir=work,
            progress=progress, should_stop=should_stop,
        )
        if should_stop and should_stop():
            raise RuntimeError("Đã huỷ.")
        if progress:
            progress(len(renders), len(renders), "Đang ghép track…")
        dub = assemble_audio(renders, work / "dub.wav", work_dir=work)
        if progress:
            progress(len(renders), len(renders), "Đang mux video…")
        mux(project, dub, out_path)
    return out_path, renders
