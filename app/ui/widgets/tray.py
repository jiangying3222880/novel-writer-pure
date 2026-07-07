"""
I14 SystemTray - 系统托盘.

设计参考 docs/widgets-mockup.html I14 (2026-06-10 批准).

特性:
- 自定义 QSystemTrayIcon
- 自绘程序图标 (QPixmap, 不依赖外部资源文件)
- 菜单: 显示/隐藏/退出 等可注册 action
- 双击托盘 = 触发 show_hide action
- 启动/退出消息提示
- available() 静态方法检测系统托盘可用性 (offscreen 环境返回 False)
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QWidget,
)

log = logging.getLogger(__name__)


def _build_app_icon(size: int = 22) -> QIcon:
    """生成程序图标: 圆角蓝紫渐变 + 白色 'NW' 文字."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    # 背景: 蓝紫渐变
    from PySide6.QtGui import QLinearGradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#6c7ae0"))
    grad.setColorAt(1, QColor("#4b58b0"))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, 4, 4)
    # 文字
    p.setPen(QPen(QColor("#ffffff")))
    f = p.font()
    f.setBold(True)
    f.setPointSize(max(7, size // 3))
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "NW")
    p.end()
    return QIcon(pix)


class TrayAction:
    """菜单项描述. label/icon_text/callback/separator."""

    def __init__(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        icon_text: str = "",
        separator_after: bool = False,
    ) -> None:
        self.label = label
        self.callback = callback
        self.icon_text = icon_text
        self.separator_after = separator_after


class SystemTray(QObject):
    """系统托盘封装."""

    activated = Signal(int)  # QSystemTrayIcon.ActivationReason
    messageClicked = Signal()

    def __init__(
        self,
        *,
        app_name: str = "Novel Writer",
        tooltip: str = "Novel Writer",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._app_name = app_name
        self._tooltip = tooltip
        self._actions: List[TrayAction] = []
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._available = False

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("[tray] 系统托盘不可用 (offscreen / 无托盘服务)")
            return
        # Windows / macOS 上系统托盘可用
        try:
            self._tray = QSystemTrayIcon(_build_app_icon(22), self)
            self._tray.setToolTip(self._tooltip)
            self._tray.activated.connect(self._on_activated)
            self._tray.messageClicked.connect(self.messageClicked.emit)
            self._menu = QMenu()
            self._menu.setStyleSheet(
                "QMenu { background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f; padding: 4px; }"
                "QMenu::item { padding: 6px 18px; border-radius: 2px; }"
                "QMenu::item:selected { background: rgba(108,122,224,0.2); color: #f0f1f2; }"
                "QMenu::separator { height: 1px; background: #2a2b2f; margin: 4px 0; }"
            )
            self._tray.setContextMenu(self._menu)
            self._available = True
        except Exception as e:
            log.warning("[tray] 创建托盘失败: %s", e)
            self._tray = None

    # ---- 公开 API ----
    def is_available(self) -> bool:
        """托盘功能是否可用 (offscreen 环境返回 False)."""
        return self._available

    def add_action(self, action: TrayAction) -> None:
        """注册一个菜单项. 仅在 available 时生效."""
        self._actions.append(action)
        if self._available and self._menu is not None:
            self._rebuild_menu()

    def add_separator(self) -> None:
        """追加一个分隔符."""
        if self._menu is not None and self._available:
            self._menu.addSeparator()

    def show(self) -> None:
        if self._tray is not None:
            self._tray.show()

    def hide(self) -> None:
        if self._tray is not None:
            self._tray.hide()

    def show_message(
        self,
        title: str,
        body: str,
        *,
        icon_type=QSystemTrayIcon.Information,
        timeout_ms: int = 4000,
    ) -> None:
        if self._tray is not None:
            self._tray.showMessage(title, body, icon_type, timeout_ms)

    def menu(self) -> Optional[QMenu]:
        return self._menu

    def tray(self) -> Optional[QSystemTrayIcon]:
        return self._tray

    # ---- 内部 ----
    def _rebuild_menu(self) -> None:
        if self._menu is None:
            return
        self._menu.clear()
        for act in self._actions:
            qaction = QAction(self._menu)
            if act.icon_text:
                qaction.setText(f"{act.icon_text}  {act.label}")
            else:
                qaction.setText(act.label)
            qaction.triggered.connect(act.callback)
            self._menu.addAction(qaction)
            if act.separator_after:
                self._menu.addSeparator()

    def _on_activated(self, reason: int) -> None:
        self.activated.emit(reason)
