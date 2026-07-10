"""
事件总线 (B2: 完整做 ~200 行)
- 4.0 启动后, 各模块订阅事件
- 一处发生, 所有订阅者收到
- 异步派发 (Qt Signal / Python 回调 都支持)
- v3.4 新增: async_publish (非阻塞派发) / wait_for (条件等待)
"""
from __future__ import annotations
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_logger = logging.getLogger("NovelWriter.event_bus")

# 全局单例
_bus: "EventBus | None" = None
_lock = threading.Lock()


# ────────────────────── 事件定义 ──────────────────────

@dataclass
class Event:
    name: str                            # chapter_generated / chapter_finished / ...
    data: dict = field(default_factory=dict)
    source: str = ""                     # 发出者
    timestamp: float = 0.0


# ────────────────────── 事件总线 ──────────────────────

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._lock = threading.Lock()
        self._history: list[Event] = []
        self._history_max = 200
        # v3.4: 用于 wait_for() 的条件变量, 按事件名索引
        self._cond_by_event: dict[str, threading.Condition] = {}
        self._wait_count: dict[str, int] = {}  # 各事件名等待者计数

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """订阅事件。"""
        with self._lock:
            self._subscribers.setdefault(event_name, []).append(handler)
        _logger.debug("订阅: %s -> %s", event_name, handler.__name__)

    def unsubscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """取消订阅。"""
        with self._lock:
            handlers = self._subscribers.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event_name: str, data: dict = None, source: str = "") -> int:
        """
        派发事件。返回触发的 handler 数。
        - 同步派发 (handler 异常不阻塞其他人)
        """
        event = Event(
            name=event_name,
            data=data or {},
            source=source,
            timestamp=time.time(),
        )
        with self._lock:
            handlers = list(self._subscribers.get(event_name, []))
            self._history.append(event)
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]
            # v3.4: 唤醒 wait_for() 等待者
            if self._wait_count.get(event_name, 0) > 0 and event_name in self._cond_by_event:
                self._cond_by_event[event_name].notify_all()

        for h in handlers:
            try:
                h(event)
            except Exception as e:
                _logger.exception("事件 handler %s 失败: %s", h.__name__, e)
        _logger.debug("派发 %s -> %d 个订阅者", event_name, len(handlers))
        return len(handlers)

    def get_history(self, event_name: str | None = None, limit: int = 50) -> list[Event]:
        """获取历史事件。"""
        with self._lock:
            hist = self._history
            if event_name:
                hist = [e for e in hist if e.name == event_name]
            return hist[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._history.clear()
            self._cond_by_event.clear()
            self._wait_count.clear()

    # ──────────── v3.4: async_publish / wait_for (M2.3 新增) ────────────

    def async_publish(self, event_name: str, data: dict = None, source: str = "") -> asyncio.Future:
        """
        异步派发事件。返回 asyncio.Future, 完成后是触发的 handler 数。
        - handler 仍在线程池跑 (与 publish 一样的同步派发路径)
        - 调用方可以 await 这个 future, 不阻塞主线程
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        def _do_publish() -> None:
            try:
                count = self.publish(event_name, data, source)
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, count)
            except Exception as e:
                if not future.done():
                    loop.call_soon_threadsafe(future.set_exception, e)

        t = threading.Thread(target=_do_publish, daemon=True, name=f"async-publish-{event_name}")
        t.start()
        return future

    def wait_for(
        self,
        event_name: str,
        *,
        predicate: Optional[Callable[[Event], bool]] = None,
        timeout: float = 30.0,
    ) -> Optional[Event]:
        """
        阻塞等待指定事件被 publish 一次。
        - predicate: 额外过滤, 返回 True 才算命中
        - timeout: 秒, 超时返回 None
        - 仅在主线程/订阅线程使用; 不建议在 Qt UI 线程同步阻塞 (>200ms 改用异步回调)
        """
        cond = self._cond_for(event_name)
        deadline = time.monotonic() + timeout
        with cond:
            # 先看历史里有没有已经满足条件的
            for ev in reversed(self._history):
                if ev.name == event_name and (predicate is None or predicate(ev)):
                    return ev
            # 没就等
            self._wait_count[event_name] = self._wait_count.get(event_name, 0) + 1
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    cond.wait(timeout=remaining)
                    # 醒来后看历史
                    for ev in reversed(self._history):
                        if ev.name == event_name and (predicate is None or predicate(ev)):
                            return ev
            finally:
                self._wait_count[event_name] = max(0, self._wait_count.get(event_name, 1) - 1)

    def _cond_for(self, event_name: str) -> threading.Condition:
        with self._lock:
            if event_name not in self._cond_by_event:
                self._cond_by_event[event_name] = threading.Condition(self._lock)
            return self._cond_by_event[event_name]

    def _notify_waiters(self, event_name: str) -> None:
        """publish 之后唤醒该事件的所有 wait_for 等待者。"""
        if self._wait_count.get(event_name, 0) > 0:
            cond = self._cond_by_event.get(event_name)
            if cond is not None:
                with cond:
                    cond.notify_all()


# ────────────────────── 全局访问 ──────────────────────

def get_bus() -> EventBus:
    global _bus
    with _lock:
        if _bus is None:
            _bus = EventBus()
        return _bus


def subscribe(event_name: str, handler: Callable[[Event], None]) -> None:
    get_bus().subscribe(event_name, handler)


def publish(event_name: str, data: dict = None, source: str = "") -> int:
    return get_bus().publish(event_name, data, source)


# ────────────────────── 内置事件名 ──────────────────────

class Events:
    """事件名常量 (避免拼写错误)。"""
    CHAPTER_GENERATING = "chapter.generating"          # 开始生成
    CHAPTER_GENERATED = "chapter.generated"            # 生成完 (含 tokens)
    CHAPTER_SAVED = "chapter.saved"                    # 用户保存
    CHAPTER_EVALUATED = "chapter.evaluated"            # 评估完
    CHAPTER_FINISHED = "chapter.finished"              # 全部完成 (写+评估+同步)
    # ── v3.0 Edit Signals (改稿信号 → Skill 沉淀) ──
    CHAPTER_COMMITTED = "chapter.committed"            # 章节封存 (Layer 2 触发)
    EDIT_SIGNAL_INGESTED = "edit_signal.ingested"      # 信号落盘 (Layer 1 触发)
    CANDIDATE_PROMOTED = "candidate.promoted"          # 候选 Skill 沉淀 (Layer 3 产出)
    CANDIDATE_EVOLVED = "candidate.evolved"            # 进化跑完 (Layer 4 产出)
    SKILL_INJECTED = "skill.injected"                  # 软提示注入 (Layer 5 触发)
    SUBTEXT_GENERATED = "subtext.generated"            # subtext 卡生成
    WORLD_SYNCED = "world.synced"                      # D4 世界观同步 (写完一章后)
    CONTRADICTION_FOUND = "world.contradiction_found"  # D4 矛盾检测发现
    MODEL_USED = "model.used"                          # 模型被用 (含 tokens + 费用)
    MODEL_FAILED = "model.failed"                      # 模型失败
    MODEL_FALLBACK = "model.fallback"                  # 降级到备用
    PROJECT_CREATED = "project.created"
    PROJECT_SWITCHED = "project.switched"
    APP_STARTED = "app.started"
    APP_CLOSING = "app.closing"
    # ── v4.3 StoryEngine 状态同步 ──
    STORY_STATE_UPDATED = "story.state_updated"
    STORY_UNIT_COMPLETED = "story.unit_completed"
