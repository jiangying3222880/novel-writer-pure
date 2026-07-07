"""
I6 DialogLibrary - 弹窗库.

设计参考 docs/widgets-mockup.html I6 (2026-06-10 批准).

5 类标准弹窗, 统一暗色样式 (与全局主题同步):
- ConfirmDialog: 确认/取消 (含危险样式)
- InputDialog: 单行输入
- MultiSelectDialog: 多选 (返回 list[str])
- ProgressDialog (QDialog 框架): 含子 widget 的子窗口
- SubWindowDialog: 承载任意 QWidget 的通用子窗口

辅助函数 Dialogs.confirm/input/multiselect/sub/info/warning/error
返回 (accepted, value) 风格数据.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# ---- 暗色统一样式 (与 theme.py 同步) ----
_DARK_DIALOG_QSS = """
QDialog { background: #0f1011; }
QLabel { color: #c8cdd4; }
QLabel#dlgTitle { color: #f0f1f2; font-size: 14px; font-weight: 600; }
QLabel#dlgMessage { color: #c8cdd4; font-size: 13px; }
QLabel#dlgHint { color: #8a8f98; font-size: 11px; }
QFrame#dlgHeader { background: #0a0b0d; border-bottom: 1px solid #2a2b2f; }
QFrame#dlgFooter { background: #0a0b0d; border-top: 1px solid #2a2b2f; }
QPushButton {
    background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f;
    border-radius: 4px; padding: 6px 14px; font-size: 13px;
}
QPushButton:hover { background: #222326; border-color: #3a3b3e; }
QPushButton#primaryAction { background: #6c7ae0; color: #ffffff; border: none; font-weight: 600; }
QPushButton#primaryAction:hover { background: #7d8aff; }
QPushButton#dangerAction { background: #d6443c; color: #ffffff; border: none; font-weight: 600; }
QPushButton#dangerAction:hover { background: #e55550; }
QLineEdit, QPlainTextEdit, QListWidget {
    background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f;
    border-radius: 4px; padding: 4px 6px; selection-background-color: rgba(108,122,224,0.3);
}
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: rgba(108,122,224,0.18); color: #f0f1f2; }
"""


def _apply_dark_qss(dialog: QDialog) -> None:
    dialog.setStyleSheet(_DARK_DIALOG_QSS)


# ============== 1) 确认弹窗 ==============

class ConfirmDialog(QDialog):
    """确认弹窗. 支持 danger 样式."""

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_text: str = "确定",
        cancel_text: str = "取消",
        hint: str = "",
        danger: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        _apply_dark_qss(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setObjectName("dlgHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        title_label = QLabel(f"{'⚠' if danger else '✓'} {title}", header)
        title_label.setObjectName("dlgTitle")
        h.addWidget(title_label)
        layout.addWidget(header)

        # Body
        body = QWidget(self)
        b = QVBoxLayout(body)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(8)
        msg = QLabel(message, body)
        msg.setObjectName("dlgMessage")
        msg.setWordWrap(True)
        b.addWidget(msg)
        if hint:
            hint_lbl = QLabel(hint, body)
            hint_lbl.setObjectName("dlgHint")
            hint_lbl.setWordWrap(True)
            b.addWidget(hint_lbl)
        b.addStretch(1)
        layout.addWidget(body, 1)

        # Footer
        footer = QFrame(self)
        footer.setObjectName("dlgFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 10, 16, 10)
        f.addStretch(1)
        self._cancel_btn = QPushButton(cancel_text, footer)
        self._cancel_btn.clicked.connect(self.reject)
        f.addWidget(self._cancel_btn)
        self._confirm_btn = QPushButton(confirm_text, footer)
        self._confirm_btn.setObjectName("dangerAction" if danger else "primaryAction")
        self._confirm_btn.setDefault(True)
        self._confirm_btn.clicked.connect(self.accept)
        f.addWidget(self._confirm_btn)
        layout.addWidget(footer)


# ============== 2) 输入弹窗 ==============

class InputDialog(QDialog):
    """单行输入弹窗 (可 multiline)."""

    def __init__(
        self,
        title: str,
        label: str,
        *,
        initial: str = "",
        placeholder: str = "",
        multiline: bool = False,
        confirm_text: str = "保存",
        cancel_text: str = "取消",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        _apply_dark_qss(self)

        self._value: str = initial
        self._multiline = multiline

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setObjectName("dlgHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        title_label = QLabel(title, header)
        title_label.setObjectName("dlgTitle")
        h.addWidget(title_label)
        layout.addWidget(header)

        # Body
        body = QWidget(self)
        b = QVBoxLayout(body)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(6)
        lbl = QLabel(label, body)
        lbl.setObjectName("dlgMessage")
        b.addWidget(lbl)
        if multiline:
            self._editor = QPlainTextEdit(body)
            self._editor.setPlainText(initial)
            self._editor.setMinimumHeight(120)
        else:
            self._editor = QLineEdit(body)
            self._editor.setText(initial)
            if placeholder:
                self._editor.setPlaceholderText(placeholder)
            self._editor.selectAll()
        b.addWidget(self._editor)
        layout.addWidget(body, 1)

        # Footer
        footer = QFrame(self)
        footer.setObjectName("dlgFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 10, 16, 10)
        f.addStretch(1)
        cancel_btn = QPushButton(cancel_text, footer)
        cancel_btn.clicked.connect(self.reject)
        f.addWidget(cancel_btn)
        ok_btn = QPushButton(confirm_text, footer)
        ok_btn.setObjectName("primaryAction")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        f.addWidget(ok_btn)
        layout.addWidget(footer)

    def value(self) -> str:
        return self._value

    def _on_ok(self) -> None:
        if self._multiline:
            self._value = self._editor.toPlainText().strip()
        else:
            self._value = self._editor.text().strip()
        self.accept()


# ============== 3) 多选弹窗 ==============

class MultiSelectDialog(QDialog):
    """多选弹窗. items: List[(label, checked, hint)]; 返回选中 label 列表."""

    def __init__(
        self,
        title: str,
        items: Sequence[Tuple[str, bool, str]],
        *,
        confirm_text: str = "确定",
        cancel_text: str = "取消",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        _apply_dark_qss(self)

        self._checkboxes: List[QCheckBox] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setObjectName("dlgHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        title_label = QLabel(title, header)
        title_label.setObjectName("dlgTitle")
        h.addWidget(title_label)
        layout.addWidget(header)

        # Body (滚动)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget(scroll)
        b = QVBoxLayout(body)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(6)
        for label, checked, hint in items:
            cb = QCheckBox(label, body)
            cb.setChecked(checked)
            self._checkboxes.append(cb)
            b.addWidget(cb)
            if hint:
                h_lbl = QLabel(f"  {hint}", body)
                h_lbl.setObjectName("dlgHint")
                b.addWidget(h_lbl)
        b.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        # Footer
        footer = QFrame(self)
        footer.setObjectName("dlgFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 10, 16, 10)
        f.addStretch(1)
        cancel_btn = QPushButton(cancel_text, footer)
        cancel_btn.clicked.connect(self.reject)
        f.addWidget(cancel_btn)
        ok_btn = QPushButton(confirm_text, footer)
        ok_btn.setObjectName("primaryAction")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        f.addWidget(ok_btn)
        layout.addWidget(footer)

    def selected_labels(self) -> List[str]:
        return [cb.text() for cb in self._checkboxes if cb.isChecked()]


# ============== 4) 子窗口 (任意 QWidget 容器) ==============

class SubWindowDialog(QDialog):
    """承载任意 QWidget 的子窗口."""

    def __init__(
        self,
        title: str,
        widget: QWidget,
        *,
        width: int = 520,
        height: int = 400,
        confirm_text: str = "关闭",
        show_buttons: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, height)
        _apply_dark_qss(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setObjectName("dlgHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        title_label = QLabel(title, header)
        title_label.setObjectName("dlgTitle")
        h.addWidget(title_label)
        layout.addWidget(header)

        # Body
        layout.addWidget(widget, 1)

        # Footer
        if show_buttons:
            footer = QFrame(self)
            footer.setObjectName("dlgFooter")
            footer.setAttribute(Qt.WA_StyledBackground, True)
            f = QHBoxLayout(footer)
            f.setContentsMargins(16, 10, 16, 10)
            f.addStretch(1)
            ok_btn = QPushButton(confirm_text, footer)
            ok_btn.setObjectName("primaryAction")
            ok_btn.clicked.connect(self.accept)
            f.addWidget(ok_btn)
            layout.addWidget(footer)


# ============== 便捷调用 ==============

class Dialogs:
    """便捷调用入口. 全部返回 (accepted: bool, value)."""

    @staticmethod
    def confirm(
        title: str,
        message: str,
        *,
        hint: str = "",
        danger: bool = False,
        confirm_text: str = "确定",
        cancel_text: str = "取消",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, None]:
        dlg = ConfirmDialog(
            title, message,
            hint=hint, danger=danger,
            confirm_text=confirm_text, cancel_text=cancel_text,
            parent=parent,
        )
        ok = dlg.exec() == QDialog.Accepted
        return (ok, None)

    @staticmethod
    def input(
        title: str,
        label: str,
        *,
        initial: str = "",
        placeholder: str = "",
        multiline: bool = False,
        confirm_text: str = "保存",
        cancel_text: str = "取消",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, str]:
        dlg = InputDialog(
            title, label,
            initial=initial, placeholder=placeholder, multiline=multiline,
            confirm_text=confirm_text, cancel_text=cancel_text,
            parent=parent,
        )
        if dlg.exec() == QDialog.Accepted:
            return (True, dlg.value())
        return (False, "")

    @staticmethod
    def multiselect(
        title: str,
        items: Sequence[Tuple[str, bool, str]],
        *,
        confirm_text: str = "确定",
        cancel_text: str = "取消",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, List[str]]:
        dlg = MultiSelectDialog(
            title, items,
            confirm_text=confirm_text, cancel_text=cancel_text,
            parent=parent,
        )
        if dlg.exec() == QDialog.Accepted:
            return (True, dlg.selected_labels())
        return (False, [])

    @staticmethod
    def sub(
        title: str,
        widget: QWidget,
        *,
        width: int = 520,
        height: int = 400,
        confirm_text: str = "关闭",
        show_buttons: bool = True,
        parent: Optional[QWidget] = None,
    ) -> bool:
        dlg = SubWindowDialog(
            title, widget,
            width=width, height=height,
            confirm_text=confirm_text, show_buttons=show_buttons,
            parent=parent,
        )
        return dlg.exec() == QDialog.Accepted

    @staticmethod
    def info(
        title: str,
        message: str,
        *,
        hint: str = "",
        ok_text: str = "好的",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, None]:
        """信息提示弹窗 (替代 QMessageBox.information)."""
        return Dialogs._notify(
            title, message,
            hint=hint, ok_text=ok_text,
            danger=False, parent=parent,
        )

    @staticmethod
    def warning(
        title: str,
        message: str,
        *,
        hint: str = "",
        ok_text: str = "好的",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, None]:
        """警告提示弹窗 (替代 QMessageBox.warning)."""
        return Dialogs._notify(
            title, message,
            hint=hint, ok_text=ok_text,
            danger=True, parent=parent,
        )

    @staticmethod
    def error(
        title: str,
        message: str,
        *,
        hint: str = "",
        ok_text: str = "好的",
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, None]:
        """错误提示弹窗 (替代 QMessageBox.critical)."""
        return Dialogs._notify(
            title, message,
            hint=hint, ok_text=ok_text,
            danger=True, parent=parent,
        )

    @staticmethod
    def _notify(
        title: str,
        message: str,
        *,
        hint: str = "",
        ok_text: str = "好的",
        danger: bool = False,
        parent: Optional[QWidget] = None,
    ) -> Tuple[bool, None]:
        """
        单按钮通知弹窗 (内部使用, 不导出).
        - 统一暗色样式
        - danger=True 时按钮变红 (warning/error)
        """
        dlg = QDialog(parent)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.setMinimumWidth(380)
        _apply_dark_qss(dlg)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(dlg)
        header.setObjectName("dlgHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        icon_char = "⚠" if danger else "ℹ"
        title_label = QLabel(f"{icon_char} {title}", header)
        title_label.setObjectName("dlgTitle")
        h.addWidget(title_label)
        layout.addWidget(header)

        # Body
        body = QWidget(dlg)
        b = QVBoxLayout(body)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(8)
        msg = QLabel(message, body)
        msg.setObjectName("dlgMessage")
        msg.setWordWrap(True)
        b.addWidget(msg)
        if hint:
            hint_lbl = QLabel(hint, body)
            hint_lbl.setObjectName("dlgHint")
            hint_lbl.setWordWrap(True)
            b.addWidget(hint_lbl)
        b.addStretch(1)
        layout.addWidget(body, 1)

        # Footer
        footer = QFrame(dlg)
        footer.setObjectName("dlgFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 10, 16, 10)
        f.addStretch(1)
        ok_btn = QPushButton(ok_text, footer)
        ok_btn.setObjectName("dangerAction" if danger else "primaryAction")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dlg.accept)
        f.addWidget(ok_btn)
        layout.addWidget(footer)

        dlg.exec()
        return (True, None)
