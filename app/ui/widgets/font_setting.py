"""
I24 FontSetting - 字体设置组件.

设计参考 docs/widgets-mockup.html I24 (2026-06-10 批准).

特性:
- 字体族 (QFontDatabase 列出可用字体)
- 字号 (QSpinBox 8..72)
- 粗体/斜体 切换
- 实时预览框
- 字体变化信号 fontChanged(family, size, bold, italic)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from app.ui.widgets._number_input import NumberInput


_PREVIEW_TEXT = "林轩缓缓抬眼, 苍穹之上, 残阳如血. 他唇角微挑, 握紧手中长剑."


class FontSetting(QFrame):
    """字体选择组件."""

    fontChanged = Signal(str, int, bool, bool)  # family, size, bold, italic

    def __init__(
        self,
        *,
        initial_family: str = "",
        initial_size: int = 13,
        initial_bold: bool = False,
        initial_italic: bool = False,
        preview_text: str = _PREVIEW_TEXT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fontSetting")
        self._preview_text = preview_text
        self._build_ui(initial_family, initial_size, initial_bold, initial_italic)
        self._apply_style()
        self._update_preview()
        self._wire_signals()

    def _build_ui(
        self,
        initial_family: str,
        initial_size: int,
        initial_bold: bool,
        initial_italic: bool,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 字体族
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("字体族:", self))
        self._family_combo = QComboBox(self)
        families = sorted({f for f in QFontDatabase.families()})
        self._family_combo.addItems(families)
        if not initial_family:
            initial_family = QFont().family()
        if initial_family in families:
            self._family_combo.setCurrentText(initial_family)
        else:
            self._family_combo.setCurrentIndex(0)
        self._family_combo.setMinimumWidth(180)
        row1.addWidget(self._family_combo, 1)
        layout.addLayout(row1)

        # 字号 + 粗体/斜体
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("字号:", self))
        self._size_spin = NumberInput(lo=8, hi=72, default=initial_size, suffix=" pt", parent=self)
        row2.addWidget(self._size_spin)
        row2.addSpacing(12)
        self._bold_chk = QCheckBox("粗体", self)
        self._bold_chk.setChecked(initial_bold)
        row2.addWidget(self._bold_chk)
        self._italic_chk = QCheckBox("斜体", self)
        self._italic_chk.setChecked(initial_italic)
        row2.addWidget(self._italic_chk)
        row2.addStretch(1)
        layout.addLayout(row2)

        # 预览
        layout.addWidget(QLabel("预览:", self))
        self._preview = QPlainTextEdit(self)
        self._preview.setPlainText(self._preview_text)
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(80)
        layout.addWidget(self._preview)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QFrame#fontSetting { background: #0a0b0d; border: 1px solid #2a2b2f; border-radius: 4px; }"
            "QLabel { color: #8a8f98; font-size: 11px; }"
            "QComboBox, QSpinBox, QPlainTextEdit { background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f; border-radius: 3px; padding: 4px 8px; }"
            "QComboBox:focus, QSpinBox:focus { border-color: #6c7ae0; }"
            "QPlainTextEdit { padding: 12px; line-height: 1.7; }"
            "QCheckBox { color: #c8cdd4; }"
        )

    def _wire_signals(self) -> None:
        self._family_combo.currentTextChanged.connect(self._on_changed)
        self._size_spin.valueChanged.connect(self._on_changed)
        self._bold_chk.stateChanged.connect(self._on_changed)
        self._italic_chk.stateChanged.connect(self._on_changed)

    def _on_changed(self, *_args) -> None:
        self._update_preview()
        self.fontChanged.emit(
            self.family(),
            self.size(),
            self.bold(),
            self.italic(),
        )

    # ---- 公开 API ----
    def family(self) -> str:
        return self._family_combo.currentText()

    def size(self) -> int:
        return self._size_spin.value()

    def bold(self) -> bool:
        return self._bold_chk.isChecked()

    def italic(self) -> bool:
        return self._italic_chk.isChecked()

    def set_family(self, family: str) -> None:
        idx = self._family_combo.findText(family)
        if idx >= 0:
            self._family_combo.setCurrentIndex(idx)

    def set_size(self, size: int) -> None:
        self._size_spin.setValue(size)

    def set_bold(self, bold: bool) -> None:
        self._bold_chk.setChecked(bold)

    def set_italic(self, italic: bool) -> None:
        self._italic_chk.setChecked(italic)

    def set_preview_text(self, text: str) -> None:
        self._preview_text = text
        self._preview.setPlainText(text)
        self._update_preview()

    def to_dict(self) -> dict:
        return {
            "family": self.family(),
            "size": self.size(),
            "bold": self.bold(),
            "italic": self.italic(),
        }

    def apply_dict(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        if "family" in data:
            self.set_family(str(data["family"]))
        if "size" in data:
            try:
                self.set_size(int(data["size"]))
            except (TypeError, ValueError):
                pass
        if "bold" in data:
            self.set_bold(bool(data["bold"]))
        if "italic" in data:
            self.set_italic(bool(data["italic"]))

    # ---- 内部 ----
    def _update_preview(self) -> None:
        f = QFont(self.family(), self.size())
        f.setBold(self.bold())
        f.setItalic(self.italic())
        self._preview.setFont(f)
