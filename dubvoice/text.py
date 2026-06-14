"""Chuẩn hoá text trước khi đưa vào TTS.

Đa ngôn ngữ: bỏ ký tự markup/điều khiển gây lỗi đọc, gộp dấu câu lặp.
Đọc số bằng chữ chỉ áp dụng cho tiếng Việt (num2words tuỳ chọn) để tránh
phá vỡ ngôn ngữ khác — với ngôn ngữ khác, Edge TTS tự đọc số đúng bản ngữ.
"""
from __future__ import annotations

import re

_MARKUP = re.compile(r"[*~_\[\]<>{}]")
_QUOTES = str.maketrans("", "", '"“”‘’')
_MULTI_DOT = re.compile(r"\.{2,}")
_MULTI_DASH = re.compile(r"-{2,}")
_WS = re.compile(r"\s+")

try:  # tuỳ chọn — chỉ dùng cho tiếng Việt
    from num2words import num2words  # type: ignore

    _HAS_NUM2WORDS = True
except ImportError:  # pragma: no cover
    _HAS_NUM2WORDS = False


def clean(text: str, *, locale: str = "") -> str:
    """Làm sạch text cho TTS. ``locale`` ví dụ 'vi-VN', 'zh-CN'."""
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = _MARKUP.sub("", text)
    text = text.translate(_QUOTES)
    text = _MULTI_DOT.sub(".", text)
    text = _MULTI_DASH.sub(",", text)

    if _HAS_NUM2WORDS and locale.startswith("vi"):
        try:
            text = re.sub(
                r"\d+", lambda m: num2words(int(m.group()), lang="vi"), text
            )
        except (ValueError, NotImplementedError):
            pass

    return _WS.sub(" ", text).strip()
