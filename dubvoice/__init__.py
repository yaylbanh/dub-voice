"""dub-voice — lồng tiếng AI cho phim từ phụ đề SRT bằng Microsoft Edge TTS.

Module chính:
    srt        : đọc/ghi phụ đề SRT
    text       : chuẩn hoá text trước khi đọc (số, ký tự lạ)
    voices     : danh mục giọng Edge + cấu hình giọng theo nhân vật
    tts        : sinh audio qua Edge TTS, có cache
    fit        : logic khớp thời lượng (auto time-fit)
    assemble   : dựng track tổng + ghép vào video bằng ffmpeg
    project    : mô hình Project / Block, lưu .dubproj.json
"""

__version__ = "0.1.0"
