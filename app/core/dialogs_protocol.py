"""
dialogs_protocol.py - 宿主无关的弹窗协议 (M1 解耦第 1 步).

核心业务用这个, 不直接 import PySide6.
具体实现由宿主 (PySide6 桌面 / WebView / CLI) 通过 set_dialogs_impl 注入.

用法:
  # 业务层
  from app.core.dialogs_protocol import info, warning, error, confirm
  info("标题", "内容")

  # 宿主启动时 (PySide6 桌面 main.py)
  from app.adapters.pyside6.dialogs_impl import install
  install()
"""
from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class DialogsProtocol(Protocol):
    """弹窗协议. 所有宿主 (PySide6 / Web / CLI) 必须实现."""
    def info(self, title: str, message: str) -> None: ...
    def warning(self, title: str, message: str) -> None: ...
    def error(self, title: str, message: str) -> None: ...
    def confirm(self, title: str, message: str) -> bool: ...
    def input(self, title: str, label: str, default: str = "") -> Optional[str]: ...
    def multiselect(self, title: str, label: str, options: List[str]) -> List[str]: ...


# 全局注册 (由宿主启动时注入)
_impl: Optional[DialogsProtocol] = None


def set_dialogs_impl(impl: DialogsProtocol) -> None:
    """宿主启动时调用, 注入具体实现."""
    global _impl
    _impl = impl


def get_dialogs_impl() -> Optional[DialogsProtocol]:
    """测试用: 拿到当前实现, 可用于 monkey-patch."""
    return _impl


def _require() -> DialogsProtocol:
    if _impl is None:
        raise RuntimeError(
            "Dialogs 实现未注入. "
            "请在宿主启动时调 app.adapters.pyside6.dialogs_impl.install() (或对应宿主)"
        )
    return _impl


# === 业务层 API ===
def info(title: str, message: str) -> None:
    _require().info(title, message)


def warning(title: str, message: str) -> None:
    _require().warning(title, message)


def error(title: str, message: str) -> None:
    _require().error(title, message)


def confirm(title: str, message: str) -> bool:
    return _require().confirm(title, message)


def input_text(title: str, label: str, default: str = "") -> Optional[str]:
    """input 是 Python 内置函数, 业务层用 input_text 避免冲突."""
    return _require().input(title, label, default)


def multiselect(title: str, label: str, options: List[str]) -> List[str]:
    return _require().multiselect(title, label, options)
