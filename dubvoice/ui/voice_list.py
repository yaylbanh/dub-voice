"""Saved voice list widgets for the right-side panel."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class VoiceListRow(QWidget):
    play_requested = Signal(str)
    edit_requested = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, label: str, color: str, *, is_default: bool = False):
        super().__init__()
        self.label = label
        self._build_ui(color, is_default)

    def _build_ui(self, color: str, is_default: bool) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(8)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color};font-size:14px;")
        root.addWidget(dot)

        name = label_text = self.label
        if is_default:
            label_text = f"{label_text} (mặc định)"
        self.name_label = QLabel(label_text)
        self.name_label.setStyleSheet("color:#111827;")
        root.addWidget(self.name_label, 1)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(30)
        self.play_btn.clicked.connect(lambda: self.play_requested.emit(self.label))
        root.addWidget(self.play_btn)

        self.edit_btn = QPushButton("✎")
        self.edit_btn.setFixedWidth(30)
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.label))
        root.addWidget(self.edit_btn)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setFixedWidth(26)
        self.menu_btn.clicked.connect(lambda: self.menu_requested.emit(self.label, self.menu_btn))
        root.addWidget(self.menu_btn)


class VoiceListCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { border:1px solid #e5e7eb; border-radius:10px; background:#fafafa; }"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

