"""
app/adapters/headless/dialogs_impl.py - 无 GUI 弹窗实现.

适用场景:
- VS Code 扩展宿主 (核心进程跑在 Node 旁边, 不需要 QApplication)
- HTTP bridge (核心库作为后台服务运行, 弹窗走 HTTP 回传到 VS Code)
- CI/自动化测试 (不能弹窗)

行为:
- info/warning/error: 写 logger + 收集到 _log 队列, 可由宿主异步拉走
- confirm: 返回 _default_confirm 字段 (默认 True)
- input: 返回 _default_input 字段 (默认 "")
- multiselect: 返回 _default_multiselect 字段 (默认空列表)
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.core import dialogs_protocol

logger = logging.getLogger("nw.headless_dialogs")


class HeadlessDialogsImpl:
    """无 GUI 弹窗实现. 所有方法都不阻塞, 不弹窗."""

    def __init__(self) -> None:
        self.log: List[dict] = []  # [{kind, title, message, ts}, ...]
        self._default_confirm: bool = True
        self._default_input: str = ""
        self._default_multiselect: List[str] = []

    def set_defaults(
        self,
        confirm: Optional[bool] = None,
        input_text: Optional[str] = None,
        multiselect: Optional[List[str]] = None,
    ) -> None:
        """测试用: 注入返回值."""
        if confirm is not None:
            self._default_confirm = confirm
        if input_text is not None:
            self._default_input = input_text
        if multiselect is not None:
            self._default_multiselect = list(multiselect)

    def info(self, title: str, message: str) -> None:
        self._record("info", title, message)
        logger.info("[headless] %s: %s", title, message)

    def warning(self, title: str, message: str) -> None:
        self._record("warning", title, message)
        logger.warning("[headless] %s: %s", title, message)

    def error(self, title: str, message: str) -> None:
        self._record("error", title, message)
        logger.error("[headless] %s: %s", title, message)

    def confirm(self, title: str, message: str) -> bool:
        self._record("confirm", title, message)
        return self._default_confirm

    def input(self, title: str, label: str, default: str = "") -> Optional[str]:
        self._record("input", title, f"{label} (default={default!r})")
        return self._default_input or default or None

    def multiselect(self, title: str, label: str, options: List[str]) -> List[str]:
        self._record("multiselect", title, f"{label} options={options}")
        return list(self._default_multiselect)

    def _record(self, kind: str, title: str, message: str) -> None:
        import time
        self.log.append({"kind": kind, "title": title, "message": message, "ts": time.time()})

    def get_log(self, kind: Optional[str] = None) -> List[dict]:
        if kind is None:
            return list(self.log)
        return [e for e in self.log if e["kind"] == kind]

    def clear_log(self) -> None:
        self.log.clear()


# 模块级单例 (供 install() 共享)
_instance: Optional[HeadlessDialogsImpl] = None


def install() -> HeadlessDialogsImpl:
    """注册 headless 实现. 返回单例, 方便测试用 get/set."""
    global _instance
    if _instance is None:
        _instance = HeadlessDialogsImpl()
    dialogs_protocol.set_dialogs_impl(_instance)
    return _instance


def uninstall() -> None:
    dialogs_protocol.set_dialogs_impl(None)  # type: ignore[arg-type]
    global _instance
    _instance = None


def get_instance() -> Optional[HeadlessDialogsImpl]:
    """测试用: 拿 headless 单例."""
    return _instance
