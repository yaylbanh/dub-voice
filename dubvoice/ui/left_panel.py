"""Left workspace view for the voice-mapping flow."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class LeftWorkspaceState:
    project_name: str = "Chưa mở dự án"
    subtitle_name: str = "Chưa mở SRT"
    video_name: str = "Chưa chọn video"
    total_blocks: int = 0
    current_block_text: str = "Block hiện tại: --"
    current_time_text: str = "Time: --"
    preview_text: str = "Chưa chọn video"
    status_text: str = "Mở SRT để bắt đầu gán giọng theo block."
    can_preview_source: bool = False
    can_preview_tts: bool = False
    can_apply: bool = False


class LeftWorkspaceView(QFrame):
    """Pure view for the left workspace column."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(self._section_title("Video gốc"))

        self.preview_card = QLabel("Chưa chọn video")
        self.preview_card.setAlignment(Qt.AlignCenter)
        self.preview_card.setMinimumHeight(210)
        self.preview_card.setStyleSheet(
            "background:#111827;color:#e5e7eb;border:1px solid #374151;"
            "border-radius:10px;padding:16px;font-weight:600;"
        )
        root.addWidget(self.preview_card)

        self.video_meta = QLabel("Video: Chưa chọn")
        self.time_meta = QLabel("00:00:00.000  ->  00:00:00.000")
        self.video_meta.setStyleSheet("color:#4b5563;")
        self.time_meta.setStyleSheet("color:#4b5563;")
        root.addWidget(self.video_meta)
        root.addWidget(self.time_meta)

        transport = QHBoxLayout()
        self.btn_prev_block = QPushButton("⏮")
        self.btn_play_pause = QPushButton("⏯")
        self.btn_next_block = QPushButton("⏭")
        self.btn_capture = QPushButton("⧉")
        for btn in (
            self.btn_prev_block,
            self.btn_play_pause,
            self.btn_next_block,
            self.btn_capture,
        ):
            btn.setEnabled(False)
            btn.setFixedWidth(40)
            transport.addWidget(btn)
        transport.addStretch(1)
        root.addLayout(transport)

        listen_row = QHBoxLayout()
        self.btn_listen_source = QPushButton("🔊 Nghe gốc")
        self.btn_listen_tts = QPushButton("🎙 Nghe TTS")
        self.btn_listen_source.setStyleSheet(
            "background:#16a34a;color:white;font-weight:600;padding:6px 10px;"
        )
        self.btn_listen_tts.setStyleSheet("padding:6px 10px;")
        listen_row.addWidget(self.btn_listen_source)
        listen_row.addWidget(self.btn_listen_tts)
        root.addLayout(listen_row)

        self.current_block_label = QLabel("Block hiện tại: --")
        self.current_time_label = QLabel("Time: --")
        self.project_meta_label = QLabel("Dự án: Chưa mở")
        self.subtitle_meta_label = QLabel("File sub: Chưa mở")
        for label in (
            self.current_block_label,
            self.current_time_label,
            self.project_meta_label,
            self.subtitle_meta_label,
        ):
            label.setWordWrap(True)
            label.setStyleSheet("color:#374151;")
            root.addWidget(label)

        root.addWidget(self._separator())
        root.addWidget(self._section_title("Dán danh sách block"))

        hint = QLabel("Ví dụ: 1, 3, 5-8, 12, 20-25")
        hint.setStyleSheet("color:#6b7280;")
        root.addWidget(hint)

        self.block_input = QTextEdit()
        self.block_input.setPlaceholderText("Mỗi dòng 1 số hoặc dải block cần gán.")
        self.block_input.setMinimumHeight(120)
        root.addWidget(self.block_input)

        root.addWidget(QLabel("Label giọng áp dụng"))
        self.apply_voice_combo = QComboBox()
        root.addWidget(self.apply_voice_combo)

        root.addWidget(QLabel("Giọng mặc định"))
        self.default_voice_combo = QComboBox()
        root.addWidget(self.default_voice_combo)

        self.btn_apply = QPushButton("✔ Áp dụng")
        self.btn_apply.setStyleSheet(
            "background:#16a34a;color:white;font-weight:700;padding:8px 12px;"
        )
        root.addWidget(self.btn_apply)

        self.status_label = QLabel("Mở SRT để bắt đầu gán giọng theo block.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#6b7280;")
        root.addWidget(self.status_label)

        root.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(f"<b>{text}</b>")
        label.setStyleSheet("font-size:16px;color:#111827;")
        return label

    def _separator(self) -> QWidget:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e5e7eb;")
        return line

    def set_state(self, state: LeftWorkspaceState) -> None:
        self.preview_card.setText(state.preview_text)
        self.video_meta.setText(f"Video: {state.video_name}")
        self.time_meta.setText(f"{state.total_blocks} block")
        self.current_block_label.setText(state.current_block_text)
        self.current_time_label.setText(state.current_time_text)
        self.project_meta_label.setText(f"Dự án: {state.project_name}")
        self.subtitle_meta_label.setText(f"File sub: {state.subtitle_name}")
        self.status_label.setText(state.status_text)
        self.btn_listen_source.setEnabled(state.can_preview_source)
        self.btn_listen_tts.setEnabled(state.can_preview_tts)
        self.btn_apply.setEnabled(state.can_apply)

    def set_voice_choices(
        self,
        labels: list[str],
        *,
        apply_label: str = "",
        default_label: str = "",
    ) -> None:
        self._fill_combo(self.apply_voice_combo, labels, apply_label)
        self._fill_combo(self.default_voice_combo, labels, default_label)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _fill_combo(self, combo: QComboBox, labels: list[str], selected: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label in labels:
            combo.addItem(label, label)
        if selected:
            idx = combo.findData(selected)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        elif combo.count():
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
