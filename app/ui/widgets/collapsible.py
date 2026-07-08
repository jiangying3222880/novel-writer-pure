"""
I4 CollapsiblePanel - 可折叠面板.

设计参考 docs/widgets-mockup.html I4 (2026-06-10 批准).

特性:
- 单个标题 + 内容区域, 点击标题展开/折叠
- 状态记忆 (每个实例独立)
- 标题栏支持自定义 widget (右侧额外按钮)
- toggle / expanded 信号

使用:
    panel = CollapsiblePanel("基础信息")
    panel.set_content(my_widget)
    panel.toggled.connect(my_callback)  # bool: True=展开
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import surface_bg


class CollapsiblePanel(QFrame):
    """可折叠面板. 标题 + 任意子 widget."""

    toggled = Signal(bool)  # True=展开, False=折叠

    def __init__(
        self,
        title: str = "",
        *,
        expanded: bool = True,
        collapsible: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("collapsiblePanel")
        self.setFrameShape(QFrame.NoFrame)

        self._title = title
        self._expanded = expanded
        self._collapsible = collapsible

        self._build_ui()
        self._apply_state()

    # ---- 公开 API ----
    def set_content(self, widget: QWidget) -> None:
        """设置内容 widget (替换已有)."""
        body_layout = self._body.layout()
        assert body_layout is not None
        while body_layout.count():
            item = body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        body_layout.addWidget(widget)

    def add_content(self, widget: QWidget) -> None:
        """追加内容 widget."""
        self._body.layout().addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title = title
        self._title_label.setText(title)

    def title(self) -> str:
        return self._title

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply_state()
        self.toggled.emit(expanded)

    def set_extra_widget(self, widget: QWidget) -> None:
        """在标题栏右侧添加额外 widget (如按钮)."""
        for i in range(self._extra_layout.count() - 1, -1, -1):
            item = self._extra_layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._extra_layout.addWidget(widget)

    # ---- 内部 ----
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        self._header = QWidget(self)
        self._header.setObjectName("collapsibleHeader")
        if self._collapsible:
            self._header.setCursor(QCursor(Qt.PointingHandCursor))
        self._header.setAttribute(Qt.WA_StyledBackground, True)
        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(10, 6, 8, 6)
        h_layout.setSpacing(8)

        self._arrow = QToolButton(self._header)
        self._arrow.setObjectName("collapsibleArrow")
        self._arrow.setText("▶")
        self._arrow.setFixedSize(14, 14)
        self._arrow.setFocusPolicy(Qt.NoFocus)
        self._arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._arrow.setStyleSheet(
            "QToolButton#collapsibleArrow { border: none; background: transparent; color: #8a8f98; font-size: 10px; padding: 0; }"
        )

        self._title_label = QLabel(self._title, self._header)
        self._title_label.setObjectName("collapsibleTitle")
        self._title_label.setStyleSheet(
            "QLabel#collapsibleTitle { color: #f0f1f2; font-weight: 600; font-size: 13px; background: transparent; border: none; }"
        )

        h_layout.addWidget(self._arrow)
        h_layout.addWidget(self._title_label, 1)

        # 右侧额外区域
        self._extra_layout = QHBoxLayout()
        self._extra_layout.setContentsMargins(0, 0, 0, 0)
        self._extra_layout.setSpacing(4)
        extra_w = QWidget(self._header)
        extra_w.setLayout(self._extra_layout)
        extra_w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h_layout.addWidget(extra_w, 0)

        layout.addWidget(self._header)

        # 内容区
        self._body = QWidget(self)
        self._body.setObjectName("collapsibleBody")
        self._body.setAttribute(Qt.WA_StyledBackground, True)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(4)
        self._body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(self._body)

    def _apply_state(self) -> None:
        self._body.setVisible(self._expanded)
        self._arrow.setText("▼" if self._expanded else "▶")
        header_bg = "#222326" if self._expanded else "#191a1b"
        self._header.setStyleSheet(
            f"QWidget#collapsibleHeader {{ background: {header_bg}; border-bottom: 1px solid #2a2b2f; }}"
        )
        self._body.setStyleSheet(f"QWidget#collapsibleBody {{ background: {surface_bg()}; }}")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._collapsible
            and event.button() == Qt.LeftButton
            and self._header.geometry().contains(event.position().toPoint())
        ):
            self._expanded = not self._expanded
            self._apply_state()
            self.toggled.emit(self._expanded)
            event.accept()
            return
        super().mousePressEvent(event)
