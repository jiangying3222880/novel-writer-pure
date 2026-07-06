"""
G20 SMOKE: v4.0 因果归因引擎 — 从发散信号回溯根因

G19.5 检测了"什么模式" (BURST/SUSTAINED/...)
G19.6 回答了"边界在哪里" (stress manifold)
G20 回答:  "是什么导致的?"

核心能力:
  1. 逆向因果追踪: 从 MetricPoint 回溯到 decision/memory/guide 事件
  2. 归因图构建:    DAG 连接因果事件
  3. 根因排序:      按因果影响力排序假设
  4. 反事实验证:    "如果修复 X, Y 会恢复吗?"

全部 mock, 注入已知因果链, 验证归因引擎能找到它们.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_SMOKE_TIMEOUT = 30
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g20 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smoke_g19_5_enhanced_divergence import (
    MetricPoint, DivergencePattern, DivergenceEvent,
)
from smoke_g19_6_stress_manifold import (
    generate_stress_trajectory, StressConfig, SceneType,
)


# ============================================================
# 1. 因果事件模型
# ============================================================

class EventCause(Enum):
    GUIDE_IGNORED = "guide_ignored"         # Guide 被拒绝
    GUIDE_CONFLICT = "guide_conflict"        # Guide 间冲突
    CHARACTER_OOC = "character_ooc"          # 角色 OOC
    CHARACTER_FORK = "character_fork"        # 角色状态分叉
    HOOK_ORPHAN = "hook_orphan"             # 钩子遗忘
    MEMORY_FADE = "memory_fade"             # 记忆废弃
    MEMORY_OVERWRITE = "memory_overwrite"    # 记忆覆盖
    CONTEXT_LOSS = "context_loss"           # 上下文丢失
    FEEDBACK_D1_D4 = "feedback_d1_d4"       # D1下降→D4加速
    FEEDBACK_D4_D1 = "feedback_d4_d1"       # D4升高→D1进一步降


@dataclass
class CausalEvent:
    """一次因果事件 — 系统中的一个状态变化."""
    event_id: str
    cause_type: EventCause
    unit_index: int
    metric_affected: str          # D1/D2/D3/D4
    magnitude: float              # 对指标的影响量
    description: str
    parent_ids: list[str] = field(default_factory=list)  # 上游事件
    child_ids: list[str] = field(default_factory=list)   # 下游事件


@dataclass
class AttributionHypothesis:
    """归因假设 — 一个潜在的根因."""
    root_event: CausalEvent
    confidence: float             # 0-1
    causal_path: list[CausalEvent]  # 从根因到发散事件的路径
    path_length: int
    counterfactual_recovery: float  # "如果修复" — 指标恢复量


@dataclass
class AttributionReport:
    """归因报告."""
    divergence: DivergenceEvent
    hypotheses: list[AttributionHypothesis]
    primary_cause: AttributionHypothesis | None

    @property
    def is_confident(self) -> bool:
        if not self.primary_cause:
            return False
        return self.primary_cause.confidence >= 0.7


# ============================================================
# 2. 因果事件生成器 (注入已知因果链)
# ============================================================

class CausalDataGenerator:
    """生成带有已知因果链的 mock 数据.

    每条因果链都是确定性的, 验证归因引擎能否正确追踪."""

    def __init__(self, n_units: int = 30, seed: int = 42):
        self.n_units = n_units
        self.rng = random.Random(seed)
        self.events: list[CausalEvent] = []
        self._event_idx = 0

    def _eid(self) -> str:
        self._event_idx += 1
        return f"CE_{self._event_idx:04d}"

    def generate_causal_chain_simple(self) -> list[CausalEvent]:
        """简单因果链: Guide被忽略 → D1下降 → 单个因果关系.

        unit 12: GuideConflict → unit 13-15: GuideIgnored → unit 16: D1 decline detected."""
        chain = []

        root = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.GUIDE_CONFLICT,
            unit_index=12, metric_affected="D1", magnitude=0.30,
            description="Guide #3 与 Guide #7 在'战斗场景角色行动'上冲突",
        )
        chain.append(root)

        for offset in range(3):
            ev = CausalEvent(
                event_id=self._eid(), cause_type=EventCause.GUIDE_IGNORED,
                unit_index=13 + offset, metric_affected="D1", magnitude=0.08,
                description=f"Guide #{4+offset} 被 LLM 拒绝 (冲突影响)",
                parent_ids=[chain[-1].event_id],
            )
            chain[-1].child_ids.append(ev.event_id)
            chain.append(ev)

        self.events.extend(chain)
        return chain

    def generate_causal_chain_feedback(self) -> list[CausalEvent]:
        """反馈因果链: D1下降 → D4加速 → D1进一步下降.

        unit 22: D1 decline → unit 24: MemoryFade → unit 26: D4 spike → unit 28: Feedback."""
        chain = []

        d1_drop = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.GUIDE_IGNORED,
            unit_index=22, metric_affected="D1", magnitude=0.20,
            description="连续 4 个 Guide 被拒绝, 采纳率骤降",
        )
        chain.append(d1_drop)

        mem_fade = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.MEMORY_FADE,
            unit_index=24, metric_affected="D4", magnitude=0.15,
            description="L4 记忆废弃率因采纳率下降加速上升",
            parent_ids=[d1_drop.event_id],
        )
        d1_drop.child_ids.append(mem_fade.event_id)
        chain.append(mem_fade)

        feedback = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.FEEDBACK_D4_D1,
            unit_index=26, metric_affected="D1", magnitude=0.12,
            description="D4 废弃率高 → 上下文丢失 → D1 采纳率进一步下降",
            parent_ids=[mem_fade.event_id],
        )
        mem_fade.child_ids.append(feedback.event_id)
        chain.append(feedback)

        self.events.extend(chain)
        return chain

    def generate_causal_chain_character(self) -> list[CausalEvent]:
        """角色因果链: OOC → CharacterFork → 角色消失.

        unit 15: CharacterOOC → unit 17: CharacterFork → unit 27: 角色消失."""
        chain = []

        ooc = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.CHARACTER_OOC,
            unit_index=15, metric_affected="D2", magnitude=0.35,
            description="女主_苏雪 状态异常: 暴怒+敌对 (与设定矛盾)",
        )
        chain.append(ooc)

        fork = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.CHARACTER_FORK,
            unit_index=17, metric_affected="D2", magnitude=0.25,
            description="角色状态分叉: 快速恢复后再次异常 '冷漠+疏远'",
            parent_ids=[ooc.event_id],
        )
        ooc.child_ids.append(fork.event_id)
        chain.append(fork)

        context_loss = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.CONTEXT_LOSS,
            unit_index=25, metric_affected="D2", magnitude=0.40,
            description="多次状态波动后上下文丢失, 角色信息不可恢复",
            parent_ids=[fork.event_id],
        )
        fork.child_ids.append(context_loss.event_id)
        chain.append(context_loss)

        # 角色消失 (D2 metric 本身)
        gap = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.CHARACTER_OOC,
            unit_index=27, metric_affected="D2", magnitude=1.0,
            description="女主_苏雪 从叙事中完全消失",
            parent_ids=[context_loss.event_id],
        )
        context_loss.child_ids.append(gap.event_id)
        chain.append(gap)

        self.events.extend(chain)
        return chain

    def generate_causal_chain_memory(self) -> list[CausalEvent]:
        """记忆因果链: MemoryOverwrite → MemoryFade 加速.

        unit 20: MemoryOverwrite (新内容覆盖旧记忆) → unit 21-25: 持续废弃."""
        chain = []

        overwrite = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.MEMORY_OVERWRITE,
            unit_index=20, metric_affected="D4", magnitude=0.20,
            description="新记忆'黑风谷大战'覆盖了'青云城日常' 3 条记忆",
        )
        chain.append(overwrite)

        for offset in range(5):
            fade = CausalEvent(
                event_id=self._eid(), cause_type=EventCause.MEMORY_FADE,
                unit_index=21 + offset, metric_affected="D4", magnitude=0.04,
                description=f"记忆 {offset+1} 因覆盖效应加速废弃",
                parent_ids=[chain[-1].event_id],
            )
            chain[-1].child_ids.append(fade.event_id)
            chain.append(fade)

        self.events.extend(chain)
        return chain

    def generate_causal_chain_multi_root(self) -> list[CausalEvent]:
        """多根因因果链: 两个独立根因 → 汇合触发级联.

        unit 8: GuideConflict (根因 A) → unit 10-13: GuideIgnored
        unit 12: HookOrphan (根因 B) → unit 14-18: Hook 持续遗忘
        汇合: unit 19: D1+D3 同时下降 → Feedback."""
        chain = []

        # 根因 A
        root_a = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.GUIDE_CONFLICT,
            unit_index=8, metric_affected="D1", magnitude=0.25,
            description="Guide 冲突: '保持紧张感' vs '插入日常过渡'",
        )
        chain.append(root_a)

        ga = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.GUIDE_IGNORED,
            unit_index=10, metric_affected="D1", magnitude=0.10,
            description="Guide 被忽略 — 冲突后果",
            parent_ids=[root_a.event_id],
        )
        root_a.child_ids.append(ga.event_id)
        chain.append(ga)

        # 根因 B (独立)
        root_b = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.HOOK_ORPHAN,
            unit_index=12, metric_affected="D3", magnitude=0.20,
            description="钩子 HOOK_3 '上古遗迹的钥匙' 未在预期 Unit 内回收",
        )
        chain.append(root_b)

        hd = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.HOOK_ORPHAN,
            unit_index=14, metric_affected="D3", magnitude=0.15,
            description="钩子 HOOK_3 持续未被回收 (第 2 个窗口)",
            parent_ids=[root_b.event_id],
        )
        root_b.child_ids.append(hd.event_id)
        chain.append(hd)

        # 汇合事件
        merge = CausalEvent(
            event_id=self._eid(), cause_type=EventCause.FEEDBACK_D1_D4,
            unit_index=19, metric_affected="D1", magnitude=0.18,
            description="D1 持续下降 + 钩子遗忘 → 系统信心崩塌, 加速退化",
            parent_ids=[ga.event_id, hd.event_id],
        )
        ga.child_ids.append(merge.event_id)
        hd.child_ids.append(merge.event_id)
        chain.append(merge)

        self.events.extend(chain)
        return chain

    def get_events_in_window(self, unit_min: int, unit_max: int) -> list[CausalEvent]:
        """获取指定 unit 范围内的因果事件."""
        return [e for e in self.events if unit_min <= e.unit_index <= unit_max]


# ============================================================
# 3. 因果归因引擎
# ============================================================

class CausalAttributionEngine:
    """逆向因果追踪引擎.

    输入: divergence event + trajectory + causal events
    输出: ranked attribution hypotheses."""

    LOOKBACK = 12       # 向前搜索窗口 (unit)
    MIN_CORRELATION = 0.3  # 最小相关性阈值

    def attribute(
        self,
        divergence: DivergenceEvent,
        trajectory: list[MetricPoint],
        causal_events: list[CausalEvent],
    ) -> AttributionReport:
        """对一个发散事件进行因果归因."""

        # Step 1: 收集候选事件
        candidates = self._collect_candidates(divergence, causal_events)

        if not candidates:
            return AttributionReport(
                divergence=divergence, hypotheses=[], primary_cause=None)

        # Step 2: 计算每个候选与指标变化的相关性
        scored = self._score_candidates(divergence, trajectory, candidates)

        # Step 3: 追踪因果路径
        paths = self._trace_paths(scored, causal_events)

        # Step 4: 反事实验证
        hypotheses = self._counterfactual_validate(divergence, trajectory, paths)

        # Step 5: 排序
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        return AttributionReport(
            divergence=divergence,
            hypotheses=hypotheses,
            primary_cause=hypotheses[0] if hypotheses else None,
        )

    def _collect_candidates(
        self, divergence: DivergenceEvent, all_events: list[CausalEvent],
    ) -> list[CausalEvent]:
        """收集发散事件之前的候选因果事件."""
        start = max(0, divergence.unit_index - self.LOOKBACK)
        end = divergence.unit_index

        # 展开复合 metric (eg. "D1→D4" → ["D1", "D4"])
        metrics = set()
        for part in divergence.metric.replace("→", " ").replace(">", " ").split():
            part = part.strip()
            if part:
                metrics.add(part)

        candidates = [e for e in all_events
                      if start <= e.unit_index <= end
                      and e.metric_affected in metrics]
        return candidates

    def _score_candidates(
        self, divergence: DivergenceEvent,
        trajectory: list[MetricPoint],
        candidates: list[CausalEvent],
    ) -> list[tuple[CausalEvent, float]]:
        """对每个候选事件计算因果相关性分数.

        分数 = temporal proximity × magnitude match × metric match."""
        scored = []
        for candidate in candidates:
            temporal_score = 1.0 - (divergence.unit_index - candidate.unit_index) / self.LOOKBACK
            magnitude_match = min(candidate.magnitude, divergence.magnitude) / max(
                candidate.magnitude, divergence.magnitude, 0.001)
            # 复合 metric 展开
            div_metrics = set(divergence.metric.replace("→", " ").split())
            metric_bonus = 0.5  # 默认部分匹配 (已在 _collect 中过滤)
            if candidate.metric_affected in div_metrics:
                metric_bonus = 1.0

            score = temporal_score * 0.4 + magnitude_match * 0.4 + metric_bonus * 0.2
            score = max(0.0, min(1.0, score))
            scored.append((candidate, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _trace_paths(
        self, scored: list[tuple[CausalEvent, float]],
        all_events: list[CausalEvent],
    ) -> list[list[CausalEvent]]:
        """从每个候选事件向前追踪因果路径到根因."""
        event_map = {e.event_id: e for e in all_events}
        paths = []

        for candidate, score in scored[:10]:  # top 10 候选
            if score < self.MIN_CORRELATION:
                break
            path = self._trace_to_root(candidate, event_map)
            paths.append(path)

        return paths

    def _trace_to_root(
        self, event: CausalEvent, event_map: dict[str, CausalEvent],
        visited: set | None = None,
    ) -> list[CausalEvent]:
        """从事件回溯到根因 (无 parent 的事件)."""
        if visited is None:
            visited = set()
        if event.event_id in visited:
            return [event]
        visited.add(event.event_id)

        if not event.parent_ids:
            return [event]

        # 追踪所有父路径, 取最长
        longest = [event]
        for pid in event.parent_ids:
            if pid in event_map:
                upstream = self._trace_to_root(event_map[pid], event_map, visited)
                if len(upstream) + 1 > len(longest):
                    longest = [event] + upstream
            else:
                # 父事件不在当前集合中 (可能在更早的范围外)
                root = CausalEvent(
                    event_id=pid, cause_type=EventCause.CONTEXT_LOSS,
                    unit_index=event.unit_index - 1, metric_affected=event.metric_affected,
                    magnitude=event.magnitude * 0.8,
                    description=f"上游事件 {pid} (超出搜索范围, 推断根因)",
                )
                longest = [event, root]

        return longest

    def _counterfactual_validate(
        self, divergence: DivergenceEvent,
        trajectory: list[MetricPoint],
        paths: list[list[CausalEvent]],
    ) -> list[AttributionHypothesis]:
        """反事实验证: 如果移除根因, 指标会恢复多少?"""
        hypotheses = []

        for path in paths:
            if not path:
                continue

            root = path[-1]
            # 计算根因对最终指标的影响量
            total_impact = sum(e.magnitude for e in path)
            # 保守估计: 移除根因可以恢复 70-90% 的影响
            recovery = min(total_impact * 0.85, 1.0)

            # 置信度 = 路径清晰度 × 反事实恢复量
            path_clarity = 1.0 / len(path)  # 短路径更可信
            confidence = min(0.95, path_clarity * 0.5 + recovery * 0.5)

            hypotheses.append(AttributionHypothesis(
                root_event=root,
                confidence=round(confidence, 4),
                causal_path=path,
                path_length=len(path),
                counterfactual_recovery=round(recovery, 4),
            ))

        return hypotheses


# ============================================================
# 4. 测试用例
# ============================================================

def build_test_trajectory(n_units: int = 30) -> tuple[list[MetricPoint], list[SceneType]]:
    """构建测试轨迹 — 轻度退化, 便于验证归因."""
    config = StressConfig(
        d1_drift=0.005, d2_ooc=0.005,
        d3_hook_decay=0.005, d4_memory_fade=0.005,
        burst_mag=0.05, burst_dur=2, burst_start=20,
        self_heal=0.05, feedback_lag=4,
    )
    return generate_stress_trajectory(config, n_units)


def test_single_cause_attribution():
    """测试 1: 单因归因 — 已知因果链, 验证引擎找到正确的根因."""
    print("\n" + "=" * 62)
    print("  G20 测试 1: 单因归因 — Guide Conflict → D1 下降")
    print("=" * 62)

    gen = CausalDataGenerator(n_units=30, seed=42)
    chain = gen.generate_causal_chain_simple()

    # 注入发散事件: 对应因果链的末端
    divergence = DivergenceEvent(
        pattern=DivergencePattern.SUSTAINED,
        metric="D1", unit_index=16, magnitude=0.24,
        detail="D1 持续衰退: 0.82→0.58",
    )

    trajectory, _ = build_test_trajectory()
    engine = CausalAttributionEngine()
    report = engine.attribute(divergence, trajectory, gen.events)

    assert report.primary_cause is not None, "应该有归因结果"
    assert report.primary_cause.confidence > 0.5, f"置信度应 > 0.5, 实际 {report.primary_cause.confidence}"
    assert report.primary_cause.root_event.cause_type == EventCause.GUIDE_CONFLICT, \
        f"根因应为 GUIDE_CONFLICT, 实际 {report.primary_cause.root_event.cause_type}"

    print(f"  PASS: primary cause = {report.primary_cause.root_event.cause_type.value}")
    print(f"  confidence = {report.primary_cause.confidence:.2f}")
    print(f"  path length = {report.primary_cause.path_length}")
    print(f"  recovery = {report.primary_cause.counterfactual_recovery:.2f}")

    for h in report.hypotheses[:3]:
        print(f"    [{h.confidence:.2f}] {h.root_event.cause_type.value}"
              f" ({h.path_length} steps) : {h.root_event.description}")

    return True


def test_feedback_attribution():
    """测试 2: 反馈环归因 — D1→D4→D1 因果链."""
    print("\n" + "=" * 62)
    print("  G20 测试 2: 反馈环归因 — D1↓ → D4↑ → D1↓↓")
    print("=" * 62)

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_feedback()

    divergence = DivergenceEvent(
        pattern=DivergencePattern.FEEDBACK_LOOP,
        metric="D1→D4", unit_index=28, magnitude=0.18,
        detail="反馈环: D1↓@u22 → D4↓@u28",
    )

    trajectory, _ = build_test_trajectory()
    engine = CausalAttributionEngine()
    report = engine.attribute(divergence, trajectory, gen.events)

    assert report.primary_cause is not None
    # 根因应该是 GUIDE_IGNORED (第一环)
    assert report.primary_cause.root_event.cause_type == EventCause.GUIDE_IGNORED, \
        f"根因应为 GUIDE_IGNORED, 实际 {report.primary_cause.root_event.cause_type}"
    assert report.primary_cause.confidence > 0.4, f"置信度应 > 0.4"

    print(f"  PASS: primary cause = {report.primary_cause.root_event.cause_type.value}")
    print(f"  confidence = {report.primary_cause.confidence:.2f}")
    print(f"  path length = {report.primary_cause.path_length}")

    return True


def test_character_attribution():
    """测试 3: 角色归因 — OOC → Fork → 消失."""
    print("\n" + "=" * 62)
    print("  G20 测试 3: 角色归因 — OOC → 角色消失")
    print("=" * 62)

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_character()

    divergence = DivergenceEvent(
        pattern=DivergencePattern.CASCADE,
        metric="D2", unit_index=27, magnitude=1.0,
        detail="角色 '女主_苏雪' 消失",
    )

    trajectory, _ = build_test_trajectory()
    engine = CausalAttributionEngine()
    report = engine.attribute(divergence, trajectory, gen.events)

    assert report.primary_cause is not None
    assert report.primary_cause.root_event.cause_type == EventCause.CHARACTER_OOC, \
        f"根因应为 CHARACTER_OOC, 实际 {report.primary_cause.root_event.cause_type}"

    print(f"  PASS: primary cause = {report.primary_cause.root_event.cause_type.value}")
    print(f"  confidence = {report.primary_cause.confidence:.2f}")
    print(f"  path length = {report.primary_cause.path_length}")

    return True


def test_multi_root_attribution():
    """测试 4: 多根因归因 — 两个独立根因汇合触发级联."""
    print("\n" + "=" * 62)
    print("  G20 测试 4: 多根因归因 — GuideConflict + HookOrphan → 级联")
    print("=" * 62)

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_multi_root()

    divergence = DivergenceEvent(
        pattern=DivergencePattern.FEEDBACK_LOOP,
        metric="D1→D4", unit_index=19, magnitude=0.18,
        detail="多根因汇合触发反馈环",
    )

    trajectory, _ = build_test_trajectory()
    engine = CausalAttributionEngine()
    report = engine.attribute(divergence, trajectory, gen.events)

    assert report.primary_cause is not None
    assert len(report.hypotheses) >= 2, "应至少找到 2 个独立根因路径"

    root_types = {h.root_event.cause_type for h in report.hypotheses[:3]}
    assert EventCause.GUIDE_CONFLICT in root_types, "应发现 GuideConflict 根因"

    print(f"  PASS: found {len(report.hypotheses)} hypotheses")
    for h in report.hypotheses[:3]:
        print(f"    [{h.confidence:.2f}] {h.root_event.cause_type.value}"
              f" ({h.path_length} steps)")

    return True


def test_false_positive_resistance():
    """测试 5: 误报抵抗 — 无关事件不应被归因."""
    print("\n" + "=" * 62)
    print("  G20 测试 5: 误报抵抗 — 无关因果事件不应被归因")
    print("=" * 62)

    gen = CausalDataGenerator(n_units=30, seed=42)
    # 注入一个与 divergence 无关的事件链
    gen.generate_causal_chain_memory()  # D4 事件

    # divergence 却是 D1 的
    divergence = DivergenceEvent(
        pattern=DivergencePattern.BURST,
        metric="D1", unit_index=12, magnitude=0.15,
        detail="D1 burst: 瞬时下降",
    )

    trajectory, _ = build_test_trajectory()
    engine = CausalAttributionEngine()
    report = engine.attribute(divergence, trajectory, gen.events)

    # 不应将 D4 的 memory 事件归因到 D1 的 divergence
    if report.primary_cause:
        # 如果有结果, 验证不是 memory 相关的错误归因
        is_memory = report.primary_cause.root_event.cause_type in (
            EventCause.MEMORY_FADE, EventCause.MEMORY_OVERWRITE)
        if is_memory and report.primary_cause.confidence > 0.5:
            print(f"  FAIL: 错误将 D4 memory 事件归因为 D1 divergence 的根因"
                  f" (conf={report.primary_cause.confidence:.2f})")
            return False

    print(f"  PASS: 无高置信度错误归因")
    if report.primary_cause:
        print(f"  (低置信度归因: {report.primary_cause.root_event.cause_type.value}"
              f" conf={report.primary_cause.confidence:.2f})")
    else:
        print(f"  (无归因结果 — 所有候选事件被正确过滤)")

    return True


# ============================================================
# Main
# ============================================================

def main():
    passed = failed = 0

    tests = [
        ("单因归因", test_single_cause_attribution),
        ("反馈环归因", test_feedback_attribution),
        ("角色归因", test_character_attribution),
        ("多根因归因", test_multi_root_attribution),
        ("误报抵抗", test_false_positive_resistance),
    ]

    for name, test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    total = passed + failed
    print("\n" + "=" * 62)
    print(f"  G20 完成: {passed}/{total} 通过, {failed} 失败")
    print("=" * 62)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
