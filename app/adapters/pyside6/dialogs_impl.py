"""
app/adapters/pyside6/dialogs_impl.py - PySide6 弹窗实现 (M1 解耦第 2 步).

把 PySide6 的 Dialogs (info/warning/error/confirm/input/multiselect)
注册到 dialogs_protocol 的全局 _impl.

桌面端 main.py 启动时调一次 install() 即可.
"""
from __future__ import annotations

from typing import List, Optional

from app.core import dialogs_protocol
from app.ui.widgets.dialogs import Dialogs


class _PySide6DialogsImpl:
    """PySide6 弹窗实现 - 包装现有 Dialogs 库."""

    def info(self, title: str, message: str) -> None:
        Dialogs.info(title, message)

    def warning(self, title: str, message: str) -> None:
        Dialogs.warning(title, message)

    def error(self, title: str, message: str) -> None:
        Dialogs.error(title, message)

    def confirm(self, title: str, message: str) -> bool:
        return Dialogs.confirm(title, message)

    def input(self, title: str, label: str, default: str = "") -> Optional[str]:
        return Dialogs.input(title, label, default)

    def multiselect(self, title: str, label: str, options: List[str]) -> List[str]:
        return Dialogs.multiselect(title, label, options)


def install() -> None:
    """PySide6 宿主启动时调一次: 注入弹窗实现."""
    dialogs_protocol.set_dialogs_impl(_PySide6DialogsImpl())


def uninstall() -> None:
    """测试用: 移除实现 (强制测试未注入路径)."""
    dialogs_protocol.set_dialogs_impl(None)  # type: ignore[arg-type]
