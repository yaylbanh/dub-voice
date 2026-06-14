# dub-voice

Lồng tiếng AI cho phim (review drama) từ phụ đề **SRT** bằng **Microsoft Edge TTS** —
**đa ngôn ngữ** (322 giọng / 142 locale), tự khớp thời lượng theo timeline, gán giọng
theo nhân vật, ghép thẳng vào video.

## Tính năng

- **Đa ngôn ngữ**: lấy động toàn bộ giọng Edge, lọc theo locale (vi-VN, zh-CN, en-US, ko-KR, ja-JP…).
- **Auto time-fit**: tự tăng tốc giọng (atempo, giới hạn an toàn ~1.5x) để khớp slot SRT;
  phần tràn để chồng tự nhiên sang câu sau. Cột **Fit** hiển thị độ lệch, tô đỏ block lệch nặng (>1s).
- **Giọng theo nhân vật**: mỗi nhân vật là một cấu hình giọng (giọng Edge + tốc độ + cao độ + âm lượng).
  Vì Edge chỉ có 2 giọng tiếng Việt, dùng **pitch/rate** để phân biệt nam/nữ chính–phụ.
- **Gán hàng loạt**: chọn nhiều dòng trong bảng → gán 1 giọng; đặt giọng mặc định cho dòng chưa gán.
- **Bỏ qua dòng rác** (`...`, dòng trống) tự động.
- **Cache TTS**: block không đổi không sinh lại (theo hash text + giọng + tham số).
- **Ghép video**: giữ tiếng gốc làm nền (âm lượng thấp) hoặc thay hẳn; xuất `.mp4`/`.wav`/`.mp3`.
- Toàn bộ xử lý audio bằng **ffmpeg** trực tiếp — không cần pydub/numpy, chạy mượt với hàng nghìn block.

## Cài đặt

```bash
pip install -r requirements.txt
# Cần ffmpeg + ffprobe trong PATH (hoặc đặt ffmpeg_bin/ cạnh thư mục dự án).
```

## Dùng GUI

```bash
python -m dubvoice gui      # hoặc bấm run.bat trên Windows
```

Quy trình: **Mở SRT** → (tuỳ chọn) **Chọn video** → cấu hình giọng / gán nhân vật →
**Render & Xuất**.

## Dùng CLI

```bash
# Lồng tiếng một giọng, ghép vào video
python -m dubvoice dub phim.srt --video phim.mp4 -o phim_dub.mp4

# Xuất audio, chọn giọng + ngôn ngữ
python -m dubvoice dub phim.srt --voice zh-CN-YunxiNeural --locale zh-CN -o out.mp3

# Thay hẳn tiếng gốc, nới giới hạn tăng tốc
python -m dubvoice dub phim.srt --video phim.mp4 --replace-audio --max-tempo 1.7 -o out.mp4

# Xem danh mục giọng
python -m dubvoice voices               # liệt kê locale
python -m dubvoice voices --locale zh-CN
```

## Kiến trúc

```
dubvoice/
  ffmpeg.py    định vị + bọc ffmpeg/ffprobe
  srt.py       đọc/ghi SRT
  text.py      chuẩn hoá text (đa ngôn ngữ; đọc số chữ cho vi-VN)
  voices.py    danh mục giọng Edge (fetch động + cache) + VoiceConfig
  tts.py       sinh audio Edge TTS + cache theo nội dung
  fit.py       logic khớp thời lượng (atempo, ngưỡng lệch)
  project.py   mô hình Project/Block, lưu .dubproj.json
  assemble.py  dựng track tổng + mux video
  cli.py       CLI
  ui/app.py    GUI PySide6
```

## Hướng phát triển tiếp

- Auto gán giọng theo nhân vật (phân tích người nói).
- AI rút gọn câu khi lệch nặng để khớp timeline mà giữ nghĩa.
- Hàng đợi render nhiều tập (batch overnight).
- Nghe thử từng block ngay trong GUI; preview video kèm waveform.
