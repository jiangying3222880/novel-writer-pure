"""
主题切换自动刷新工具 (v4.1)

背景: pages.py / tabs 中 setStyleSheet(f"color: {text_muted()}") 模式, 一旦
       应用了, 后续切换主题, 该 widget 不会自动重画. 本模块提供 3 种方式
       让 widget 在主题切换时自动重新应用样式.

使用:
    from app.ui.theme_observer import bind_theme

    class MyWidget(QWidget):
        def __init__(self):
            super().__init__()
            self._apply_dynamic_style()
            bind_theme(self, self._apply_dynamic_style)

        def _apply_dynamic_style(self):
            self.lbl.setStyleSheet(f"color: {text_muted()};")
"""
from __future__ import annotations

from typing import Callable
from weakref import WeakSet

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from app.ui.theme import get_theme

# 全局: 主题切换时回调集合 (持有弱引用, widget 销毁后自动移除)
_widgets: "WeakSet[QWidget]" = WeakSet()
_extra_callbacks: list[Callable[[str], None]] = []


def _on_theme_changed(name: str) -> None:
    """ThemeManager.changed 触发时, 重新应用所有动态样式."""
    # 1. 通知所有 bind_theme 注册的 widget
    dead: list[QWidget] = []
    for w in list(_widgets):
        if not _is_alive(w):
            dead.append(w)
            continue
        cb = getattr(w, "_theme_reapply", None)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass
    for w in dead:
        _widgets.discard(w)

    # 2. 通知其他外部回调
    for cb in _extra_callbacks:
        try:
            cb(name)
        except Exception:
            pass


def _is_alive(w: QObject) -> bool:
    """检查 QObject 是否还活着 (C++ 对象未释放)."""
    try:
        # sip.isdeleted 在 PyQt 用, PySide6 通过访问一个属性来判断
        _ = w.parent()
        return True
    except RuntimeError:
        return False


def bind_theme(widget: QWidget, reapply: Callable[[], None]) -> None:
    """注册一个 widget, 主题切换时自动调用 reapply() 重新生成样式.

    Args:
        widget:  监听的 QWidget
        reapply: 无参回调, 应重新调用 setStyleSheet(...)
    """
    widget._theme_reapply = reapply  # type: ignore[attr-defined]
    _widgets.add(widget)


def register_global_callback(cb: Callable[[str], None]) -> None:
    """注册一个全局回调, 主题切换时调用 cb(theme_name)."""
    _extra_callbacks.append(cb)


# ---- 启动钩子: ThemeManager.changed 已发, 这里挂一个 on-install 钩子 ----
_initialized = False


def ensure_hooked() -> None:
    """确保 ThemeManager.changed 信号已绑定到 _on_theme_changed."""
    global _initialized
    if _initialized:
        return
    try:
        tm = get_theme()
        tm.changed.connect(_on_theme_changed)
        _initialized = True
    except Exception:
        pass


# 主动初始化一次 (模块 import 时)
ensure_hooked()
