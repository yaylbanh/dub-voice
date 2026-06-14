"""Controller for the left workspace panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from ..project import Block, Project
from .left_panel import LeftWorkspaceState, LeftWorkspaceView


def _fmt_ms(total_ms: int) -> str:
    total_ms = max(0, total_ms)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def parse_block_spec(spec: str) -> list[int]:
    """Parse values like `1, 3, 5-8` into subtitle block indexes."""
    values: set[int] = set()
    chunks = [part.strip() for part in spec.replace("\n", ",").split(",") if part.strip()]
    if not chunks:
        raise ValueError("Chưa nhập block cần áp dụng.")
    for chunk in chunks:
        if "-" in chunk:
            start_text, end_text = [part.strip() for part in chunk.split("-", 1)]
            start = int(start_text)
            end = int(end_text)
            if start <= 0 or end <= 0:
                raise ValueError("Block phải lớn hơn 0.")
            if end < start:
                raise ValueError(f"Dải block không hợp lệ: {chunk}")
            values.update(range(start, end + 1))
            continue
        value = int(chunk)
        if value <= 0:
            raise ValueError("Block phải lớn hơn 0.")
        values.add(value)
    return sorted(values)


class LeftWorkspaceController:
    """Bind left-panel widgets to the project and current block selection."""

    def __init__(
        self,
        view: LeftWorkspaceView,
        *,
        preview_source,
        preview_tts,
        apply_blocks,
    ):
        self.view = view
        self.project: Project | None = None
        self.current_block: Block | None = None
        self._preview_source = preview_source
        self._preview_tts = preview_tts
        self._apply_blocks = apply_blocks

        self.view.btn_listen_source.clicked.connect(self.preview_source)
        self.view.btn_listen_tts.clicked.connect(self.preview_tts)
        self.view.btn_apply.clicked.connect(self.apply_blocks_from_input)

        self._render_state()

    def set_project(self, project: Project | None) -> None:
        self.project = project
        self.current_block = project.blocks[0] if project and project.blocks else None
        self.refresh_voice_choices()
        self._render_state()

    def set_current_block(self, block: Block | None, *, selected_count: int = 0) -> None:
        self.current_block = block
        if block and selected_count > 1:
            self.view.set_status(
                f"Đang chọn {selected_count} block. Nghe thử sẽ dùng block đầu tiên."
            )
        self._render_state()

    def refresh_voice_choices(self) -> None:
        labels = [v.label for v in self.project.voices] if self.project else []
        default_label = self.project.default_voice if self.project else ""
        current_apply = self.view.apply_voice_combo.currentData() or default_label
        self.view.set_voice_choices(
            labels,
            apply_label=current_apply,
            default_label=default_label,
        )
        self._render_state()

    def preview_source(self) -> None:
        if not self.project or not self.project.video_path:
            QMessageBox.warning(self.view, "Chưa có video", "Hãy chọn video trước.")
            return
        if not self.current_block:
            QMessageBox.warning(self.view, "Chưa chọn block", "Hãy chọn một block trong bảng.")
            return
        self._preview_source(self.current_block)

    def preview_tts(self) -> None:
        if not self.current_block:
            QMessageBox.warning(self.view, "Chưa chọn block", "Hãy chọn một block trong bảng.")
            return
        self._preview_tts(self.current_block)

    def apply_blocks_from_input(self) -> None:
        if not self.project:
            QMessageBox.warning(self.view, "Chưa có dự án", "Hãy mở SRT trước.")
            return
        apply_label = self.view.apply_voice_combo.currentData() or ""
        default_label = self.view.default_voice_combo.currentData() or ""
        if not apply_label:
            QMessageBox.warning(self.view, "Chưa có giọng", "Hãy tạo hoặc chọn giọng trước.")
            return
        spec = self.view.block_input.toPlainText().strip()
        try:
            block_indexes = parse_block_spec(spec)
        except ValueError as exc:
            QMessageBox.warning(self.view, "Block không hợp lệ", str(exc))
            return
        changed = self._apply_blocks(block_indexes, apply_label, default_label)
        if not changed:
            QMessageBox.warning(
                self.view,
                "Không có block khớp",
                "Không tìm thấy block nào trùng với danh sách vừa dán.",
            )
            return
        self.view.set_status(
            f"Đã gán `{apply_label}` cho {changed} block. Giọng mặc định: {default_label}."
        )

    def _render_state(self) -> None:
        project = self.project
        block = self.current_block
        state = LeftWorkspaceState()
        if project:
            state.project_name = project.name
            state.subtitle_name = Path(project.srt_path).name if project.srt_path else "Chưa mở"
            state.video_name = Path(project.video_path).name if project.video_path else "Chưa chọn"
            state.total_blocks = len(project.blocks)
            state.preview_text = (
                f"Video: {state.video_name}\n\nPreview nhúng sẽ nối ở bước sau."
                if project.video_path
                else "Chưa chọn video\n\nDùng `Chọn video` để bật nghe gốc theo block."
            )
            state.can_preview_source = bool(project.video_path and block)
            state.can_preview_tts = bool(block)
            state.can_apply = bool(project.voices)
            if block:
                state.current_block_text = f"Block hiện tại: #{block.index}"
                state.current_time_text = (
                    f"Time: {_fmt_ms(block.start_ms)}  ->  {_fmt_ms(block.end_ms)} "
                    f"({block.slot_ms / 1000:.2f}s)"
                )
                state.status_text = "Dán danh sách block hoặc chọn block trong bảng để nghe thử."
            else:
                state.status_text = "Chưa có block nào để thao tác."
        self.view.set_state(state)
