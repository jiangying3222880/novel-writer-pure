"""
项目事件总线 (V4.0-P4-新)

解决 3 个问题:
  1) 小说设定页 BasicInfoWidget._on_save 改了项目基础信息, ProjectsPage 详情不刷新
  2) ProjectsPage._on_edit 改了项目, NovelSettingsPage 的 BasicInfoWidget 表单不重 load
  3) 任何地方改了 project 表/structure.json, 其他 page 都能拿到通知

设计:
  - 极简 EventBus, 3 种事件: created / updated / deleted
  - 不依赖 Qt (service 层不能用 Qt 信号, 保持纯净), 用纯 Python callback 列表
  - 同步触发 (写完立即通知), 失败不影响主流程
  - 在 project_service.create/update/delete 内部自动 publish (订阅者只需要 subscribe)

事件 payload:
  - event="project.created" / "project.updated" / "project.deleted"
  - pid:  项目 id
  - project: dict (created/updated 时附上完整 row, deleted 时为 None)
"""
from __future__ import annotations
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

# 回调签名: handler(event: str, pid: str, project: Optional[dict]) -> None
Handler = Callable[[str, str, Optional[dict]], None]


class _ProjectEventBus:
    """进程内单例 — 模块级 _bus 即可."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> Handler:
        """订阅; 返回 handler 本身 (方便 unsubscribe)."""
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)
        return handler

    def unsubscribe(self, handler: Handler) -> bool:
        with self._lock:
            try:
                self._handlers.remove(handler)
                return True
            except ValueError:
                return False

    def publish(self, event: str, pid: str, project: Optional[dict]) -> None:
        # 拷贝一份再调用, 避免回调里 unsubscribe 改 list
        with self._lock:
            handlers = list(self._handlers)
        for h in handlers:
            try:
                h(event, pid, project)
            except Exception as e:
                # 回调里报错不能影响主流程, 记 log
                log.warning("project_event_bus handler %r failed: %s", h, e)


# 模块级单例
_bus = _ProjectEventBus()


def subscribe(handler: Handler) -> Handler:
    """订阅项目变更事件. handler(event, pid, project) -> None.

    event 取值: "project.created" / "project.updated" / "project.deleted"
    """
    return _bus.subscribe(handler)


def unsubscribe(handler: Handler) -> bool:
    return _bus.unsubscribe(handler)


def publish(event: str, pid: str, project: Optional[dict] = None) -> None:
    """发布事件. 一般由 project_service 内部调用, 业务层不必直接 publish."""
    _bus.publish(event, pid, project)


def _handler_count() -> int:
    """测试用: 返回当前订阅者数."""
    with _bus._lock:
        return len(_bus._handlers)
