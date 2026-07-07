"""
I17 ImageLabel - 图像 + 缩放条.

设计参考 docs/widgets-mockup.html I17 (2026-06-10 批准).

特性:
- 加载本地图片 (file path / QPixmap)
- 缩放条 (-/+), 实时刷新
- 自适应模式 (fit-to-width) 与原始比例切换
- 状态: zoomChanged 信号
- 空状态占位 (无图片时)
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ImageLabel(QFrame):
    """图像查看器 + 缩放条."""

    zoomChanged = Signal(float)  # 当前缩放倍率 (1.0 = 原始)

    MIN_ZOOM = 0.1
    MAX_ZOOM = 5.0
    DEFAULT_ZOOM = 1.0

    def __init__(
        self,
        *,
        min_zoom: float = MIN_ZOOM,
        max_zoom: float = MAX_ZOOM,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("imageLabel")
        self.setFrameShape(QFrame.NoFrame)
        self._min_zoom = min_zoom
        self._max_zoom = max_zoom
        self._zoom = self.DEFAULT_ZOOM
        self._pixmap: Optional[QPixmap] = None
        self._placeholder_text = "无图片"

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 图像区 (滚动)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: #0a0b0d; border: 1px solid #2a2b2f; border-radius: 4px; }"
        )
        self._image_label = QLabel(self._scroll)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(200, 180)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scroll.setWidget(self._image_label)
        layout.addWidget(self._scroll, 1)

        # 缩放条
        bar = QFrame(self)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.setSpacing(8)
        self._zoom_out_btn = QPushButton("−", bar)
        self._zoom_out_btn.setFixedSize(24, 22)
        self._zoom_out_btn.clicked.connect(lambda: self.zoom_by(0.8))
        self._zoom_label = QLabel(f"{int(self._zoom * 100)}%", bar)
        self._zoom_label.setMinimumWidth(48)
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_in_btn = QPushButton("+", bar)
        self._zoom_in_btn.setFixedSize(24, 22)
        self._zoom_in_btn.clicked.connect(lambda: self.zoom_by(1.25))
        self._reset_btn = QPushButton("100%", bar)
        self._reset_btn.setFixedHeight(22)
        self._reset_btn.clicked.connect(self.reset_zoom)
        self._fit_btn = QPushButton("适应", bar)
        self._fit_btn.setFixedHeight(22)
        self._fit_btn.clicked.connect(self.fit_to_width)
        for b in (self._zoom_out_btn, self._zoom_in_btn, self._reset_btn, self._fit_btn):
            b.setCursor(Qt.PointingHandCursor)
        bar_layout.addWidget(self._zoom_out_btn)
        bar_layout.addWidget(self._zoom_label)
        bar_layout.addWidget(self._zoom_in_btn)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self._reset_btn)
        bar_layout.addWidget(self._fit_btn)
        layout.addWidget(bar)

        # 初始占位
        self._show_placeholder()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QFrame#imageLabel { background: #0a0b0d; border: 1px solid #2a2b2f; border-radius: 4px; padding: 8px; }"
            "QLabel { color: #c8cdd4; font-size: 11px; }"
            "QPushButton { background: #191a1b; color: #c8cdd4; border: 1px solid #2a2b2f; border-radius: 3px; padding: 2px 6px; }"
            "QPushButton:hover { background: #222326; }"
        )

    # ---- 公开 API ----
    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._zoom = self.DEFAULT_ZOOM
        self._render()

    def load_from_file(self, path: str) -> bool:
        if not os.path.isfile(path):
            self._show_placeholder(f"文件不存在: {path}")
            return False
        pix = QPixmap(path)
        if pix.isNull():
            self._show_placeholder(f"无法加载: {path}")
            return False
        self._pixmap = pix
        self._zoom = self.DEFAULT_ZOOM
        self._render()
        return True

    def clear(self) -> None:
        self._pixmap = None
        self._show_placeholder()

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder_text = text
        if self._pixmap is None:
            self._show_placeholder()

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        new = max(self._min_zoom, min(self._max_zoom, zoom))
        if abs(new - self._zoom) < 1e-6:
            return
        self._zoom = new
        self._render()
        self.zoomChanged.emit(self._zoom)

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def reset_zoom(self) -> None:
        self.set_zoom(self.DEFAULT_ZOOM)

    def fit_to_width(self) -> None:
        if self._pixmap is None:
            return
        w = max(self._scroll.viewport().width() - 16, 64)
        ratio = w / max(self._pixmap.width(), 1)
        self.set_zoom(ratio)

    # ---- 内部 ----
    def _render(self) -> None:
        if self._pixmap is None:
            self._show_placeholder()
            return
        if self._zoom == 1.0:
            scaled = self._pixmap
        else:
            w = max(int(self._pixmap.width() * self._zoom), 1)
            h = max(int(self._pixmap.height() * self._zoom), 1)
            scaled = self._pixmap.scaled(
                w, h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        self._image_label.setPixmap(scaled)
        self._image_label.setMinimumSize(scaled.size())
        self._image_label.setText("")
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")

    def _show_placeholder(self, text: Optional[str] = None) -> None:
        msg = text or self._placeholder_text
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText(f"🖼  {msg}")
        self._zoom_label.setText("—")
