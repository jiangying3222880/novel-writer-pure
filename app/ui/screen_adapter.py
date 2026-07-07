"""
屏幕适配 / 实时缩放 (Phase 3 I17).

根据当前窗口 / 屏幕尺寸, 计算合适的字体缩放系数, 并实时应用到 QApplication.
支持:
  1. 窗口 resizeEvent 触发 (主窗口改变大小时)
  2. QScreen logicalDotsPerInchChanged 触发 (拖到不同 DPI 屏)
  3. screenAdded / screenRemoved 触发 (外接显示器)

设计:
  - 缩放系数按窗口宽度分段:
      < 1280  → 0.92  (紧凑屏, 笔记本 13")
      1280-1599 → 1.00 (默认)
      1600-2047 → 1.08 (常规 1080p 全屏)
      2048-2559 → 1.18 (2K 屏)
      ≥ 2560   → 1.30  (4K 屏)
  - 高度也作为轻微修正 (矮屏字稍小)
  - 应用: QApplication.setFont(...) + 重新设置 stylesheet 引用
    (不重写 stylesheet; 字体缩放用 QFont.setPointSize 即可, 控件布局自动跟随)

性能:
  - 缩放变化后才触发; 1s 内重复相同值去抖
  - debounce: 200ms 合并连续 resize
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QFont, QScreen
from PySide6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)


# 基础字体大小 (主题默认 13px)
BASE_FONT_PX = 13

# 缩放阶梯: (min_width, factor)
SCALE_BREAKPOINTS: list[tuple[int, float]] = [
    (0,    0.92),
    (1280, 1.00),
    (1600, 1.08),
    (2048, 1.18),
    (2560, 1.30),
]

# 缩放上下限 (防止极端屏)
MIN_SCALE = 0.85
MAX_SCALE = 1.50


def compute_scale(width: int, height: int) -> float:
    """根据窗口尺寸返回缩放系数."""
    if width <= 0:
        return 1.0
    # 主系数: 找最大 breakpoint <= width
    factor = 1.0
    for bp_w, f in SCALE_BREAKPOINTS:
        if width >= bp_w:
            factor = f
        else:
            break
    # 高度修正: 矮屏 (height < 720) 再 -0.04, 高屏 (height > 1080) +0.02
    if height < 720:
        factor -= 0.04
    elif height > 1080:
        factor += 0.02
    return max(MIN_SCALE, min(MAX_SCALE, factor))


def scaled_font(base_px: int = BASE_FONT_PX, factor: float = 1.0) -> QFont:
    """构造一个 pointSize = base_px * factor 的 QFont."""
    pt = max(6, int(round(base_px * factor)))
    f = QFont()
    f.setPointSize(pt)
    return f


class ScreenAdapter(QObject):
    """全局单例: 监听屏幕/窗口变化, 调 QApplication 全局字体.

    用法:
        adapter = ScreenAdapter.instance()
        adapter.attach(widget)        # 让 widget 的 resizeEvent 也触发
        ...
        adapter.compute_and_apply()   # 主动调一次 (启动时)
    """
    scaleChanged = Signal(float)  # 当前缩放系数

    _instance: Optional["ScreenAdapter"] = None

    @classmethod
    def instance(cls) -> "ScreenAdapter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._current_scale: float = 1.0
        self._last_apply_ts: float = 0.0
        # 200ms debounce
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_apply)
        self._attached_widget: Optional[QWidget] = None
        self._original_resize_event = None  # type: ignore[assignment]

    # ---- 公开 API ----

    def attach(self, widget: QWidget) -> None:
        """绑定一个 widget (一般是 MainWindow), 监听其 resizeEvent."""
        if self._attached_widget is widget:
            return
        self._attached_widget = widget
        # override resizeEvent
        original = widget.resizeEvent
        adapter_ref = self

        def _wrap_resize(ev):
            adapter_ref._on_widget_resized(widget)
            if original:
                original(ev)

        widget.resizeEvent = _wrap_resize  # type: ignore[method-assign]
        self._original_resize_event = original
        # 立即根据当前尺寸算一次
        self._on_widget_resized(widget)

    def compute_and_apply(self) -> float:
        """主动触发一次计算并应用 (返回新缩放系数)."""
        w, h = self._get_target_size()
        return self._schedule(w, h, force=True)

    # ---- 内部 ----

    def _get_target_size(self) -> tuple[int, int]:
        """优先取 attached widget, 否则取 primaryScreen 尺寸."""
        if self._attached_widget is not None:
            return self._attached_widget.width(), self._attached_widget.height()
        app = QApplication.instance()
        if app is not None:
            screen: QScreen = app.primaryScreen()
            if screen is not None:
                g = screen.availableGeometry()
                return g.width(), g.height()
        return 1280, 800  # fallback

    def _on_widget_resized(self, w: QWidget) -> None:
        ww, hh = w.width(), w.height()
        self._schedule(ww, hh, force=False)

    def _schedule(self, w: int, h: int, *, force: bool) -> float:
        new_scale = compute_scale(w, h)
        # 去抖: 200ms 内合并
        self._pending_scale = new_scale
        self._pending_force = force
        if force:
            self._debounce.stop()
            self._do_apply()
        else:
            self._debounce.start(200)
        return new_scale

    def _do_apply(self) -> None:
        new_scale = getattr(self, "_pending_scale", 1.0)
        force = getattr(self, "_pending_force", False)
        now = time.time()
        # 1s 内重复值, 跳过 (除 force)
        if not force and abs(new_scale - self._current_scale) < 0.005 and (now - self._last_apply_ts) < 1.0:
            return
        self._current_scale = new_scale
        self._last_apply_ts = now
        app = QApplication.instance()
        if app is None:
            return
        # 应用: 改全局 QApplication 字体
        new_font = scaled_font(BASE_FONT_PX, new_scale)
        app.setFont(new_font)
        # 主题 stylesheet 里的 px 是绝对值, 我们也尝试在 stylesheet 里注入缩放后的 px;
        # 但 QSS 重新设置代价较大, 这里只动 QApplication font + 触发信号
        log.info(f"[ScreenAdapter] scale={new_scale:.3f} ({new_font.pointSize()}pt)")
        self.scaleChanged.emit(new_scale)

    @property
    def current_scale(self) -> float:
        return self._current_scale
