"""
Decision Engine — converts Guide signals into a single narrative strategy
with a concrete writing instruction.

Input:  StoryState + list of DecisionSignals
Output: StrategyResult (strategy + instruction + reason)

Pipeline:
  1. compute dimension vector from signals
  2. detect conflicts among top signals
  3. select strategy from dominant dimension
  4. generate instruction string
"""
from __future__ import annotations
import logging
from typing import Any

from story.decision.strategy import (
    Strategy,
    StrategyResult,
    DIMENSION_STRATEGY_MAP,
    STRATEGY_LABELS,
)
from story.decision.dimension_matrix import compute_dimension_vector, DimensionVector
from story.guide.collector import DecisionSignal

_logger = logging.getLogger("NovelWriter.story.decision_engine")


def decide(
    signals: list[DecisionSignal],
    *,
    story_state=None,
    previous_decisions: list | None = None,
) -> StrategyResult:
    if not signals:
        return _default_strategy()

    vector = compute_dimension_vector(signals)

    if not vector.has_signals:
        return _default_strategy()

    conflicts = _detect_signal_conflicts(signals)
    top_signals = _top_signals(signals, n=5)

    strategy, strategy_confidence = _select_strategy(vector, signals)

    reason = _build_reason(vector, strategy, conflicts, top_signals)
    instruction = _build_instruction(
        strategy, vector, top_signals, conflicts,
        story_state=story_state,
        previous_decisions=previous_decisions,
    )

    result = StrategyResult(
        strategy=strategy,
        confidence=strategy_confidence,
        reason=reason,
        dominant_dimension=vector.dominant,
        contributing_guides=[s.guide_id for s in top_signals],
        instruction=instruction,
        context={
            "vector": vector.to_dict(),
            "conflicts_count": len(conflicts),
            "signal_count": len(signals),
        },
    )

    _logger.info(
        "Decision: %s (confidence=%.2f, dim=%s, signals=%d, conflicts=%d)",
        result.label, result.confidence, vector.dominant,
        len(signals), len(conflicts),
    )
    return result


def _default_strategy() -> StrategyResult:
    return StrategyResult(
        strategy=Strategy.RESOLVE,
        confidence=0.3,
        reason="无有效信号，使用默认策略",
        instruction="按单元大纲自然推进",
    )


def _detect_signal_conflicts(signals: list[DecisionSignal]) -> list[dict]:
    conflicts: list[dict] = []
    for i in range(len(signals)):
        for j in range(i + 1, len(signals)):
            sa = signals[i]
            sb = signals[j]
            if sa.dimension != sb.dimension:
                if sa.priority >= 0.6 and sb.priority >= 0.6:
                    conf_ratio = min(sa.priority, sb.priority) / max(sa.priority, sb.priority)
                    if conf_ratio > 0.7:
                        conflicts.append({
                            "a": sa.guide_id,
                            "b": sb.guide_id,
                            "dim_a": sa.dimension,
                            "dim_b": sb.dimension,
                            "severity": round(1.0 - (abs(sa.priority - sb.priority)), 2),
                        })
    return conflicts


def _top_signals(signals: list[DecisionSignal], n: int = 5) -> list[DecisionSignal]:
    return sorted(signals, key=lambda s: -s.signal_strength)[:n]


def _select_strategy(
    vector: DimensionVector,
    signals: list[DecisionSignal],
) -> tuple[Strategy, float]:
    candidates = DIMENSION_STRATEGY_MAP.get(vector.dominant)
    if not candidates:
        return Strategy.RESOLVE, 0.5

    if vector.guide_count <= 1 and vector.dominant_score < 0.3:
        return Strategy.RESOLVE, 0.3

    adjusted: list[tuple[Strategy, float]] = []
    for strat, base_weight in candidates:
        score = base_weight * min(vector.dominant_score, 1.0)
        if strat == Strategy.RESOLVE:
            if _has_support_consensus(signals):
                score *= 1.2
        if strat == Strategy.DETOUR:
            top_dims = _count_top_dimensions(signals, n=3)
            if top_dims >= 3:
                score *= 1.4
            elif top_dims >= 2:
                score *= 1.15
        if strat == Strategy.EXPLODE:
            urgent_ratio = sum(1 for s in signals if s.urgent) / max(len(signals), 1)
            if urgent_ratio > 0.3:
                score *= 1.2
        if strat == Strategy.DELAY:
            if vector.guide_count <= 2:
                score *= 0.7
        adjusted.append((strat, round(min(score, 1.0), 4)))

    adjusted.sort(key=lambda x: -x[1])
    best = adjusted[0]
    return best[0], best[1]


def _has_support_consensus(signals: list[DecisionSignal]) -> bool:
    if len(signals) < 2:
        return False
    support_edges = 0
    guide_ids = {s.guide_id for s in signals}
    for s in signals:
        for sup_id in s.supports:
            if sup_id in guide_ids:
                support_edges += 1
    return support_edges >= 2


def _count_top_dimensions(signals: list[DecisionSignal], n: int = 3) -> int:
    top = sorted(signals, key=lambda s: -s.signal_strength)[:n]
    return len({s.dimension for s in top})


def _build_reason(
    vector: DimensionVector,
    strategy: Strategy,
    conflicts: list[dict],
    top_signals: list[DecisionSignal],
) -> str:
    dim_label = vector.dominant
    dim_score = vector.dominant_score

    reasons = [
        f"主导维度: {dim_label} (强度 {dim_score:.2f})",
    ]

    if strategy == Strategy.DELAY:
        reasons.append(f"策略: 延后 — 当前信号不足或冲突过多，暂缓推进")
    elif strategy == Strategy.EXPLODE:
        reasons.append(f"策略: 爆发 — 高张力信号集中，加速回收伏笔")
    elif strategy == Strategy.RESOLVE:
        reasons.append(f"策略: 收束 — 信号方向一致，按选定路径推进")
    elif strategy == Strategy.DETOUR:
        reasons.append(f"策略: 转向 — 存在维度冲突，引入意外转折")

    if conflicts:
        reasons.append(f"检测到 {len(conflicts)} 处维度冲突")

    top_sources = [s.source for s in top_signals[:3]]
    if top_sources:
        reasons.append(f"主要信号源: {', '.join(top_sources)}")

    return "；".join(reasons)


def _build_instruction(
    strategy: Strategy,
    vector: DimensionVector,
    top_signals: list[DecisionSignal],
    conflicts: list[dict],
    *,
    story_state=None,
    previous_decisions: list | None = None,
) -> str:
    strategy_instruction = {
        Strategy.DELAY: (
            "暂缓主要推进方向。"
            "维持当前张力水平，不急于揭示答案或回收伏笔。"
            "着重描写人物的内心犹豫和外部压力的积累。"
            "让读者感受到'暴风雨前的宁静'。"
        ),
        Strategy.EXPLODE: (
            "集中爆发。回收此前埋下的伏笔，让隐藏的冲突浮出水面。"
            "场景密度增加，节奏加快，以动作和对话推进为主。"
            "让多个线索在本单元交汇碰撞。"
        ),
        Strategy.RESOLVE: (
            "选一条路径坚持推进。"
            "围绕单元大纲的核心事件展开，不引入额外的分支。"
            "保持叙事方向的一致性，重点刻画人物在此路径上的成长。"
        ),
        Strategy.DETOUR: (
            "引入意外转折。"
            "在看似明确的叙事方向上制造一个反预期事件。"
            "让读者的预期落空，但回头会发现一切有迹可循。"
            "转折必须与已有伏笔/人物动机一致，不可凭空出现。"
        ),
    }.get(strategy, "按单元大纲自然推进。")

    parts = [f"## 叙事策略: {STRATEGY_LABELS.get(strategy, '')}", "", strategy_instruction]

    top_advice = [s.advice for s in top_signals[:3] if s.advice]
    if top_advice:
        parts.append("")
        parts.append("### 当前引导建议")
        for i, adv in enumerate(top_advice):
            parts.append(f"{i + 1}. {adv}")

    if conflicts:
        parts.append("")
        parts.append("### 维度冲突提醒")
        parts.append(f"当前存在 {len(conflicts)} 处信号维度冲突，以上策略已综合权衡。")
        for i, c in enumerate(conflicts[:3]):
            parts.append(f"{i + 1}. 维度 [{c['dim_a']}] vs [{c['dim_b']}] — 严重度 {c['severity']:.2f}")

    if story_state is not None:
        parts.append("")
        parts.append("### 当前故事状态")
        chars = story_state.character_names()
        if chars:
            parts.append(f"出场角色: {', '.join(chars[:5])}")
        parts.append(f"当前步骤: {story_state.current_step}/{story_state.total_steps}")
        parts.append(f"活跃伏笔: {story_state.active_hooks_count()}")

    return "\n".join(parts)
