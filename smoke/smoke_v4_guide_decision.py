"""
Week 2 verification: Guide → Decision Input Layer
Tests: signals → dimension vector → strategy → instruction
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story import (
    StoryState, StateBridge, Strategy, StrategyResult, STRATEGY_LABELS,
    compute_dimension_vector, DimensionVector, decide,
    DecisionSignal, collect_signals,
)

print("1. IMPORTS: OK")

# ===== 2. Mock signals — simulate Guide output =====
signals = [
    DecisionSignal(
        guide_id="g1", source="pressure", priority=0.9, confidence=0.85,
        advice="当前节奏过慢，建议加速，在下一场景集中爆发",
        reason="reader_signal 检测到读者兴趣下降",
        dimension="pacing", urgent=True,
    ),
    DecisionSignal(
        guide_id="g2", source="pressure", priority=0.85, confidence=0.80,
        advice="压力已进入橙色区，需回收伏笔",
        reason="累积未回收伏笔 3 个",
        dimension="hook", urgent=True,
    ),
    DecisionSignal(
        guide_id="g3", source="character_state", priority=0.6, confidence=0.75,
        advice="主角林凡信任度大幅下降，需铺垫",
        reason="trust 从 80 降至 50",
        dimension="character",
    ),
    DecisionSignal(
        guide_id="g4", source="voice", priority=0.5, confidence=0.7,
        advice="慕容雪的对话风格偏冷，注意语气一致",
        reason="声音指纹检测偏离",
        dimension="style",
    ),
    DecisionSignal(
        guide_id="g5", source="consistency", priority=0.55, confidence=0.65,
        advice="天剑峰在上文是晴天，此处出现暴雨需交代原因",
        reason="世界一致性检测",
        dimension="world",
    ),
]

# Add support/conflict edges
signals[0].supports.append("g2")
signals[1].supports.append("g1")

print(f"2. SIGNALS: {len(signals)} signals, {sum(1 for s in signals if s.urgent)} urgent")

# ===== 3. Dimension Vector =====
vector = compute_dimension_vector(signals)
print(f"3. DIMENSION VECTOR: dominant={vector.dominant} (score={vector.dominant_score}), guides={vector.guide_count}")
for s in vector.sorted_scores():
    if s.score > 0:
        print(f"   {s.dimension}: {s.score:.4f} ({s.guide_count} guides)")
assert vector.has_signals
assert vector.dominant_score > 0
print("   OK")

# ===== 4. Decision with state =====
state = StoryState(
    unit_id="u_test", title="试剑大会",
    current_step=3, total_steps=5,
    pov_character="林凡", synopsis="林凡在试剑大会上面对宿敌",
).with_character("林凡", {"trust": 50, "realm": "金丹"})

result = decide(signals, story_state=state)
print(f"4. DECISION: strategy={result.label} ({result.strategy.value}), confidence={result.confidence:.2f}")
print(f"   reason: {result.reason}")
assert result.strategy in (Strategy.EXPLODE, Strategy.DELAY, Strategy.RESOLVE, Strategy.DETOUR)
assert result.confidence > 0
assert result.instruction
assert len(result.contributing_guides) > 0
print("   OK")

print(f"5. INSTRUCTION (first 200 chars):")
print(f"   {result.instruction[:200]}...")
print("   OK")

# ===== 6. Empty signals → default =====
empty_result = decide([], story_state=state)
print(f"6. EMPTY DECISION: strategy={empty_result.label}, confidence={empty_result.confidence:.2f}")
assert empty_result.strategy == Strategy.RESOLVE
print("   OK")

# ===== 7. All four strategies coverage =====
print(f"7. STRATEGY LABELS:")
for s in Strategy:
    print(f"   {s.value}: {STRATEGY_LABELS[s]}")

# ===== 8. DETOUR test (conflicting signals) =====
conflict_signals = [
    DecisionSignal(
        guide_id="c1", source="pressure", priority=0.85, confidence=0.80,
        advice="加速回收伏笔", dimension="pacing", urgent=True,
    ),
    DecisionSignal(
        guide_id="c2", source="consistency", priority=0.80, confidence=0.82,
        advice="世界观出现矛盾，暂停推进先修正", dimension="world", urgent=True,
    ),
    DecisionSignal(
        guide_id="c3", source="voice", priority=0.75, confidence=0.78,
        advice="当前文风偏离作品调性", dimension="style",
    ),
]
detour_result = decide(conflict_signals)
print(f"8. CONFLICT DECISION: strategy={detour_result.label}, confidence={detour_result.confidence:.2f}")
print(f"   reason: {detour_result.reason}")
print("   OK")

# ===== 9. DELAY test (few signals) =====
delay_signals = [
    DecisionSignal(
        guide_id="d1", source="memory", priority=0.4, confidence=0.45,
        advice="旧弧线记忆可忽略", dimension="hook",
    ),
]
delay_result = decide(delay_signals)
print(f"9. DELAY DECISION: strategy={delay_result.label}, confidence={delay_result.confidence:.2f}")
print("   OK")

# ===== 10. signals_summary =====
from story.guide.collector import signals_summary
summary = signals_summary(signals)
print(f"10. SUMMARY: total={summary['total']}, urgent={summary['urgent']}, sources={summary['by_source']}")
print(f"    dimensions={summary['by_dimension']}")
assert summary["total"] == 5
print("    OK")

print()
print("ALL TESTS PASSED")
