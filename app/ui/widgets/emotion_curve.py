"""
Emotion Curve Widget (v4.0 发布模块)

用 QPainter 自绘情绪曲线 (不依赖 matplotlib)，数据源为
app.services.emotion_analyzer.analyze_emotion_curve。
情绪类型用不同颜色区分，悬停/坐标可扩展。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

_EMOTION_COLORS = {
    "tension": "#f38ba8",     # 紧张 - 红
    "climax": "#fab387",      # 高潮 - 橙
    "release": "#a6e3a1",     # 释放 - 绿
    "dip": "#6c7086",         # 低谷 - 灰
    "rise": "#89b4fa",        # 上升 - 蓝
}


class EmotionCurveWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list = []
        self._title = "情绪曲线"
        self.setMinimumHeight(160)
        self._label = QLabel(self._title)
        self._label.setStyleSheet("font-size: 12px; color: #a6adc8;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._label)
        self._plot = _Plot(self)
        lay.addWidget(self._plot, 1)

    # -------------------------------------------------------------- #
    def set_text(self, text: str) -> None:
        from app.services.emotion_analyzer import analyze_emotion_curve
        self._text = text or ""
        try:
            self._points = analyze_emotion_curve(self._text)
        except Exception:
            self._points = []
        self._plot.set_points(self._points)
        n = len(self._points)
        self._label.setText(f"情绪曲线 · {n} 个采样点")
        self._plot.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self._label.setText(title)


class _Plot(QWidget):
    """纯 QPainter 折线图."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list = []
        self.setMinimumHeight(120)

    def set_points(self, points: list) -> None:
        self._points = points

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 14
        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)

        # 背景
        painter.fillRect(0, 0, w, h, QColor("#181825"))

        # 中线 (intensity=0.5)
        mid_y = pad_t + plot_h * 0.5
        painter.setPen(QPen(QColor("#313244"), 1))
        painter.drawLine(pad_l, mid_y, pad_l + plot_w, mid_y)

        if not self._points:
            painter.setPen(QColor("#6c7086"))
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(pad_l + 4, pad_t + plot_h * 0.5,
                             "（暂无文本可分析）")
            return

        n = len(self._points)
        max_pos = max((p.position for p in self._points), default=1) or 1

        pts = []
        for p in self._points:
            x = pad_l + (p.position / max_pos) * plot_w if max_pos else pad_l
            y = pad_t + (1.0 - p.intensity) * plot_h
            pts.append((x, y, p.emotion_type))

        # 折线
        pen = QPen(QColor("#9399b2"), 1.5)
        painter.setPen(pen)
        for i in range(1, len(pts)):
            painter.drawLine(
                int(pts[i - 1][0]), int(pts[i - 1][1]),
                int(pts[i][0]), int(pts[i][1]),
            )

        # 采样点 (按情绪着色)
        for x, y, etype in pts:
            color = QColor(_EMOTION_COLORS.get(etype, "#cdd6f4"))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            r = 3
            painter.drawEllipse(int(x) - r, int(y) - r, r * 2, r * 2)

        # 图例
        painter.setPen(QColor("#6c7086"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        legend = "   ".join(
            f"●{k}" for k in ("tension", "climax", "release", "rise", "dip")
        )
        painter.drawText(pad_l, h - 2, legend)
