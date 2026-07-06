"""
Story Event types — 语义事实定义

Event = 不可变事实记录，不是命令。
每个 Event 描述"发生了什么"，Reducer 根据 Event 更新 State。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import time
import uuid


@dataclass(frozen=True)
class StoryEvent:
    """不可变故事事件."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    causality: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    unit_id: str = ""
    project_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "payload": dict(self.payload),
            "causality": dict(self.causality),
            "timestamp": self.timestamp,
            "unit_id": self.unit_id,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StoryEvent:
        return cls(
            id=d.get("id", ""),
            type=d.get("type", ""),
            payload=d.get("payload", {}),
            causality=d.get("causality", {}),
            timestamp=d.get("timestamp", 0.0),
            unit_id=d.get("unit_id", ""),
            project_id=d.get("project_id", ""),
        )


# 事件类型常量
class EventTypes:
    # 角色事件
    CHARACTER_STATE = "character_state"
    CHARACTER_RELATIONSHIP = "character_relationship"
    CHARACTER_KNOWLEDGE = "character_knowledge"
    CHARACTER_LOCATION = "character_location"
    CHARACTER_INVENTORY = "character_inventory"

    # 世界事件
    WORLD_STATE = "world_state"
    WORLD_LOCATION = "world_location"
    WORLD_TIME = "world_time"

    # 伏笔事件
    HOOK_PLANT = "hook_plant"
    HOOK_PAYOFF = "hook_payoff"

    # 承诺事件
    PROMISE_MADE = "promise_made"
    PROMISE_BROKEN = "promise_broken"

    # 写作事件
    UNIT_COMPLETED = "unit_completed"
    CHAPTER_GENERATED = "chapter_generated"
