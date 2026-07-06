"""
Narrative strategies — the four fundamental decisions the system can make
when multiple Guides push in different directions.

DELAY   — defer this thread; maintain tension, don't resolve yet
EXPLODE — accelerate; resolve hooks, deliver payoff now
RESOLVE — pick one path and commit; discard alternatives
DETOUR  — introduce a twist; subvert the obvious direction
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Strategy(Enum):
    DELAY = "delay"
    EXPLODE = "explode"
    RESOLVE = "resolve"
    DETOUR = "detour"


STRATEGY_LABELS: dict[Strategy, str] = {
    Strategy.DELAY: "延后",
    Strategy.EXPLODE: "爆发",
    Strategy.RESOLVE: "收束",
    Strategy.DETOUR: "转向",
}

STRATEGY_DESCRIPTIONS: dict[Strategy, str] = {
    Strategy.DELAY: "暂缓推进，保持张力，不急于兑现",
    Strategy.EXPLODE: "加速释放，集中回收伏笔，制造高潮",
    Strategy.RESOLVE: "选择方向并坚持，放弃其他可能路径",
    Strategy.DETOUR: "引入意外转折，颠覆读者预期",
}

DIMENSION_STRATEGY_MAP: dict[str, list[tuple[Strategy, float]]] = {
    "pacing": [
        (Strategy.DELAY, 0.9),
        (Strategy.EXPLODE, 0.8),
        (Strategy.RESOLVE, 0.3),
        (Strategy.DETOUR, 0.4),
    ],
    "tension": [
        (Strategy.EXPLODE, 0.9),
        (Strategy.DETOUR, 0.7),
        (Strategy.DELAY, 0.6),
        (Strategy.RESOLVE, 0.3),
    ],
    "character": [
        (Strategy.RESOLVE, 0.8),
        (Strategy.EXPLODE, 0.5),
        (Strategy.DETOUR, 0.5),
        (Strategy.DELAY, 0.4),
    ],
    "hook": [
        (Strategy.EXPLODE, 0.9),
        (Strategy.RESOLVE, 0.7),
        (Strategy.DELAY, 0.6),
        (Strategy.DETOUR, 0.5),
    ],
    "world": [
        (Strategy.RESOLVE, 0.8),
        (Strategy.DETOUR, 0.4),
        (Strategy.DELAY, 0.3),
        (Strategy.EXPLODE, 0.3),
    ],
    "style": [
        (Strategy.RESOLVE, 0.7),
        (Strategy.DELAY, 0.4),
        (Strategy.DETOUR, 0.4),
        (Strategy.EXPLODE, 0.3),
    ],
}


@dataclass
class StrategyResult:
    strategy: Strategy
    label: str = ""
    description: str = ""
    confidence: float = 0.5
    reason: str = ""
    dominant_dimension: str = ""
    contributing_guides: list[str] = field(default_factory=list)
    instruction: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.label:
            self.label = STRATEGY_LABELS.get(self.strategy, "")
        if not self.description:
            self.description = STRATEGY_DESCRIPTIONS.get(self.strategy, "")
        self.confidence = max(0.0, min(1.0, self.confidence))

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "label": self.label,
            "description": self.description,
            "confidence": self.confidence,
            "reason": self.reason,
            "dominant_dimension": self.dominant_dimension,
            "contributing_guides": list(self.contributing_guides),
            "instruction": self.instruction,
            "context": dict(self.context),
        }
