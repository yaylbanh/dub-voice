"""Giao diện dòng lệnh cho dub-voice.

Ví dụ:
    python -m dubvoice dub phim.srt --video phim.mp4 -o phim_dub.mp4
    python -m dubvoice dub phim.srt --voice vi-VN-NamMinhNeural -o out.mp3
    python -m dubvoice voices --locale zh-CN
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import voices as voices_mod
from .assemble import run_full
from .project import Project
from .tts import TtsEngine
from .voices import VoiceConfig


def _cmd_voices(args) -> int:
    vs = voices_mod.all_voices(force_refresh=args.refresh)
    if args.locale:
        vs = voices_mod.by_locale(args.locale, vs)
    if not args.locale:
        print(f"{len(vs)} giọng / {len(voices_mod.locales(vs))} locale. "
              f"Lọc bằng --locale, vd: --locale zh-CN")
        for loc in voices_mod.locales(vs):
            n = len(voices_mod.by_locale(loc, vs))
            print(f"  {loc:8s} ({n})")
        return 0
    for v in vs:
        print(f"  {v.short_name:32s} {v.gender:7s} {v.friendly}")
    return 0


def _cmd_dub(args) -> int:
    srt = Path(args.srt)
    if not srt.exists():
        print(f"Không thấy file SRT: {srt}", file=sys.stderr)
        return 1

    proj = Project.from_srt(srt)
    if args.video:
        proj.video_path = args.video
    if args.locale:
        proj.locale = args.locale
    proj.keep_original_audio = not args.replace_audio
    proj.max_tempo = args.max_tempo

    if args.voice:
        # Chế độ một giọng: gán toàn bộ cho 1 giọng chỉ định.
        cfg = VoiceConfig("Mặc định", args.voice)
        proj.voices = [cfg]
        proj.default_voice = cfg.label
        for b in proj.blocks:
            b.voice_label = cfg.label

    out = Path(args.output)

    def progress(done, total, msg):
        pct = int(done / total * 100) if total else 0
        print(f"\r[{pct:3d}%] {done}/{total} {msg:40s}", end="", flush=True)

    print(f"Lồng tiếng {len(proj.blocks)} block → {out}")
    _, renders = run_full(proj, out, engine=TtsEngine(), progress=progress)
    print()
    errs = [r for r in renders if r.error]
    heavy = [r for r in renders if r.fit and r.fit.is_heavy]
    print(f"Xong: {out}")
    print(f"  Lỗi: {len(errs)} block | Lệch nặng (>1s): {len(heavy)} block")
    if errs:
        for r in errs[:10]:
            print(f"    #{r.block.index}: {r.error}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dubvoice", description="Lồng tiếng AI từ SRT (Edge TTS)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("voices", help="Liệt kê giọng Edge")
    pv.add_argument("--locale", help="Lọc theo locale, vd vi-VN, zh-CN")
    pv.add_argument("--refresh", action="store_true", help="Tải lại danh mục giọng")
    pv.set_defaults(func=_cmd_voices)

    pd = sub.add_parser("dub", help="Lồng tiếng từ file SRT")
    pd.add_argument("srt")
    pd.add_argument("-o", "--output", required=True, help="File ra (.mp4/.wav/.mp3)")
    pd.add_argument("--video", help="Video gốc để ghép")
    pd.add_argument("--voice", help="Giọng đơn (short_name Edge)")
    pd.add_argument("--locale", help="Locale của phụ đề, vd vi-VN")
    pd.add_argument("--replace-audio", action="store_true", help="Thay hẳn tiếng gốc")
    pd.add_argument("--max-tempo", type=float, default=1.5, help="Giới hạn tăng tốc (1.5)")
    pd.set_defaults(func=_cmd_dub)

    pg = sub.add_parser("gui", help="Mở giao diện đồ hoạ")
    pg.set_defaults(func=lambda a: (__import__("dubvoice.ui.app", fromlist=["main"]).main() or 0))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
