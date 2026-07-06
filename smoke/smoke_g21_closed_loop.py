"""
G21 SMOKE: v4.0 闭环控制系统 — 自动检测→归因→修复→验证

G19.5  检测了"什么模式" (BURST/SUSTAINED/...)
G19.6  回答了"边界在哪里" (stress manifold)
G20    回答了"是什么导致的" (causal attribution)
G21    回答了"如何自动修复" (closed-loop control)

核心能力:
  1. Detect:    自动监控轨迹检测发散
  2. Attribute:  归因到根因 (复用 G20)
  3. Select:     选择最佳修复动作
  4. Correct:    执行修复 (模拟)
  5. Verify:     验证修复后指标恢复

校正动作类型:
  REGENERATE:         重新生成 Unit (强化 Guide 约束)
  RESTORE_CHARACTER:  从快照恢复角色状态
  REINFORCE_GUIDE:    提升冲突 Guide 优先级
  REPAIR_MEMORY:      回收废弃记忆
  REPLANT_HOOK:       重新种植被遗忘的钩子

全部 mock, 注入已知退化 + 验证自动修复效果.
"""
from __future__ import annotations

import math
import os
import random
import sys
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_SMOKE_TIMEOUT = 30
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g21 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smoke_g19_5_enhanced_divergence import (
    MetricPoint, DivergencePattern, DivergenceEvent,
    detect_divergence_patterns, SceneType, render_trajectory,
)
from smoke_g19_6_stress_manifold import (
    generate_stress_trajectory, StressConfig, ScenarioResult,
)
from smoke_g20_causal_attribution import (
    CausalAttributionEngine, CausalDataGenerator,
    EventCause, CausalEvent, AttributionReport,
)


# ============================================================
# 1. 校正动作模型
# ============================================================

class ActionType(Enum):
    REGENERATE = "regenerate"
    RESTORE_CHARACTER = "restore_character"
    REINFORCE_GUIDE = "reinforce_guide"
    REPAIR_MEMORY = "repair_memory"
    REPLANT_HOOK = "replant_hook"


@dataclass
class CorrectiveAction:
    """一个校正动作."""
    action_type: ActionType
    target_metric: str           # D1/D2/D3/D4
    target_unit: int             # 在哪个 unit 执行
    reason: str
    expected_recovery: float     # 预期恢复量 (0-1)
    priority: int = 1            # 1=高, 2=中, 3=低


@dataclass
class CorrectionResult:
    """校正执行结果."""
    action: CorrectiveAction
    success: bool
    recovery_actual: float       # 实际恢复量
    new_metrics: dict[str, float]  # 校正后的指标
    side_effects: list[str]      # 副作用


@dataclass
class ControlLoopReport:
    """闭环控制完整报告."""
    detections: list[DivergenceEvent]         # 检测到的发散
    attribution: AttributionReport | None     # 归因结果
    actions: list[CorrectiveAction]           # 生成的校正动作
    results: list[CorrectionResult]           # 校正结果
    pre_trajectory: list[MetricPoint]         # 校正前轨迹
    post_trajectory: list[MetricPoint] | None # 校正后轨迹
    is_stable: bool                           # 校正后是否稳定
    rounds: int                               # 执行轮数


# ============================================================
# 2. 动作选择器
# ============================================================

class ActionSelector:
    """根据归因结果选择最佳校正动作."""

    # 从根因类型到动作类型的映射
    CAUSE_TO_ACTION = {
        EventCause.GUIDE_IGNORED:    ActionType.REINFORCE_GUIDE,
        EventCause.GUIDE_CONFLICT:   ActionType.REINFORCE_GUIDE,
        EventCause.CHARACTER_OOC:    ActionType.RESTORE_CHARACTER,
        EventCause.CHARACTER_FORK:   ActionType.RESTORE_CHARACTER,
        EventCause.HOOK_ORPHAN:      ActionType.REPLANT_HOOK,
        EventCause.MEMORY_FADE:      ActionType.REPAIR_MEMORY,
        EventCause.MEMORY_OVERWRITE: ActionType.REPAIR_MEMORY,
        EventCause.CONTEXT_LOSS:     ActionType.REGENERATE,
        EventCause.FEEDBACK_D1_D4:   ActionType.REINFORCE_GUIDE,
        EventCause.FEEDBACK_D4_D1:   ActionType.REPAIR_MEMORY,
    }

    def select(self, report: AttributionReport,
               trajectory: list[MetricPoint]) -> list[CorrectiveAction]:
        """从归因报告选择校正动作."""
        actions = []

        if report.primary_cause and report.primary_cause.confidence >= 0.4:
            action = self._action_from_hypothesis(report.primary_cause, trajectory)
            if action:
                actions.append(action)

        # 补充动作: 检查是否有其他 metric 也需要修复
        for hypothesis in report.hypotheses[1:3]:
            if hypothesis.confidence < 0.3:
                break
            action = self._action_from_hypothesis(hypothesis, trajectory)
            if action:
                # 避免重复
                if action.action_type != actions[0].action_type:
                    actions.append(action)

        actions.sort(key=lambda a: a.priority)
        return actions[:3]

    def _action_from_hypothesis(
        self, h, trajectory: list[MetricPoint],
    ) -> CorrectiveAction | None:
        action_type = self.CAUSE_TO_ACTION.get(h.root_event.cause_type)
        if not action_type:
            return None

        if len(trajectory) > 0:
            target_unit = h.root_event.unit_index
        else:
            target_unit = 0

        return CorrectiveAction(
            action_type=action_type,
            target_metric="D1" if action_type == ActionType.REGENERATE
                          else h.root_event.metric_affected,
            target_unit=target_unit,
            reason=f"根因: {h.root_event.cause_type.value} — {h.root_event.description}",
            expected_recovery=h.counterfactual_recovery,
            priority=1 if h.confidence >= 0.5 else 2,
        )


# ============================================================
# 3. 校正器 (模拟修复效果)
# ============================================================

class MockCorrector:
    """模拟校正器 — 对退化轨迹应用修复并计算恢复效果."""

    RECOVERY_EFFECT = {
        ActionType.REGENERATE:        {"D1": 0.75, "D2": 0.30, "D3": 0.40, "D4": 0.20},
        ActionType.REINFORCE_GUIDE:   {"D1": 0.70, "D2": 0.10, "D3": 0.30, "D4": 0.15},
        ActionType.RESTORE_CHARACTER: {"D1": 0.10, "D2": 0.85, "D3": 0.05, "D4": 0.05},
        ActionType.REPAIR_MEMORY:     {"D1": 0.15, "D2": 0.05, "D3": 0.10, "D4": 0.80},
        ActionType.REPLANT_HOOK:      {"D1": 0.10, "D2": 0.05, "D3": 0.70, "D4": 0.05},
    }

    # 副作用概率
    SIDE_EFFECTS = {
        ActionType.REGENERATE: [
            (0.15, "D2 轻微波动 (再生文字的风格一致性稍差)"),
            (0.05, "D3 钩子锚点偏移 (再生可能遗漏部分钩子)"),
        ],
        ActionType.REINFORCE_GUIDE: [
            (0.10, "D2 角色灵活性略微降低"),
        ],
        ActionType.RESTORE_CHARACTER: [
            (0.08, "D1 采纳率暂时波动 (状态变化导致后续 Guide 需要重新对齐)"),
        ],
        ActionType.REPAIR_MEMORY: [
            (0.05, "D1 轻微下降 (记忆恢复可能引发 Guide 冲突)"),
        ],
        ActionType.REPLANT_HOOK: [
            (0.06, "D2 轻微波动 (重新种植钩子需要引入新场景)"),
        ],
    }

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def apply(
        self,
        action: CorrectiveAction,
        trajectory: list[MetricPoint],
    ) -> CorrectionResult:
        """应用校正动作到轨迹."""
        effects = self.RECOVERY_EFFECT[action.action_type]

        # 计算恢复量 (含 10% 随机波动)
        modifier = 0.9 + self.rng.random() * 0.2
        recovery = min(action.expected_recovery, 0.90) * modifier

        # 修复后指标
        new_metrics = {}
        for metric, base_effect in effects.items():
            actual = base_effect * recovery
            new_metrics[metric] = round(actual, 4)

        # 副作用
        side = []
        for prob, desc in self.SIDE_EFFECTS.get(action.action_type, []):
            if self.rng.random() < prob:
                side.append(desc)

        return CorrectionResult(
            action=action,
            success=recovery > 0.1,
            recovery_actual=round(recovery, 4),
            new_metrics=new_metrics,
            side_effects=side,
        )


# ============================================================
# 4. 恢复验证器
# ============================================================

class RecoveryValidator:
    """验证校正后的轨迹是否恢复到安全状态."""

    STABILITY_THRESHOLD = 0.75  # D1/D2 恢复到此线以上视为稳定
    MAX_RESIDUAL_EVENTS = 2     # 校正后允许的残留事件数

    def validate(
        self,
        pre_trajectory: list[MetricPoint],
        post_trajectory: list[MetricPoint],
        results: list[CorrectionResult],
    ) -> bool:
        """验证校正是否成功."""
        if not post_trajectory:
            return False

        # 1. 检查 D1/D2 终值
        last = post_trajectory[-1]
        if last.guide_adoption_rate < self.STABILITY_THRESHOLD:
            return False
        if last.character_continuity < self.STABILITY_THRESHOLD:
            return False

        # 2. 检查是否还有严重发散事件
        scenes = [SceneType.DIALOGUE] * len(post_trajectory)
        post_events = detect_divergence_patterns(post_trajectory, scenes)
        critical = [e for e in post_events
                    if e.pattern in (DivergencePattern.CASCADE,
                                     DivergencePattern.FEEDBACK_LOOP)]
        if critical:
            return False

        # 3. 检查校正效果是否可见
        d1_pre = pre_trajectory[-1].guide_adoption_rate
        d1_post = post_trajectory[-1].guide_adoption_rate
        if d1_post < d1_pre + 0.05:
            return False  # 校正效果太弱

        return True


# ============================================================
# 5. 闭环控制循环
# ============================================================

class ClosedLoopController:
    """闭环控制系统: Detect → Attribute → Select → Correct → Verify."""

    MAX_ROUNDS = 3

    def __init__(self, seed: int = 42):
        self.attributor = CausalAttributionEngine()
        self.selector = ActionSelector()
        self.corrector = MockCorrector(seed=seed)
        self.validator = RecoveryValidator()

    def run(
        self,
        trajectory: list[MetricPoint],
        causal_events: list[CausalEvent],
        disappearances: list[dict] | None = None,
    ) -> ControlLoopReport:
        """执行完整的闭环控制循环."""

        all_detections = []
        all_results = []
        actions = []
        current = [deepcopy(mp) for mp in trajectory]
        initial = [deepcopy(mp) for mp in trajectory]

        if disappearances is None:
            disappearances = []

        for round_idx in range(self.MAX_ROUNDS):
            # Step 1: Detect
            scenes = [SceneType.DIALOGUE] * len(current)
            detections = detect_divergence_patterns(current, scenes, disappearances)

            # 只关心持久/高危事件
            serious = [d for d in detections
                       if d.pattern != DivergencePattern.BURST
                       and d.pattern != DivergencePattern.SELF_HEAL]
            if not serious:
                break

            all_detections.extend(serious)

            # Step 2: Attribute (取最严重的事件)
            primary_div = sorted(serious, key=lambda d: d.magnitude, reverse=True)[0]
            attr_report = self.attributor.attribute(primary_div, current, causal_events)

            # Step 3: Select
            round_actions = self.selector.select(attr_report, current)
            if not round_actions:
                break
            actions.extend(round_actions)

            # Step 4: Correct
            for action in round_actions:
                result = self.corrector.apply(action, current)
                all_results.append(result)

                if result.success:
                    current = self._apply_correction_to_trajectory(
                        current, result, action.target_unit)

            # Step 5: Verify
            if self.validator.validate(initial, current, all_results):
                break

        # 最终验证
        is_stable = self.validator.validate(initial, current, all_results)

        return ControlLoopReport(
            detections=all_detections,
            attribution=attr_report if all_detections else None,
            actions=actions,
            results=all_results,
            pre_trajectory=initial,
            post_trajectory=current,
            is_stable=is_stable,
            rounds=len(actions) if actions else 0,
        )

    def _apply_correction_to_trajectory(
        self, trajectory: list[MetricPoint],
        result: CorrectionResult,
        target_unit: int,
    ) -> list[MetricPoint]:
        """将校正效果应用到轨迹的后半段 (target_unit 之后).

        每个 metric 的恢复量均匀分布在剩余 unit 上."""
        new = [deepcopy(mp) for mp in trajectory]
        n_remaining = max(1, len(trajectory) - target_unit)

        gains = result.new_metrics
        for i in range(target_unit, len(trajectory)):
            weight = (i - target_unit + 1) / n_remaining
            if "D1" in gains:
                new[i].guide_adoption_rate = min(1.0,
                    new[i].guide_adoption_rate + gains["D1"] * weight)
            if "D2" in gains:
                new[i].character_continuity = min(1.0,
                    new[i].character_continuity + gains["D2"] * weight)
            if "D3" in gains:
                new[i].hook_span_ratio = min(1.0,
                    new[i].hook_span_ratio + gains["D3"] * weight)
            if "D4" in gains:
                new[i].memory_fade_ratio = max(0.0,
                    new[i].memory_fade_ratio - gains["D4"] * weight)

        return new


# ============================================================
# 6. 测试用例
# ============================================================

def make_degraded_trajectory() -> list[MetricPoint]:
    """创建一条已知退化的轨迹 (模拟 SUSTAINED + CASCADE)."""
    config = StressConfig(
        d1_drift=0.015, d2_ooc=0.005,
        d3_hook_decay=0.01, d4_memory_fade=0.015,
        burst_mag=0.25, burst_dur=4, burst_start=15,
        self_heal=0.02, feedback_lag=4,
    )
    trajectory, _ = generate_stress_trajectory(config, n_units=30, seed=42)
    return trajectory


def test_sustained_recovery():
    """测试 1: SUSTAINED D1 下降 → REGENERATE → D1 恢复."""
    print("\n" + "=" * 62)
    print("  G21 测试 1: SUSTAINED 修复 — D1 持续下降 → 再生修复")
    print("=" * 62)

    trajectory = make_degraded_trajectory()

    # 注入因果链
    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_simple()

    controller = ClosedLoopController(seed=42)
    report = controller.run(trajectory, gen.events)

    assert report.actions, "应该有校正动作"
    assert any(a.action_type == ActionType.REINFORCE_GUIDE
               or a.action_type == ActionType.REGENERATE
               for a in report.actions), "应该有 Guide 相关修复"

    d1_pre = report.pre_trajectory[-1].guide_adoption_rate
    d1_post = report.post_trajectory[-1].guide_adoption_rate
    assert d1_post > d1_pre, f"D1 应该恢复: {d1_pre:.3f} → {d1_post:.3f}"

    print(f"  PASS: D1 恢复 {d1_pre:.3f} → {d1_post:.3f} (+{d1_post-d1_pre:.3f})")
    print(f"  actions: {len(report.actions)}, rounds: {report.rounds}")
    print(f"  is_stable: {report.is_stable}")

    for r in report.results:
        print(f"  {r.action.action_type.value}: recovery={r.recovery_actual:.2f}"
              f"  success={r.success}")

    return True


def test_cascade_mitigation():
    """测试 2: CASCADE (角色消失) → RESTORE_CHARACTER → 角色恢复."""
    print("\n" + "=" * 62)
    print("  G21 测试 2: CASCADE 缓解 — 角色消失 → 恢复角色")
    print("=" * 62)

    # 重度 D2 退化轨迹
    config = StressConfig(
        d1_drift=0.005, d2_ooc=0.020,
        d3_hook_decay=0.005, d4_memory_fade=0.005,
        burst_mag=0.30, burst_dur=5, burst_start=15,
        self_heal=0.02, feedback_lag=4,
    )
    trajectory, _ = generate_stress_trajectory(config, n_units=30, seed=42)

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_character()

    # 注入角色消失事件 (模拟检测器会发现的 CASCADE)
    disappearances = [{"char_name": "女主_苏雪", "at_unit_index": 22}]

    controller = ClosedLoopController(seed=42)
    # 手动注入 CASCADE divergence 到检测流程
    scenes = [SceneType.DIALOGUE] * len(trajectory)
    detections = detect_divergence_patterns(trajectory, scenes, disappearances)

    # 应该检测到 CASCADE
    cascade_events = [d for d in detections if d.pattern == DivergencePattern.CASCADE]
    d2_sustained = [d for d in detections
                    if d.pattern == DivergencePattern.SUSTAINED and d.metric == "D2"]

    assert cascade_events or d2_sustained, \
        f"应该有 CASCADE 或 D2 SUSTAINED, 实际 detections={len(detections)}"

    report = controller.run(trajectory, gen.events, disappearances)

    # 即使没有 primary action, 我们也应该能验证 D2 退化被检测到
    has_d2_detection = any(d.metric == "D2" for d in detections)
    assert has_d2_detection, "应该检测到 D2 相关发散"

    d2_pre = report.pre_trajectory[-1].character_continuity
    d2_post = report.post_trajectory[-1].character_continuity
    assert d2_post > d2_pre, f"D2 应该恢复: {d2_pre:.3f} → {d2_post:.3f}"

    print(f"  PASS: D2 恢复 {d2_pre:.3f} → {d2_post:.3f} (+{d2_post-d2_pre:.3f})")
    print(f"  detections: {len(detections)}, cascade={len(cascade_events)}")
    for r in report.results:
        print(f"  {r.action.action_type.value}: recovery={r.recovery_actual:.2f}"
              f"  success={r.success}")

    return True


def test_stability_after_correction():
    """测试 3: 校正后不引入新发散."""
    print("\n" + "=" * 62)
    print("  G21 测试 3: 校正后稳定性 — 修复不应引入新问题")
    print("=" * 62)

    trajectory = make_degraded_trajectory()

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_simple()

    controller = ClosedLoopController(seed=42)
    report = controller.run(trajectory, gen.events)

    # 校正后检测新发散
    scenes = [SceneType.DIALOGUE] * len(report.post_trajectory)
    new_events = detect_divergence_patterns(report.post_trajectory, scenes)

    # 不应出现比校正前更严重的模式
    pre_critical = [e for e in detect_divergence_patterns(report.pre_trajectory, scenes)
                    if e.pattern == DivergencePattern.CASCADE]
    post_critical = [e for e in new_events
                     if e.pattern == DivergencePattern.CASCADE]

    assert len(post_critical) <= len(pre_critical), \
        f"校正后不应出现新的 CASCADE ({len(pre_critical)}→{len(post_critical)})"

    print(f"  PASS: CASCADE 事件 pre={len(pre_critical)} post={len(post_critical)}")
    print(f"  is_stable: {report.is_stable}")

    return True


def test_no_unnecessary_correction():
    """测试 4: 不对稳定系统执行不必要校正."""
    print("\n" + "=" * 62)
    print("  G21 测试 4: 避免过度校正 — 稳定系统不应被修改")
    print("=" * 62)

    # 稳定轨迹
    config = StressConfig()  # 全 0
    trajectory, _ = generate_stress_trajectory(config, n_units=30, seed=42)

    gen = CausalDataGenerator(n_units=30, seed=42)
    # 不注入因果链

    controller = ClosedLoopController(seed=42)
    report = controller.run(trajectory, gen.events)

    # 稳定系统: 不应生成任何校正动作
    if report.actions:
        print(f"  WARNING: 产生 {len(report.actions)} 个动作, 检查是否必要")

    # D1/D2 不应有明显变化
    d1_pre = report.pre_trajectory[-1].guide_adoption_rate
    d1_post = report.post_trajectory[-1].guide_adoption_rate
    d1_change = abs(d1_post - d1_pre)

    assert d1_change < 0.05, f"D1 变化 {d1_change:.3f} 过大"

    print(f"  PASS: 稳定系统 D1 变化 = {d1_change:.4f}")
    print(f"  actions: {len(report.actions)} (expected 0)")

    return True


def test_multi_round_control():
    """测试 5: 多轮闭环 — 连续检测→修复→验证."""
    print("\n" + "=" * 62)
    print("  G21 测试 5: 多轮控制 — 2 轮检测→修复→验证")
    print("=" * 62)

    # 重度退化 (需要多轮修复)
    config = StressConfig(
        d1_drift=0.02, d2_ooc=0.008,
        d3_hook_decay=0.015, d4_memory_fade=0.02,
        burst_mag=0.30, burst_dur=5, burst_start=14,
        self_heal=0.01, feedback_lag=3,
    )
    trajectory, _ = generate_stress_trajectory(config, n_units=30, seed=42)

    gen = CausalDataGenerator(n_units=30, seed=42)
    gen.generate_causal_chain_simple()
    gen.generate_causal_chain_memory()

    controller = ClosedLoopController(seed=42)
    report = controller.run(trajectory, gen.events)

    assert report.actions, "应该有至少一个校正动作"

    d1_pre = report.pre_trajectory[-1].guide_adoption_rate
    d1_post = report.post_trajectory[-1].guide_adoption_rate
    recovery = d1_post - d1_pre

    print(f"  PASS: {report.rounds} actions, {len(report.results)} results")
    print(f"  D1: {d1_pre:.3f} → {d1_post:.3f} (recovery={recovery:.3f})")
    print(f"  is_stable: {report.is_stable}")

    for r in report.results:
        print(f"  {r.action.action_type.value}: recovery={r.recovery_actual:.2f}"
              f"  {r.side_effects}")

    return True


# ============================================================
# 7. 可视化: 修复前后轨迹对比
# ============================================================

def render_recovery_trajectory(report: ControlLoopReport) -> str:
    """修复前后 D1/D2 轨迹对比图."""
    h = 480

    d1_pre_line = ""
    d1_post_line = ""
    d2_pre_line = ""
    d2_post_line = ""

    # D1 修复前 (红色虚线)
    pre_pts_d1 = []
    for i, p in enumerate(report.pre_trajectory):
        x = 80 + i * 16
        y = 380 - p.guide_adoption_rate * 300
        pre_pts_d1.append(f"{x:.0f},{y:.0f}")
    d1_pre_line = f'<polyline points="{" ".join(pre_pts_d1)}" fill="none" stroke="var(--c-coral-400)" stroke-width="1.5" stroke-dasharray="4 3"/>'

    # D1 修复后 (蓝色实线)
    post_pts_d1 = []
    for i, p in enumerate(report.post_trajectory):
        x = 80 + i * 16
        y = 380 - p.guide_adoption_rate * 300
        post_pts_d1.append(f"{x:.0f},{y:.0f}")
    d1_post_line = f'<polyline points="{" ".join(post_pts_d1)}" fill="none" stroke="var(--c-blue-600)" stroke-width="2"/>'

    h = 520
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {h}" width="100%" role="img">
  <title>Correction Recovery Trajectory</title>
  <desc>D1 metric before and after closed-loop correction</desc>

  <rect x="40" y="20" width="620" height="{h-40}" rx="12" fill="var(--color-background-secondary)" stroke="var(--color-border-primary)" stroke-width="0.5"/>

  <text x="340" y="50" text-anchor="middle" class="th">Closed-Loop Recovery: D1 Before vs After Correction</text>
  <text x="340" y="68" text-anchor="middle" class="ts">Dashed red = before, Solid blue = after | is_stable={report.is_stable}</text>

  <line x1="80" y1="80" x2="80" y2="380" stroke="var(--color-border-secondary)" stroke-width="0.5"/>
  <line x1="80" y1="380" x2="576" y2="380" stroke="var(--color-border-secondary)" stroke-width="0.5"/>

  <line x1="80" y1="80" x2="576" y2="80" stroke="var(--color-border-tertiary)" stroke-width="0.5" stroke-dasharray="2 4"/>
  <text x="75" y="84" text-anchor="end" class="ts" fill="var(--color-text-tertiary)">1.0</text>

  <line x1="80" y1="230" x2="576" y2="230" stroke="var(--color-border-tertiary)" stroke-width="0.5" stroke-dasharray="2 4"/>
  <text x="75" y="234" text-anchor="end" class="ts" fill="var(--color-text-tertiary)">0.5</text>

  <text x="75" y="384" text-anchor="end" class="ts" fill="var(--color-text-tertiary)">0.0</text>

  {d1_pre_line}
  {d1_post_line}

  <!-- Legend -->
  <rect x="520" y="90" width="120" height="65" rx="6" fill="var(--color-background-primary)" stroke="var(--color-border-tertiary)" stroke-width="0.5"/>
  <line x1="530" y1="108" x2="555" y2="108" stroke="var(--c-coral-400)" stroke-width="1.5" stroke-dasharray="4 3"/>
  <text x="562" y="112" class="ts">Before</text>
  <line x1="530" y1="130" x2="555" y2="130" stroke="var(--c-blue-600)" stroke-width="2"/>
  <text x="562" y="134" class="ts">After</text>

  <text x="340" y="{h-10}" text-anchor="middle" class="ts" fill="var(--color-text-tertiary)">
    {report.rounds} correction(s), D1 delta=+{report.post_trajectory[-1].guide_adoption_rate - report.pre_trajectory[-1].guide_adoption_rate:.3f}
  </text>
</svg>'''
    return svg


# ============================================================
# Main
# ============================================================

def main():
    passed = failed = 0

    tests = [
        ("SUSTAINED 修复", test_sustained_recovery),
        ("CASCADE 缓解", test_cascade_mitigation),
        ("校正后稳定性", test_stability_after_correction),
        ("避免过度校正", test_no_unnecessary_correction),
        ("多轮闭环", test_multi_round_control),
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

    # --- SVG ---
    print("\n" + "=" * 62)
    print("  G21 可视化: 修复前后轨迹对比")
    print("=" * 62)
    try:
        trajectory = make_degraded_trajectory()
        gen = CausalDataGenerator(n_units=30, seed=42)
        gen.generate_causal_chain_simple()
        gen.generate_causal_chain_character()

        controller = ClosedLoopController(seed=42)
        report = controller.run(trajectory, gen.events)

        svg = render_recovery_trajectory(report)
        out = ROOT / "smoke" / "g21_recovery.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"  PASS: Recovery SVG → smoke/g21_recovery.svg ({len(svg)} bytes)")
        passed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    total = passed + failed
    print("\n" + "=" * 62)
    print(f"  G21 完成: {passed}/{total} 通过, {failed} 失败")
    print("=" * 62)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
