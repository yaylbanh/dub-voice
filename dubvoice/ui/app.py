"""Cửa sổ chính dub-voice (PySide6)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import voices as voices_mod
from ..fit import HEAVY_DRIFT_MS, compute as compute_fit
from ..project import Block, Project, _default_voice_set
from ..voices import VoiceConfig
from .preview import PreviewPlayer
from .worker import RenderWorker

# Ước lượng thô tốc độ đọc để xem trước cột Fit khi chưa render (ký tự / giây).
_CHARS_PER_SEC = 15.0


def _estimate_natural_ms(text: str) -> int:
    return int(len(text.strip()) / _CHARS_PER_SEC * 1000)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dub-voice — Lồng tiếng AI đa ngôn ngữ (Edge TTS)")
        self.resize(1280, 780)
        self.project: Project | None = None
        self.worker: RenderWorker | None = None
        self._catalog = voices_mod.all_voices()
        self._only_drift = False
        self.player = PreviewPlayer()
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_voice_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        root.addLayout(self._build_bottom())
        self._set_enabled(False)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        b_srt = QPushButton("📂 Mở SRT")
        b_srt.clicked.connect(self.open_srt)
        b_video = QPushButton("🎬 Chọn video")
        b_video.clicked.connect(self.open_video)
        b_open = QPushButton("Mở dự án")
        b_open.clicked.connect(self.load_project)
        b_save = QPushButton("Lưu dự án")
        b_save.clicked.connect(self.save_project)

        self.locale_combo = QComboBox()
        self.locale_combo.addItems(voices_mod.locales(self._catalog))
        self.locale_combo.currentTextChanged.connect(self._on_locale_changed)

        self.stats_label = QLabel("Chưa mở phụ đề")
        self.stats_label.setStyleSheet("color:#555;")

        for w in (b_srt, b_video, b_open, b_save):
            bar.addWidget(w)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Ngôn ngữ phụ đề:"))
        bar.addWidget(self.locale_combo)
        bar.addStretch(1)
        bar.addWidget(self.stats_label)
        return bar

    def _build_table(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Bật", "Giọng", "Text", "Fit", "Nghe", "Tạo lại"])
        h = self.table.horizontalHeader()
        for col in (0, 1, 2, 4, 5, 6):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        return wrap

    def _build_voice_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
        lay.addWidget(QLabel("<b>Danh sách giọng / nhân vật</b>"))

        self.voice_list = QComboBox()
        self.voice_list.currentIndexChanged.connect(self._load_voice_into_editor)
        lay.addWidget(self.voice_list)

        row = QHBoxLayout()
        b_add = QPushButton("➕ Thêm")
        b_add.clicked.connect(self.add_voice)
        b_del = QPushButton("🗑 Xoá")
        b_del.clicked.connect(self.del_voice)
        row.addWidget(b_add)
        row.addWidget(b_del)
        lay.addLayout(row)

        lay.addWidget(self._sep())
        lay.addWidget(QLabel("<b>Chỉnh giọng</b>"))

        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("Tên nhân vật")
        lay.addWidget(QLabel("Nhãn"))
        lay.addWidget(self.ed_label)

        self.ed_locale = QComboBox()
        self.ed_locale.addItems(voices_mod.locales(self._catalog))
        self.ed_locale.currentTextChanged.connect(self._refresh_voice_choices)
        lay.addWidget(QLabel("Ngôn ngữ"))
        lay.addWidget(self.ed_locale)

        self.ed_voice = QComboBox()
        lay.addWidget(QLabel("Giọng Edge"))
        lay.addWidget(self.ed_voice)

        self.ed_rate = self._slider(-50, 100, 0, "Tốc độ nền (%)", lay)
        self.ed_pitch = self._slider(-50, 50, 0, "Cao độ (Hz)", lay)
        self.ed_volume = self._slider(-50, 50, 0, "Âm lượng (%)", lay)

        b_apply = QPushButton("💾 Lưu giọng")
        b_apply.clicked.connect(self.save_voice_edit)
        lay.addWidget(b_apply)

        lay.addWidget(self._sep())
        lay.addWidget(QLabel("<b>Gán hàng loạt</b>"))
        lay.addWidget(QLabel("Gán giọng đang chọn cho các dòng đang chọn trong bảng:"))
        b_batch = QPushButton("Áp dụng cho dòng đã chọn")
        b_batch.clicked.connect(self.apply_voice_to_selection)
        lay.addWidget(b_batch)
        b_default = QPushButton("Đặt làm giọng mặc định")
        b_default.clicked.connect(self.set_default_voice)
        lay.addWidget(b_default)

        lay.addStretch(1)
        return panel

    def _build_bottom(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.chk_drift = QCheckBox("Chỉ hiện block bị lệch (>1s)")
        self.chk_drift.toggled.connect(self._toggle_drift_filter)
        self.chk_keep = QCheckBox("Giữ tiếng gốc làm nền")
        self.chk_keep.setChecked(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.btn_render = QPushButton("▶  Render & Xuất")
        self.btn_render.setStyleSheet(
            "background:#16a34a;color:white;font-weight:bold;padding:8px 18px;")
        self.btn_render.clicked.connect(self.start_render)
        bar.addWidget(self.chk_drift)
        bar.addWidget(self.chk_keep)
        bar.addWidget(self.progress, 1)
        bar.addWidget(self.btn_render)
        return bar

    # -------------- helpers --------------
    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#ddd;")
        return f

    def _slider(self, lo, hi, val, label, lay) -> QSlider:
        lay.addWidget(QLabel(label))
        row = QHBoxLayout()
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setValue(val)
        s.valueChanged.connect(box.setValue)
        box.valueChanged.connect(s.setValue)
        row.addWidget(s)
        row.addWidget(box)
        lay.addLayout(row)
        s._box = box  # type: ignore[attr-defined]
        return s

    def _set_enabled(self, on: bool):
        self.btn_render.setEnabled(on)

    # -------------- actions --------------
    def open_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file SRT", "", "SRT (*.srt)")
        if not path:
            return
        self.project = Project.from_srt(path)
        self.locale_combo.setCurrentText(self.project.locale)
        self._reload_voice_list()
        self._reload_table()
        self._set_enabled(True)
        self._update_stats()

    def open_video(self):
        if not self.project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", "", "Video (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.project.video_path = path
            self._update_stats()

    def save_project(self):
        if not self.project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu dự án", self.project.name + ".dubproj.json",
            "Dự án (*.dubproj.json)")
        if path:
            self.project.keep_original_audio = self.chk_keep.isChecked()
            self.project.save(path)
            QMessageBox.information(self, "Đã lưu", f"Đã lưu dự án:\n{path}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở dự án", "", "Dự án (*.dubproj.json)")
        if not path:
            return
        self.project = Project.load(path)
        self.locale_combo.setCurrentText(self.project.locale)
        self.chk_keep.setChecked(self.project.keep_original_audio)
        self._reload_voice_list()
        self._reload_table()
        self._set_enabled(True)
        self._update_stats()

    def _on_locale_changed(self, loc: str):
        if self.project:
            self.project.locale = loc

    # -------- voice panel --------
    def _reload_voice_list(self):
        self.voice_list.blockSignals(True)
        self.voice_list.clear()
        if self.project:
            for v in self.project.voices:
                self.voice_list.addItem(f"● {v.label}", v.label)
        self.voice_list.blockSignals(False)
        if self.project and self.project.voices:
            self.voice_list.setCurrentIndex(0)
            self._load_voice_into_editor()

    def _current_voice_cfg(self) -> VoiceConfig | None:
        if not self.project:
            return None
        label = self.voice_list.currentData()
        return self.project.voice_map().get(label)

    def _load_voice_into_editor(self):
        cfg = self._current_voice_cfg()
        if not cfg:
            return
        self.ed_label.setText(cfg.label)
        loc = "-".join(cfg.voice.split("-")[:2])
        self.ed_locale.setCurrentText(loc)
        self._refresh_voice_choices()
        idx = self.ed_voice.findData(cfg.voice)
        if idx >= 0:
            self.ed_voice.setCurrentIndex(idx)
        self.ed_rate.setValue(cfg.rate_pct)
        self.ed_pitch.setValue(cfg.pitch_hz)
        self.ed_volume.setValue(cfg.volume_pct)

    def _refresh_voice_choices(self):
        loc = self.ed_locale.currentText()
        self.ed_voice.clear()
        for v in voices_mod.by_locale(loc, self._catalog):
            self.ed_voice.addItem(f"{v.friendly} ({v.gender})", v.short_name)

    def add_voice(self):
        if not self.project:
            return
        n = len(self.project.voices) + 1
        cfg = VoiceConfig(f"Nhân vật {n}", "vi-VN-NamMinhNeural")
        self.project.voices.append(cfg)
        self._reload_voice_list()
        self.voice_list.setCurrentIndex(self.voice_list.count() - 1)
        self._refresh_row_combos()

    def del_voice(self):
        cfg = self._current_voice_cfg()
        if not cfg or not self.project:
            return
        if len(self.project.voices) <= 1:
            QMessageBox.warning(self, "Không thể xoá", "Phải còn ít nhất 1 giọng.")
            return
        self.project.voices = [v for v in self.project.voices if v.label != cfg.label]
        if self.project.default_voice == cfg.label:
            self.project.default_voice = self.project.voices[0].label
        self._reload_voice_list()
        self._refresh_row_combos()

    def save_voice_edit(self):
        cfg = self._current_voice_cfg()
        if not cfg or not self.project:
            return
        old_label = cfg.label
        cfg.label = self.ed_label.text().strip() or old_label
        if self.ed_voice.currentData():
            cfg.voice = self.ed_voice.currentData()
        cfg.rate_pct = self.ed_rate.value()
        cfg.pitch_hz = self.ed_pitch.value()
        cfg.volume_pct = self.ed_volume.value()
        # đổi tên ở các block đang tham chiếu
        if old_label != cfg.label:
            for b in self.project.blocks:
                if b.voice_label == old_label:
                    b.voice_label = cfg.label
            if self.project.default_voice == old_label:
                self.project.default_voice = cfg.label
        self._reload_voice_list()
        self._refresh_row_combos()
        self._recompute_fits()

    def set_default_voice(self):
        cfg = self._current_voice_cfg()
        if cfg and self.project:
            self.project.default_voice = cfg.label
            self._update_stats()

    def apply_voice_to_selection(self):
        cfg = self._current_voice_cfg()
        if not cfg or not self.project:
            return
        rows = {i.row() for i in self.table.selectedIndexes()}
        for row in rows:
            block = self._block_at_visible_row(row)
            if block:
                block.voice_label = cfg.label
                combo = self.table.cellWidget(row, 2)
                if isinstance(combo, QComboBox):
                    idx = combo.findData(cfg.label)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
        self._update_stats()

    # -------- table --------
    def _visible_blocks(self) -> list[Block]:
        if not self.project:
            return []
        if not self._only_drift:
            return self.project.blocks
        out = []
        for b in self.project.blocks:
            if not b.enabled:
                continue
            est = _estimate_natural_ms(b.text)
            fit = compute_fit(est, b.slot_ms, max_tempo=self.project.max_tempo)
            if fit.is_heavy:
                out.append(b)
        return out

    def _reload_table(self):
        if not self.project:
            return
        blocks = self._visible_blocks()
        self.table.setRowCount(len(blocks))
        self._row_blocks: list[Block] = blocks
        labels = [v.label for v in self.project.voices]
        for row, b in enumerate(blocks):
            # # index
            it = QTableWidgetItem(str(b.index))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, it)
            # enabled checkbox
            chk = QCheckBox()
            chk.setChecked(b.enabled)
            chk.toggled.connect(lambda v, blk=b: self._on_enable_toggled(blk, v))
            self.table.setCellWidget(row, 1, self._center(chk))
            # voice combo
            combo = QComboBox()
            for lab in labels:
                combo.addItem(lab, lab)
            if b.voice_label:
                i = combo.findData(b.voice_label)
                if i >= 0:
                    combo.setCurrentIndex(i)
            else:
                combo.setCurrentIndex(-1)
                combo.setPlaceholderText("(mặc định)")
            combo.currentIndexChanged.connect(
                lambda _i, blk=b, c=combo: self._on_voice_changed(blk, c))
            self.table.setCellWidget(row, 2, combo)
            # text
            txt = QTableWidgetItem(b.text)
            txt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 3, txt)
            # fit
            self.table.setItem(row, 4, self._fit_item(b))
            # nghe thử
            b_play = QPushButton("▶")
            b_play.setFixedWidth(34)
            b_play.setToolTip("Nghe thử (dùng cache nếu có)")
            b_play.clicked.connect(lambda _c, blk=b: self._preview(blk, regenerate=False))
            self.table.setCellWidget(row, 5, self._center(b_play))
            # tạo lại
            b_regen = QPushButton("↻")
            b_regen.setFixedWidth(34)
            b_regen.setToolTip("Tạo lại voice (bỏ cache, sinh mới rồi nghe)")
            b_regen.clicked.connect(lambda _c, blk=b: self._preview(blk, regenerate=True))
            self.table.setCellWidget(row, 6, self._center(b_regen))
        self._update_stats()

    def _fit_item(self, b: Block) -> QTableWidgetItem:
        if not b.enabled or not b.text.strip():
            it = QTableWidgetItem("—")
            it.setForeground(QColor("#999"))
            return it
        est = _estimate_natural_ms(b.text)
        fit = compute_fit(est, b.slot_ms, max_tempo=self.project.max_tempo)
        d = fit.drift_ms
        sign = "+" if d > 0 else ""
        it = QTableWidgetItem(f"{sign}{d/1000:.1f}s")
        if fit.is_heavy:
            it.setForeground(QColor("#dc2626"))
        elif abs(d) <= 200:
            it.setForeground(QColor("#16a34a"))
            it.setText("OK")
        else:
            it.setForeground(QColor("#d97706"))
        it.setFlags(Qt.ItemIsEnabled)
        return it

    def _center(self, w: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _block_at_visible_row(self, row: int) -> Block | None:
        if 0 <= row < len(getattr(self, "_row_blocks", [])):
            return self._row_blocks[row]
        return None

    def _on_enable_toggled(self, block: Block, val: bool):
        block.enabled = val
        self._update_stats()

    def _on_voice_changed(self, block: Block, combo: QComboBox):
        block.voice_label = combo.currentData() or ""
        row = self._row_blocks.index(block) if block in getattr(self, "_row_blocks", []) else -1
        if row >= 0:
            self.table.setItem(row, 4, self._fit_item(block))

    def _refresh_row_combos(self):
        # cập nhật danh sách giọng trong mọi combo của bảng
        self._reload_table()

    def _recompute_fits(self):
        for row, b in enumerate(getattr(self, "_row_blocks", [])):
            self.table.setItem(row, 4, self._fit_item(b))

    def _toggle_drift_filter(self, on: bool):
        self._only_drift = on
        self._reload_table()

    def _update_stats(self):
        if not self.project:
            return
        s = self.project.stats()
        vid = "✓ video" if self.project.video_path else "chưa có video"
        self.stats_label.setText(
            f"Tổng {s['total']} block · {s['active']} bật · "
            f"{s['unassigned']} chưa gán · {vid}")

    # -------- nghe thử / tạo lại --------
    def _preview(self, block: Block, *, regenerate: bool):
        if not self.project:
            return
        cfg = self.project.resolve_voice(block)
        if cfg is None:
            QMessageBox.warning(self, "Chưa có giọng", "Block này chưa được gán giọng.")
            return
        self.player.play(
            block.text, cfg, self.project.locale, regenerate=regenerate,
            on_error=lambda m: self.statusBar().showMessage(f"Lỗi nghe thử: {m}", 5000),
            on_state=lambda m: self.statusBar().showMessage(m, 3000) if m else None,
        )

    # -------- render --------
    def start_render(self):
        if not self.project:
            return
        if not self.project.blocks:
            QMessageBox.warning(self, "Trống", "Chưa có block nào.")
            return
        default_ext = ".mp4" if self.project.video_path else ".mp3"
        out, _ = QFileDialog.getSaveFileName(
            self, "Xuất ra", self.project.name + "_dub" + default_ext,
            "Video/Audio (*.mp4 *.mkv *.wav *.mp3)")
        if not out:
            return
        self.project.keep_original_audio = self.chk_keep.isChecked()
        self.project.locale = self.locale_combo.currentText()
        self.btn_render.setEnabled(False)
        self.btn_render.setText("⏳ Đang render…")
        self.worker = RenderWorker(self.project, out)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, done: int, total: int, msg: str):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} — {msg}")

    def _on_done(self, out: str, errs: int, heavy: int):
        self.btn_render.setEnabled(True)
        self.btn_render.setText("▶  Render & Xuất")
        QMessageBox.information(
            self, "Hoàn tất",
            f"Đã xuất:\n{out}\n\nLỗi: {errs} block · Lệch nặng: {heavy} block")

    def _on_failed(self, msg: str):
        self.btn_render.setEnabled(True)
        self.btn_render.setText("▶  Render & Xuất")
        QMessageBox.critical(self, "Lỗi render", msg)

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
