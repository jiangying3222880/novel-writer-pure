"""
UIStateBridge — v4 StoryState → UI 事件同步.

订阅 v4 状态变更, 转换为 UIEvent 发布到 app.core.event_bus.
UI 组件通过 EventBus 订阅这些事件来刷新界面.

设计原则:
  - UI 不持有状态, 只订阅 diff
  - 所有变更走 Event, 没有 Event 之外的 mutation
  - 桥接层只做翻译, 不做决策
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Optional

from story.state.story_state import StoryState, StateDiff

_logger = logging.getLogger("NovelWriter.story.ui_bridge")


class UIStateBridge:
    """v4 StoryState → UI 事件桥接.

    用法:
        bridge = UIStateBridge()
        bridge.on_state_change(old_state, new_state, diff)

    或注册回调:
        bridge.subscribe("state_updated", my_handler)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = {}
        self._event_bus = None

    def _get_bus(self):
        """延迟获取 EventBus, 避免启动时循环导入."""
        if self._event_bus is None:
            try:
                from app.core.event_bus import get_bus
                self._event_bus = get_bus()
            except ImportError:
                _logger.debug("EventBus 不可用, 使用本地回调模式")
        return self._event_bus

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """注册本地回调."""
        self._subscribers.setdefault(event_name, []).append(handler)

    def on_state_change(
        self,
        old_state: StoryState | None,
        new_state: StoryState,
        state_diff: StateDiff,
    ) -> None:
        """状态变更时调用. 发布 UI 事件到 EventBus.

        Args:
            old_state: 变更前的状态 (None 表示首次加载)
            new_state: 变更后的状态
            state_diff: diff 计算结果
        """
        if not state_diff.has_changes and old_state is not None:
            return

        # 构建 UI 事件 payload
        payload = {
            "unit_id": new_state.unit_id,
            "has_changes": state_diff.has_changes,
            "total_changes": state_diff.total_changes(),
            "character_changes": state_diff.character_changes,
            "hook_changes": state_diff.hook_changes,
            "world_changes": state_diff.world_changes,
            "commitment_changes": state_diff.commitment_changes,
            # 快照: 当前状态摘要 (给 UI 做 HUD 展示)
            "snapshot": {
                "title": new_state.title,
                "phase": new_state.phase,
                "step": f"{new_state.current_step}/{new_state.total_steps}",
                "pov": new_state.pov_character,
                "active_hooks": new_state.active_hooks_count(),
                "pending_commitments": len(new_state.pending_commitments()),
                "character_count": len(new_state.characters),
                "world_location": new_state.world.location,
                "world_time": new_state.world.time_label,
            },
        }

        # 发布到 EventBus
        bus = self._get_bus()
        if bus is not None:
            try:
                bus.publish("story.state_updated", payload, source="v4_bridge")
            except Exception as e:
                _logger.warning("发布 story.state_updated 失败: %s", e)

        # 触发本地回调
        for handler in self._subscribers.get("state_updated", []):
            try:
                handler(payload)
            except Exception as e:
                _logger.exception("本地回调 state_updated 失败: %s", e)

    def on_unit_completed(
        self,
        project_id: str,
        unit_id: str,
        result: dict[str, Any],
    ) -> None:
        """Unit 写作完成时调用. 发布完成事件."""
        payload = {
            "project_id": project_id,
            "unit_id": unit_id,
            "strategy": result.get("strategy"),
            "signal_count": result.get("signal_count", 0),
            "prompt_tokens": result.get("prompt_tokens", 0),
        }

        bus = self._get_bus()
        if bus is not None:
            try:
                bus.publish("story.unit_completed", payload, source="v4_bridge")
            except Exception as e:
                _logger.warning("发布 story.unit_completed 失败: %s", e)

        for handler in self._subscribers.get("unit_completed", []):
            try:
                handler(payload)
            except Exception as e:
                _logger.exception("本地回调 unit_completed 失败: %s", e)


# 全局单例
_bridge: UIStateBridge | None = None


def get_bridge() -> UIStateBridge:
    """获取全局 UIStateBridge 实例."""
    global _bridge
    if _bridge is None:
        _bridge = UIStateBridge()
    return _bridge
