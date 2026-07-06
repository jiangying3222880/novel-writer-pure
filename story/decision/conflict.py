"""
Conflict Resolution — 冲突检测与解决

检测信号间的冲突，提供解决建议。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from story.guide.collector import DecisionSignal


@dataclass
class Conflict:
    """信号冲突."""
    signal_a: DecisionSignal
    signal_b: DecisionSignal
    severity: float = 0.0
    description: str = ""
    resolution: str = ""


def detect_conflicts(signals: list[DecisionSignal]) -> list[Conflict]:
    """检测信号列表中的冲突."""
    conflicts = []

    for i, sa in enumerate(signals):
        for sb in signals[i+1:]:
            conflict = _check_conflict(sa, sb)
            if conflict is not None:
                conflicts.append(conflict)

    # 按严重程度排序
    conflicts.sort(key=lambda c: -c.severity)
    return conflicts


def resolve_conflicts(
    conflicts: list[Conflict],
    signals: list[DecisionSignal],
) -> list[DecisionSignal]:
    """解决冲突，返回调整后的信号列表."""
    if not conflicts:
        return signals

    # 标记被覆盖的信号
    overridden = set()
    for c in conflicts:
        if c.resolution == "override_a":
            overridden.add(c.signal_a.guide_id)
        elif c.resolution == "override_b":
            overridden.add(c.signal_b.guide_id)
        elif c.resolution == "merge":
            # 合并时保留两者，但降低优先级
            pass

    # 过滤被覆盖的信号
    result = []
    for s in signals:
        if s.guide_id not in overridden:
            result.append(s)

    return result


def _check_conflict(
    sa: DecisionSignal,
    sb: DecisionSignal,
) -> Optional[Conflict]:
    """检查两个信号是否冲突."""
    # 同维度相反方向的建议
    if sa.dimension == sb.dimension:
        # 检查是否在 conflicts_with 列表中
        if sa.guide_id in (sb.conflicts_with or []):
            return Conflict(
                signal_a=sa,
                signal_b=sb,
                severity=max(sa.priority, sb.priority),
                description=f"Explicit conflict: {sa.guide_id} vs {sb.guide_id}",
                resolution="override_a" if sa.priority < sb.priority else "override_b",
            )

    # 跨维度冲突 (priority 都很高)
    if (sa.dimension != sb.dimension
        and sa.priority >= 0.7
        and sb.priority >= 0.7):
        severity = 1.0 - abs(sa.priority - sb.priority)
        if severity > 0.6:
            return Conflict(
                signal_a=sa,
                signal_b=sb,
                severity=severity,
                description=f"Cross-dimension tension: {sa.dimension} vs {sb.dimension}",
                resolution="merge",
            )

    return None
