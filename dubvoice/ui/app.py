"""Cửa sổ chính dub-voice (PySide6)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QDoubleSpinBox, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import voices as voices_mod
from ..fit import HEAVY_DRIFT_MS, compute as compute_fit
from ..project import Block, Project, _default_voice_set
from ..voices import VoiceConfig
from .left_panel import LeftWorkspaceView
from .left_panel_controller import LeftWorkspaceController
from .preview import PreviewPlayer
from .voice_list import VoiceListRow
from .worker import RenderWorker

# Ước lượng thô tốc độ đọc để xem trước cột Fit khi chưa render (ký tự / giây).
_CHARS_PER_SEC = 15.0


def _app_state_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".local" / "state"
    return base / "dub-voice" / "ui_state.json"


def _estimate_natural_ms(text: str) -> int:
    return int(len(text.strip()) / _CHARS_PER_SEC * 1000)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dub-voice — Lồng tiếng AI đa ngôn ngữ (Edge TTS)")
        self.resize(1280, 780)
        self.project: Project | None = None
        self.project_path: Path | None = None
        self.worker: RenderWorker | None = None
        self._catalog = voices_mod.all_voices()
        self._only_drift = False
        self._assignment_filter = "all"
        self._voice_filter = ""
        self._search_text = ""
        self._is_reloading_table = False
        self._skip_resume_prompt = os.environ.get("DUBVOICE_SKIP_RESUME_PROMPT") == "1"
        self.player = PreviewPlayer()
        self.left_workspace = LeftWorkspaceView()
        self.left_controller = LeftWorkspaceController(
            self.left_workspace,
            preview_source=self._preview_source_block,
            preview_tts=self._preview_selected_block,
            apply_blocks=self._apply_block_ranges,
        )
        self._build_ui()
        if not self._skip_resume_prompt:
            QTimer.singleShot(0, self._prompt_resume_project)

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_workspace)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_voice_panel())
        splitter.setSizes([320, 760, 320])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 1)
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
        self.btn_save_project = b_save

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
        lay.addLayout(self._build_table_filters())
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Bật", "Giọng", "Text", "Fit", "Nghe", "Tạo lại"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        h = self.table.horizontalHeader()
        for col in (0, 1, 2, 4, 5, 6):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        return wrap

    def _build_table_filters(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.assignment_filter_combo = QComboBox()
        self.assignment_filter_combo.addItem("Tất cả", "all")
        self.assignment_filter_combo.addItem("Chưa gán", "unassigned")
        self.assignment_filter_combo.addItem("Đã gán", "assigned")
        self.assignment_filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.voice_filter_combo = QComboBox()
        self.voice_filter_combo.addItem("Lọc giọng", "")
        self.voice_filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm nội dung...")
        self.search_input.textChanged.connect(self._on_search_changed)

        self.chk_drift = QCheckBox("Chỉ block lệch")
        self.chk_drift.toggled.connect(self._toggle_drift_filter)

        bar.addWidget(self.assignment_filter_combo)
        bar.addWidget(self.voice_filter_combo)
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.chk_drift)
        return bar

    def _build_voice_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Danh sách giọng / nhân vật</b>"))
        header.addStretch(1)
        b_add = QPushButton("➕")
        b_add.setFixedWidth(34)
        b_add.clicked.connect(self.add_voice)
        header.addWidget(b_add)
        lay.addLayout(header)

        self.voice_list = QListWidget()
        self.voice_list.setSpacing(6)
        self.voice_list.setStyleSheet(
            "QListWidget { border:0; background:transparent; }"
            "QListWidget::item { border:0; padding:2px; }"
            "QListWidget::item:selected { background:#dbeafe; border-radius:10px; }"
        )
        self.voice_list.currentItemChanged.connect(self._on_voice_item_changed)
        lay.addWidget(self.voice_list)

        lay.addWidget(self._sep())
        lay.addWidget(QLabel("<b>Chỉnh giọng</b>"))

        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("Tên nhân vật")
        lay.addWidget(QLabel("Nhãn"))
        lay.addWidget(self.ed_label)

        self.ed_provider = QComboBox()
        self.ed_provider.addItem("Microsoft Edge TTS", "edge")
        lay.addWidget(QLabel("Provider"))
        lay.addWidget(self.ed_provider)

        self.ed_locale = QComboBox()
        self.ed_locale.addItems(voices_mod.locales(self._catalog))
        self.ed_locale.currentTextChanged.connect(self._refresh_voice_choices)
        lay.addWidget(QLabel("Ngôn ngữ"))
        lay.addWidget(self.ed_locale)

        self.ed_voice = QComboBox()
        lay.addWidget(QLabel("Voice"))
        lay.addWidget(self.ed_voice)

        self.ed_rate = self._speed_control("Tốc độ giọng (x)", lay)
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
        self.chk_keep = QCheckBox("Giữ tiếng gốc làm nền")
        self.chk_keep.setChecked(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.btn_render = QPushButton("▶  Render & Xuất")
        self.btn_render.setStyleSheet(
            "background:#16a34a;color:white;font-weight:bold;padding:8px 18px;")
        self.btn_render.clicked.connect(self.start_render)
        self.btn_export_segments = QPushButton("Xuất từng line nhỏ")
        self.btn_export_segments.clicked.connect(self.start_export_segments)
        self.btn_stop = QPushButton("Dừng khẩn cấp")
        self.btn_stop.setStyleSheet("background:#dc2626;color:white;font-weight:bold;padding:8px 14px;")
        self.btn_stop.clicked.connect(self.stop_render)
        bar.addWidget(self.chk_keep)
        bar.addWidget(self.progress, 1)
        bar.addWidget(self.btn_export_segments)
        bar.addWidget(self.btn_stop)
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

    def _speed_control(self, label, lay) -> QDoubleSpinBox:
        lay.addWidget(QLabel(label))
        row = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(50, 200)
        slider.setValue(100)
        box = QDoubleSpinBox()
        box.setRange(0.50, 2.00)
        box.setSingleStep(0.05)
        box.setDecimals(2)
        box.setValue(1.00)
        box.setSuffix("x")

        slider.valueChanged.connect(lambda value: box.setValue(value / 100.0))
        box.valueChanged.connect(lambda value: slider.setValue(int(round(value * 100))))

        row.addWidget(slider)
        row.addWidget(box)
        lay.addLayout(row)
        box._slider = slider  # type: ignore[attr-defined]
        return box

    def _set_enabled(self, on: bool):
        self.btn_render.setEnabled(on)
        self.btn_export_segments.setEnabled(on)
        self.btn_save_project.setEnabled(on)
        self.left_workspace.btn_apply.setEnabled(on)
        self.assignment_filter_combo.setEnabled(on)
        self.voice_filter_combo.setEnabled(on)
        self.search_input.setEnabled(on)
        self.chk_drift.setEnabled(on)
        self.btn_stop.setEnabled(False)

    def _save_app_state(self) -> None:
        state = {
            "last_project_path": str(self.project_path) if self.project_path else "",
            "resume_on_startup": bool(self.project_path and self.project),
        }
        path = _app_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_app_state(self) -> dict:
        path = _app_state_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _prompt_resume_project(self) -> None:
        if self.project is not None:
            return
        state = self._load_app_state()
        project_path = str(state.get("last_project_path") or "").strip()
        if not state.get("resume_on_startup") or not project_path:
            return
        path = Path(project_path)
        if not path.exists():
            self._clear_resume_state()
            return
        answer = QMessageBox.question(
            self,
            "Mở dự án cũ",
            f"Phát hiện dự án gần nhất chưa xong:\n{path}\n\nMở lại để làm tiếp không?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._load_project_path(path)
        else:
            self._clear_resume_state()

    def _clear_resume_state(self) -> None:
        self.project_path = None
        state = {"last_project_path": "", "resume_on_startup": False}
        path = _app_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # -------------- actions --------------
    def open_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file SRT", "", "SRT (*.srt)")
        if not path:
            return
        self.project = Project.from_srt(path)
        self.project_path = None
        self.locale_combo.setCurrentText(self.project.locale)
        self._reload_voice_list()
        self._reload_table()
        self.left_controller.set_project(self.project)
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
        if self.project_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Lưu dự án", self.project.name + ".dubproj.json",
                "Dự án (*.dubproj.json)")
            if not path:
                return
            self.project_path = Path(path)
        self.project.keep_original_audio = self.chk_keep.isChecked()
        self.project.save(self.project_path)
        self._save_app_state()
        self.statusBar().showMessage(f"Đã lưu dự án: {self.project_path}", 4000)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở dự án", "", "Dự án (*.dubproj.json)")
        if not path:
            return
        self._load_project_path(Path(path))

    def _load_project_path(self, path: Path):
        self.project = Project.load(path)
        self.project_path = Path(path)
        self.locale_combo.setCurrentText(self.project.locale)
        self.chk_keep.setChecked(self.project.keep_original_audio)
        self._reload_voice_list()
        self._reload_table()
        self.left_controller.set_project(self.project)
        self._set_enabled(True)
        self._update_stats()
        self._save_app_state()

    def _on_locale_changed(self, loc: str):
        if self.project:
            self.project.locale = loc

    # -------- voice panel --------
    def _reload_voice_list(self):
        current_label = self._current_voice_label()
        self.voice_list.blockSignals(True)
        self.voice_list.clear()
        if self.project:
            for voice in self.project.voices:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, voice.label)
                item.setSizeHint(self._voice_row_size_hint())
                self.voice_list.addItem(item)
                row = VoiceListRow(
                    voice.label,
                    voice.color,
                    is_default=self.project.default_voice == voice.label,
                )
                row.play_requested.connect(self._preview_voice_label)
                row.edit_requested.connect(self._select_voice_label)
                row.menu_requested.connect(self._open_voice_row_menu)
                self.voice_list.setItemWidget(item, row)
        self.voice_list.blockSignals(False)
        if self.project and self.project.voices:
            target = current_label or self.project.voices[0].label
            self._select_voice_label(target)
        self.left_controller.refresh_voice_choices()
        self._refresh_table_filter_voices()

    def _current_voice_cfg(self) -> VoiceConfig | None:
        if not self.project:
            return None
        label = self._current_voice_label()
        return self.project.voice_map().get(label)

    def _current_voice_label(self) -> str:
        item = self.voice_list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _load_voice_into_editor(self):
        cfg = self._current_voice_cfg()
        if not cfg:
            return
        self.ed_label.setText(cfg.label)
        self.ed_provider.setCurrentIndex(0)
        loc = "-".join(cfg.voice.split("-")[:2])
        self.ed_locale.setCurrentText(loc)
        self._refresh_voice_choices()
        idx = self.ed_voice.findData(cfg.voice)
        if idx >= 0:
            self.ed_voice.setCurrentIndex(idx)
        self.ed_rate.setValue(cfg.speed_multiplier())
        self.ed_pitch.setValue(cfg.pitch_hz)
        self.ed_volume.setValue(cfg.volume_pct)

    def _refresh_voice_choices(self):
        loc = self.ed_locale.currentText()
        current_voice = self.ed_voice.currentData()
        self.ed_voice.clear()
        for v in voices_mod.by_locale(loc, self._catalog):
            self.ed_voice.addItem(f"{v.friendly} ({v.gender})", v.short_name)
        idx = self.ed_voice.findData(current_voice)
        if idx >= 0:
            self.ed_voice.setCurrentIndex(idx)
        elif self.ed_voice.count():
            self.ed_voice.setCurrentIndex(0)

    def _voice_row_size_hint(self):
        return QSize(260, 44)

    def _on_voice_item_changed(self, current, _previous):
        if current:
            self._load_voice_into_editor()

    def _select_voice_label(self, label: str):
        for i in range(self.voice_list.count()):
            item = self.voice_list.item(i)
            if item.data(Qt.UserRole) == label:
                self.voice_list.setCurrentRow(i)
                self._load_voice_into_editor()
                break

    def _preview_voice_label(self, label: str):
        if not self.project:
            return
        cfg = self.project.voice_map().get(label)
        if not cfg:
            return
        block = self.left_controller.current_block
        if block is None:
            block = next((b for b in self.project.blocks if b.enabled and b.text.strip()), None)
        sample_text = block.text if block else f"Xin chào, đây là giọng {cfg.label}."
        self.player.play(
            sample_text,
            cfg,
            self.ed_locale.currentText() or self.project.locale,
            regenerate=False,
            on_error=lambda m: self.statusBar().showMessage(f"Lỗi nghe thử: {m}", 5000),
            on_state=lambda m: self.statusBar().showMessage(m, 3000) if m else None,
        )

    def _open_voice_row_menu(self, label: str, anchor):
        self._select_voice_label(label)
        menu = QMenu(self)
        act_default = menu.addAction("Đặt làm giọng mặc định")
        act_delete = menu.addAction("Xoá giọng")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen == act_default:
            cfg = self.project.voice_map().get(label) if self.project else None
            if cfg and self.project:
                self.project.default_voice = cfg.label
                self._reload_voice_list()
                self._reload_table()
                self._update_stats()
        elif chosen == act_delete:
            self.del_voice()

    def add_voice(self):
        if not self.project:
            return
        n = len(self.project.voices) + 1
        cfg = VoiceConfig(f"Nhân vật {n}", "vi-VN-NamMinhNeural")
        self.project.voices.append(cfg)
        self._reload_voice_list()
        self._select_voice_label(cfg.label)
        self._refresh_row_combos()

    def del_voice(self):
        cfg = self._current_voice_cfg()
        if not cfg or not self.project:
            return
        if len(self.project.voices) <= 1:
            QMessageBox.warning(self, "Không thể xoá", "Phải còn ít nhất 1 giọng.")
            return
        for block in self.project.blocks:
            if block.voice_label == cfg.label:
                block.voice_label = ""
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
        cfg.set_speed_multiplier(self.ed_rate.value())
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
        self._select_voice_label(cfg.label)
        self._refresh_row_combos()
        self._recompute_fits()

    def set_default_voice(self):
        cfg = self._current_voice_cfg()
        if cfg and self.project:
            self.project.default_voice = cfg.label
            self._reload_voice_list()
            self._reload_table()
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
        self._reload_table()
        self._update_stats()
        self.left_controller.refresh_voice_choices()

    # -------- table --------
    def _visible_blocks(self) -> list[Block]:
        if not self.project:
            return []
        out = []
        for b in self.project.blocks:
            if not b.enabled:
                continue
            if self._assignment_filter == "unassigned" and self.project.has_explicit_voice(b):
                continue
            if self._assignment_filter == "assigned" and not self.project.has_explicit_voice(b):
                continue
            if self._voice_filter and b.voice_label != self._voice_filter:
                continue
            if self._search_text and self._search_text not in b.text.lower():
                continue
            est = _estimate_natural_ms(b.text)
            fit = compute_fit(est, b.slot_ms, max_tempo=self.project.max_tempo)
            if self._only_drift and not fit.is_heavy:
                continue
            out.append(b)
        return out

    def _reload_table(self):
        if not self.project:
            return
        self._is_reloading_table = True
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        blocks = self._visible_blocks()
        self.table.setRowCount(len(blocks))
        self._row_blocks: list[Block] = blocks
        labels = [v.label for v in self.project.voices]
        current_block_index = getattr(self.left_controller.current_block, "index", None)
        selected_row = -1
        for row, b in enumerate(blocks):
            # # index
            it = QTableWidgetItem(str(b.index))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, it)
            # enabled checkbox
            enabled_item = QTableWidgetItem("")
            enabled_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            enabled_item.setCheckState(Qt.Checked if b.enabled else Qt.Unchecked)
            self.table.setItem(row, 1, enabled_item)
            # voice combo
            combo = QComboBox()
            combo.addItem("Chưa gán", "")
            for lab in labels:
                combo.addItem(lab, lab)
            if b.voice_label:
                i = combo.findData(b.voice_label)
                if i >= 0:
                    combo.setCurrentIndex(i)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)
            fallback = self.project.default_voice or "(chưa có)"
            combo.setToolTip(
                f"Giọng gán trực tiếp cho block. Nếu để `Chưa gán`, render sẽ fallback sang `{fallback}`."
            )
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
            play_item = QTableWidgetItem("▶")
            play_item.setTextAlignment(Qt.AlignCenter)
            play_item.setToolTip("Nghe thử (dùng cache nếu có)")
            play_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 5, play_item)
            # tạo lại
            regen_item = QTableWidgetItem("↻")
            regen_item.setTextAlignment(Qt.AlignCenter)
            regen_item.setToolTip("Tạo lại voice (bỏ cache, sinh mới rồi nghe)")
            regen_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 6, regen_item)
            if current_block_index == b.index:
                selected_row = row
        if selected_row < 0 and blocks:
            selected_row = 0
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.left_controller.set_current_block(None, selected_count=0)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._is_reloading_table = False
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

    def _on_table_item_changed(self, item: QTableWidgetItem):
        if self._is_reloading_table or item.column() != 1:
            return
        block = self._block_at_visible_row(item.row())
        if not block:
            return
        block.enabled = item.checkState() == Qt.Checked
        if self._only_drift or self._search_text or self._voice_filter or self._assignment_filter != "all":
            self._reload_table()
            return
        self.table.setItem(item.row(), 4, self._fit_item(block))
        self._update_stats()

    def _on_table_cell_clicked(self, row: int, column: int):
        block = self._block_at_visible_row(row)
        if not block:
            return
        if column == 5:
            self._preview(block, regenerate=False)
        elif column == 6:
            self._preview(block, regenerate=True)

    def _on_voice_changed(self, block: Block, combo: QComboBox):
        block.voice_label = combo.currentData() or ""
        row = self._row_blocks.index(block) if block in getattr(self, "_row_blocks", []) else -1
        if self._assignment_filter != "all" or self._voice_filter or self._search_text:
            self._reload_table()
            return
        if row >= 0:
            self.table.setItem(row, 4, self._fit_item(block))
        self._update_stats()

    def _refresh_row_combos(self):
        # cập nhật danh sách giọng trong mọi combo của bảng
        self._reload_table()

    def _recompute_fits(self):
        for row, b in enumerate(getattr(self, "_row_blocks", [])):
            self.table.setItem(row, 4, self._fit_item(b))

    def _toggle_drift_filter(self, on: bool):
        self._only_drift = on
        self._reload_table()

    def _on_filter_changed(self):
        self._assignment_filter = self.assignment_filter_combo.currentData() or "all"
        self._voice_filter = self.voice_filter_combo.currentData() or ""
        self._reload_table()

    def _on_search_changed(self, text: str):
        self._search_text = text.strip().lower()
        self._reload_table()

    def _refresh_table_filter_voices(self):
        current = self.voice_filter_combo.currentData() or ""
        self.voice_filter_combo.blockSignals(True)
        self.voice_filter_combo.clear()
        self.voice_filter_combo.addItem("Lọc giọng", "")
        if self.project:
            for voice in self.project.voices:
                self.voice_filter_combo.addItem(voice.label, voice.label)
        idx = self.voice_filter_combo.findData(current)
        self.voice_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.voice_filter_combo.blockSignals(False)

    def _update_stats(self):
        if not self.project:
            return
        s = self.project.stats()
        vid = "✓ video" if self.project.video_path else "chưa có video"
        self.stats_label.setText(
            f"Tổng {s['total']} block · {s['active']} bật · "
            f"{s['unassigned']} chưa gán · {vid}")
        self.left_controller.refresh_voice_choices()

    def _on_table_selection_changed(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        first = self._block_at_visible_row(rows[0]) if rows else None
        self.left_controller.set_current_block(first, selected_count=len(rows))

    # -------- nghe thử / tạo lại --------
    def _preview(self, block: Block, *, regenerate: bool):
        if not self.project:
            return
        cfg = self.project.resolve_voice(block)
        if cfg is None:
            QMessageBox.warning(self, "Chưa có giọng", "Block này chưa được gán giọng.")
            return
        if not self.project.has_explicit_voice(block) and self.project.default_voice:
            self.statusBar().showMessage(
                f"Block #{block.index} đang dùng giọng mặc định `{self.project.default_voice}`.",
                4000,
            )
        self.player.play(
            block.text, cfg, self.project.locale, regenerate=regenerate,
            on_error=lambda m: self.statusBar().showMessage(f"Lỗi nghe thử: {m}", 5000),
            on_state=lambda m: self.statusBar().showMessage(m, 3000) if m else None,
        )

    def _preview_selected_block(self, block: Block):
        self._preview(block, regenerate=False)

    def _preview_source_block(self, block: Block):
        if not self.project or not self.project.video_path:
            QMessageBox.warning(self, "Chưa có video", "Hãy chọn video trước.")
            return
        self.player.play_source(
            self.project.video_path,
            start_ms=block.start_ms,
            end_ms=block.end_ms,
            on_error=lambda m: self.statusBar().showMessage(f"Lỗi nghe gốc: {m}", 5000),
            on_state=lambda m: self.statusBar().showMessage(m, 3000) if m else None,
        )

    def _apply_block_ranges(
        self,
        block_indexes: list[int],
        apply_label: str,
        default_label: str,
    ) -> int:
        if not self.project:
            return 0
        target_ids = set(block_indexes)
        changed = 0
        for block in self.project.blocks:
            if block.index in target_ids:
                block.voice_label = apply_label
                changed += 1
        if default_label:
            self.project.default_voice = default_label
        self._reload_table()
        self._update_stats()
        return changed

    # -------- render --------
    def start_render(self):
        if not self.project:
            return
        if not self.project.blocks:
            QMessageBox.warning(self, "Trống", "Chưa có block nào.")
            return
        if self.project_path is None:
            answer = QMessageBox.question(
                self,
                "Chưa lưu dự án",
                "Nên lưu dự án trước khi render để lần sau còn làm tiếp.\n\nLưu ngay bây giờ không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                self.save_project()
        default_ext = ".mp4" if self.project.video_path else ".mp3"
        out, _ = QFileDialog.getSaveFileName(
            self, "Xuất ra", self.project.name + "_dub" + default_ext,
            "Video/Audio (*.mp4 *.mkv *.wav *.mp3)")
        if not out:
            return
        self.project.keep_original_audio = self.chk_keep.isChecked()
        self.project.locale = self.locale_combo.currentText()
        self._start_worker(out, mode="final", button=self.btn_render, busy_text="⏳ Đang render…")

    def start_export_segments(self):
        if not self.project:
            return
        if not self.project.blocks:
            QMessageBox.warning(self, "Trống", "Chưa có block nào.")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất 0001.wav")
        if not out_dir:
            return
        self.project.locale = self.locale_combo.currentText()
        self._start_worker(
            out_dir,
            mode="segments",
            button=self.btn_export_segments,
            busy_text="⏳ Đang xuất segment…",
        )

    def _start_worker(self, out_path: str, *, mode: str, button: QPushButton, busy_text: str):
        self.btn_render.setEnabled(False)
        self.btn_export_segments.setEnabled(False)
        self.btn_stop.setEnabled(True)
        button.setText(busy_text)
        self.worker = RenderWorker(self.project, out_path, mode=mode)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def stop_render(self):
        if not self.worker or not self.worker.isRunning():
            return
        self.worker.stop()
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("Đã gửi lệnh dừng khẩn cấp. Chờ block đang chạy kết thúc...", 5000)

    def _on_progress(self, done: int, total: int, msg: str):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} — {msg}")

    def _on_done(self, out: str, errs: int, heavy: int):
        self.btn_render.setEnabled(True)
        self.btn_export_segments.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_render.setText("▶  Render & Xuất")
        self.btn_export_segments.setText("Xuất từng line nhỏ")
        self._save_app_state()
        QMessageBox.information(
            self, "Hoàn tất",
            f"Đã xuất:\n{out}\n\nLỗi: {errs} block · Lệch nặng: {heavy} block")

    def _on_failed(self, msg: str):
        self.btn_render.setEnabled(True)
        self.btn_export_segments.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_render.setText("▶  Render & Xuất")
        self.btn_export_segments.setText("Xuất từng line nhỏ")
        QMessageBox.critical(self, "Lỗi render", msg)

    def closeEvent(self, event):
        self.player.stop()
        if self.project and self.project_path:
            self._save_app_state()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
