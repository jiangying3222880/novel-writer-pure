"""
Guide Collector — wraps existing collect_guides() and standardizes signals
for the Decision Input Layer.

Adds per-Guide: dimension tag, urgency flag, and normalized severity.
Output is a list of DecisionSignal dicts ready for the Dimension Matrix.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("NovelWriter.story.guide")

SOURCE_TO_DIMENSION: dict[str, str] = {
    "pressure": "pacing",
    "reader_signal": "pacing",
    "hook": "hook",
    "character_state": "character",
    "voice": "character",
    "style": "style",
    "consistency": "world",
    "memory": "hook",
    "event": "character",
    "unit_event": "character",
}

URGENCY_THRESHOLD: float = 0.75
HIGH_CONFIDENCE_THRESHOLD: float = 0.7


@dataclass
class DecisionSignal:
    guide_id: str
    source: str
    priority: float = 0.5
    confidence: float = 0.7
    advice: str = ""
    reason: str = ""
    scope: str = "Unit"
    dimension: str = "character"
    urgent: bool = False
    conflicts_with: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def signal_strength(self) -> float:
        return self.priority * self.confidence

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= HIGH_CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "guide_id": self.guide_id,
            "source": self.source,
            "priority": self.priority,
            "confidence": self.confidence,
            "advice": self.advice,
            "reason": self.reason,
            "scope": self.scope,
            "dimension": self.dimension,
            "urgent": self.urgent,
            "conflicts_with": list(self.conflicts_with),
            "supports": list(self.supports),
            "evidence_ids": list(self.evidence_ids),
            "signal_strength": self.signal_strength,
        }


def _guess_dimension(source: str, advice: str) -> str:
    base = SOURCE_TO_DIMENSION.get(source, "character")
    advice_lower = advice.lower() if advice else ""

    if any(kw in advice_lower for kw in ("加速", "爆发", "高潮", "节奏", "pace", "快", "紧迫")):
        return "pacing"
    if any(kw in advice_lower for kw in ("回收", "兑现", "伏笔", "hook", "plant", "payoff")):
        return "hook"
    if any(kw in advice_lower for kw in ("角色", "人物", "character", "ooc", "性格", "状态")):
        return "character"
    if any(kw in advice_lower for kw in ("世界", "世界观", "设定", "consistency", "矛盾", "一致")):
        return "world"
    if any(kw in advice_lower for kw in ("风格", "文风", "style", "语气", "语调", "笔法")):
        return "style"
    if any(kw in advice_lower for kw in ("紧张", "压力", "tension", "悬疑", "压迫")):
        return "tension"
    return base


def _compute_urgency(priority: float, confidence: float, conflicts_count: int) -> bool:
    if priority >= URGENCY_THRESHOLD and confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return True
    if conflicts_count >= 2 and priority >= 0.6:
        return True
    return False


def collect_signals(
    unit_id: str,
    *,
    project_id: str = "",
    story_state=None,
    min_confidence: float = 0.3,
    max_count: int = 20,
) -> list[DecisionSignal]:
    from app.core.types import collect_guides
    raw_guides = collect_guides(unit_id, project_id=project_id)

    signals: list[DecisionSignal] = []

    for g in raw_guides:
        if g.confidence < min_confidence:
            continue

        dimension = _guess_dimension(g.source, g.advice)
        urgent = _compute_urgency(g.priority, g.confidence, len(g.conflicts_with))

        signals.append(DecisionSignal(
            guide_id=g.guide_id,
            source=g.source,
            priority=g.priority,
            confidence=g.confidence,
            advice=g.advice,
            reason=g.reason,
            scope=g.scope,
            dimension=dimension,
            urgent=urgent,
            conflicts_with=list(g.conflicts_with),
            supports=list(g.supports),
            evidence_ids=list(g.evidence_ids),
        ))

    signals.sort(key=lambda s: (-s.signal_strength, s.dimension))

    urgent_signals = [s for s in signals if s.urgent]
    non_urgent = [s for s in signals if not s.urgent]

    result = urgent_signals + non_urgent
    if len(result) > max_count:
        result = result[:max_count]

    _logger.info(
        "Collected %d signals (urgent=%d) from %d raw guides for unit=%s",
        len(result), len(urgent_signals), len(raw_guides), unit_id[:8],
    )
    return result


def signals_summary(signals: list[DecisionSignal]) -> dict:
    sources: dict[str, int] = {}
    dimensions: dict[str, int] = {}
    urgent_count = 0

    for s in signals:
        sources[s.source] = sources.get(s.source, 0) + 1
        dimensions[s.dimension] = dimensions.get(s.dimension, 0) + 1
        if s.urgent:
            urgent_count += 1

    return {
        "total": len(signals),
        "urgent": urgent_count,
        "by_source": sources,
        "by_dimension": dimensions,
        "top_strength": max((s.signal_strength for s in signals), default=0.0),
    }
