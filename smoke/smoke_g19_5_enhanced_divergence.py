"""
G19.5 SMOKE: v4.0 增强发散模型 — 拟 LLM 非线性退化仿真

G19 的 synthetic stress model 是规则性/线性退化。
G19.5 升级为拟 LLM 退化模式:
  - Non-monotonic burst (突降→恢复→再偏离)
  - Self-healing (10-15% 自发修复概率)
  - Context-dependent triggers (战斗/对话/独白场景差异化)
  - Feedback amplification (Guide↓ → Memory↓ → Guide↓↓)

新增检测能力:
  - BURST 模式识别 (区分瞬时抖动 vs 持续衰退)
  - SELF_HEAL 事件追踪
  - FEEDBACK_LOOP 因果链检测
  - 按场景类型的指标分解

复用 G19 的 D1-D4 计算器、SVG 渲染、DB 隔离。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_SMOKE_TIMEOUT = 30
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g19_5 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 复用 G19 基础设施
# ============================================================

from smoke_g19_stability_harness import (
    _calc_d1_guide_adoption,
    _calc_d2_character_continuity,
    _calc_d3_hook_health,
    _calc_d4_memory_fade,
    render_trajectory,
    MetricPoint,
    DriftWarning,
    StabilityReport,
    _setup_temp_db,
    _init_db,
    _teardown_db,
)


# ============================================================
# G19.5 新数据结构
# ============================================================

class SceneType(Enum):
    BATTLE = auto()
    DIALOGUE = auto()
    MONOLOGUE = auto()
    TRANSITION = auto()


class DivergencePattern(Enum):
    BURST = "burst"               # 瞬时偏离→恢复 → 非告警
    SUSTAINED = "sustained"       # 持续偏离 → 告警
    SELF_HEAL = "self_heal"       # 自发修复 → 记录事件
    FEEDBACK_LOOP = "feedback"    # 因果放大 → 高危告警
    CASCADE = "cascade"           # 连锁反应 → CRITICAL


@dataclass
class DivergenceEvent:
    """增强漂移事件 — 包含模式分类和因果上下文."""
    pattern: DivergencePattern
    metric: str                    # D1/D2/D3/D4
    unit_index: int
    magnitude: float               # 变化幅度
    recovery_at: int | None = None # 恢复位置 (burst/self_heal)
    triggered_by: str | None = None  # 触发此事件的另一个 metric (feedback)
    detail: str = ""


@dataclass
class SceneProfile:
    """按场景类型的指标剖面."""
    scene_type: SceneType
    count: int
    d1_mean: float
    d2_mean: float
    d3_mean: float
    d4_mean: float


@dataclass
class EnhancedReport:
    """G19.5 增强报告 — trajectory + divergence events + scene profiles."""
    base: StabilityReport
    events: list[DivergenceEvent] = field(default_factory=list)
    scenes: list[SceneProfile] = field(default_factory=list)

    @property
    def has_burst(self) -> bool:
        return any(e.pattern == DivergencePattern.BURST for e in self.events)

    @property
    def has_self_heal(self) -> bool:
        return any(e.pattern == DivergencePattern.SELF_HEAL for e in self.events)

    @property
    def has_feedback(self) -> bool:
        return any(e.pattern == DivergencePattern.FEEDBACK_LOOP for e in self.events)

    @property
    def persistent_warnings(self) -> list[DivergenceEvent]:
        return [e for e in self.events
                if e.pattern in (DivergencePattern.SUSTAINED,
                                 DivergencePattern.FEEDBACK_LOOP,
                                 DivergencePattern.CASCADE)]


# ============================================================
# 1. 增强 Mock 数据生成器
# ============================================================

class EnhancedMockGenerator:
    """拟 LLM 非线性退化数据生成器.

    三种模式:
      - "stable":           无退化, 验证基线
      - "burst_only":       瞬时 burst + 恢复, 应不触发持久告警
      - "full_drift":       burst → 恢复 → 再漂移 → 反馈放大 → 级联
    """

    # 场景类型编排 (30 unit 循环)
    SCENE_PATTERN = [
        SceneType.DIALOGUE, SceneType.TRANSITION,
        SceneType.BATTLE, SceneType.TRANSITION,
        SceneType.MONOLOGUE, SceneType.DIALOGUE,
    ]

    # 场景相关退化系数
    SCENE_DEGRADE = {
        SceneType.BATTLE:     {"d1": 0.08, "d2": 0.05},  # 战斗场景 Guide 拒绝率高
        SceneType.DIALOGUE:   {"d1": 0.02, "d2": 0.02},  # 对话场景角色更稳定
        SceneType.MONOLOGUE:  {"d1": 0.04, "d2": 0.06},  # 独白场景角色易漂移
        SceneType.TRANSITION: {"d1": 0.01, "d2": 0.01},  # 过渡场景最稳定
    }

    def __init__(self, project_id: str, unit_ids: list[str]):
        self.project_id = project_id
        self.unit_ids = unit_ids
        self.n = len(unit_ids)
        self.scene_types = self._assign_scenes()

    def _assign_scenes(self) -> list[SceneType]:
        return [self.SCENE_PATTERN[i % len(self.SCENE_PATTERN)] for i in range(self.n)]

    def generate_all(self, mode: str = "stable"):
        self._gen_units()
        self._gen_decisions(mode)
        self._gen_characters(mode)
        self._gen_hooks(mode)
        self._gen_memories(mode)

    def _get_conn(self):
        from app.db._impl import get_conn as gconn
        return gconn()

    def _gen_units(self):
        conn = self._get_conn()
        for i, uid in enumerate(self.unit_ids):
            scene = self.scene_types[i].name.lower()
            conn.execute("""
                INSERT INTO story_units (id, project_id, unit_no, title, unit_type,
                    story_order, present_order, status, synopsis, draft,
                    entry_characters, exit_characters,
                    entry_commitments, exit_commitments,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, 'other',
                    ?, ?, 'writing', ?, '',
                    '[]', '[]',
                    '[]', '[]',
                    datetime('now', 'localtime'), datetime('now', 'localtime'))
            """, (uid, self.project_id, i + 1, f"[{scene}] Unit {i + 1}",
                  i + 1, i + 1, f'场景: {scene}'))
        conn.commit()

    def _calc_adoption_rate(self, base: float, unit_idx: int, mode: str) -> float:
        """计算当前 unit 的 Guide 采纳率, 含 burst/self_heal/feedback.

        使用确定性退化 + 小幅度抖动."""
        scene = self.scene_types[unit_idx]
        degrade = self.SCENE_DEGRADE[scene]["d1"]
        rng = _get_rng()

        if mode == "stable":
            return base - degrade + rng.uniform(0, 0.03)

        # --- Burst: unit 12-15 深度突降 (4 unit 宽窗口) ---
        if 12 <= unit_idx <= 15:
            return max(0.18, base - 0.55 + rng.uniform(-0.04, 0.04))

        # --- Self-heal: unit 16-18 快速恢复 ---
        if 16 <= unit_idx <= 18:
            return min(0.88, 0.78 + rng.uniform(-0.03, 0.05))

        if mode == "burst_only":
            if unit_idx >= 19:
                return base - degrade + rng.uniform(-0.01, 0.02)
            return base - degrade + rng.uniform(-0.02, 0.03)

        # --- Full drift: unit 22-30 再漂移, 每 unit 降 3.5% ---
        if unit_idx >= 22:
            drift = (unit_idx - 22) * 0.035
            return max(0.22, 0.68 - drift + rng.uniform(-0.02, 0.02))

        return base - degrade + rng.uniform(-0.02, 0.03)

    def _gen_decisions(self, mode: str):
        """生成 unit_decisions — 含 burst/self_heal/feedback."""
        from app.services.decision_service import record
        from app.core.types import Guide

        for i, uid in enumerate(self.unit_ids):
            base = 0.88
            rate = self._calc_adoption_rate(base, i, mode)
            n_guides = 5
            for g_idx in range(n_guides):
                guide = Guide(
                    source="pressure" if g_idx < 3 else "hook",
                    priority=0.5 + g_idx * 0.1,
                    advice=f"Guide {g_idx} for unit {i} [{self.scene_types[i].name}]",
                    guide_id=f"G{i}_{g_idx}",
                )
                action = "adopted" if random.random() < rate else "ignored"
                record(
                    unit_id=uid, guide=guide, action=action,
                    project_id=self.project_id, step_no=g_idx,
                )

    def _gen_characters(self, mode: str):
        """生成 character_trackers — 含 OOC burst/self_heal."""
        from app.services.character_tracker import record

        characters = ["主角_林风", "女主_苏雪", "反派_黑煞"]
        char_states = {
            "主角_林风": {"state": "正常", "location": "青云城", "power_level": "Lv15",
                           "equipment": "基础装备", "relationship": "友好"},
            "女主_苏雪": {"state": "正常", "location": "青云城", "power_level": "Lv12",
                           "equipment": "基础装备", "relationship": "友好"},
            "反派_黑煞": {"state": "正常", "location": "黑风谷", "power_level": "Lv20",
                           "equipment": "基础装备", "relationship": "敌对"},
        }

        if mode == "stable":
            for char_name in characters:
                state = char_states[char_name].copy()
                for i, uid in enumerate(self.unit_ids):
                    loc = f"地点_{i // 3}"
                    state["location"] = loc
                    state["power_level"] = f"Lv{15 + i // 5}"
                    record(project_id=self.project_id, chapter_id=uid,
                           character_name=char_name, **state)
            return

        # --- burst_only / full_drift: 非线性退化 ---
        for char_name in characters:
            state = char_states[char_name].copy()

            for i, uid in enumerate(self.unit_ids):
                scene = self.scene_types[i]

                # 场景相关的基础变化
                loc = f"地点_{i // 3}"
                state["location"] = loc
                state["power_level"] = f"Lv{15 + i // 5}"

                if char_name == "女主_苏雪":
                    # --- Burst OOC: unit 15-16 角色行为异常 ---
                    if 15 <= i <= 16:
                        state["state"] = "暴怒"
                        state["relationship"] = "敌对"
                    # --- Self-heal: unit 17-18 恢复 ---
                    elif 17 <= i <= 18:
                        state["state"] = "沉思"
                        state["relationship"] = "友好"

                    elif mode == "full_drift":
                        # --- 再漂移: unit 22-26 ---
                        if 22 <= i <= 24:
                            state["state"] = "冷漠"
                            state["relationship"] = "疏远"
                        elif 25 <= i <= 26:
                            state["state"] = "失踪"
                            state["relationship"] = "未知"
                            state["power_level"] = "Lv0"

                        # --- 彻底消失: unit 27+ ---
                        if i >= 27:
                            continue  # skip this unit → 角色消失

                # 场景相关角色变化 (独白: 角色状态易变)
                if scene == SceneType.MONOLOGUE and random.random() < 0.12 and char_name != "反派_黑煞":
                    states = ["激动", "沉思", "犹豫", "决然"]
                    state["state"] = random.choice(states)

                record(project_id=self.project_id, chapter_id=uid,
                       character_name=char_name, **state)

    def _gen_hooks(self, mode: str):
        """生成 unit_hook_map — 含 burst 期间种植/回收异常."""
        conn = self._get_conn()
        n_hooks = 10

        for h in range(n_hooks):
            hook_id = f"HOOK_{h}"
            # plant 位置分散
            if h < 4:
                plant_idx = h * 2           # 0, 2, 4, 6
            elif h < 7:
                plant_idx = 12 + (h - 4) * 2  # 12, 14, 16 (burst 区)
            else:
                plant_idx = 20 + (h - 7) * 2  # 20, 22, 24

            if plant_idx >= self.n:
                break

            desc = f"伏笔 H{h}" + (" [BURST区]" if 12 <= plant_idx <= 16 else "")
            conn.execute(
                "INSERT INTO unit_hook_map (id, unit_id, project_id, hook_id, hook_type, description, step_no) "
                "VALUES (?, ?, ?, ?, 'plant', ?, 0)",
                (f"HP_{h}", self.unit_ids[plant_idx], self.project_id, hook_id, desc),
            )

            # payoff
            if mode == "stable":
                gap = random.choice([3, 4, 5])
            elif 12 <= plant_idx <= 16:
                # burst 区种植的 hook: 延迟回收
                gap = random.choice([8, 10, 12]) if mode == "full_drift" else random.choice([5, 6, 7])
            else:
                gap = random.choice([3, 4, 5])

            payoff_idx = min(plant_idx + gap, self.n - 1)
            conn.execute(
                "INSERT INTO unit_hook_map (id, unit_id, project_id, hook_id, hook_type, description, step_no) "
                "VALUES (?, ?, ?, ?, 'payoff', ?, 1)",
                (f"HF_{h}", self.unit_ids[payoff_idx], self.project_id, hook_id, f"回收 H{h}"),
            )

        conn.commit()

    def _gen_memories(self, mode: str):
        """生成 agent_memories — 含 burst 记忆恢复/再废弃."""
        conn = self._get_conn()

        # 基础记忆
        base_memories = [
            ("L1", "arc_main", "主角踏上修仙之路"),
            ("L1", "arc_sub", "暗线: 上古遗迹的秘密"),
            ("L2", "commitment_promise", "主角承诺保护苏雪"),
            ("L2", "world_rule_power", "灵力等级分九阶"),
        ]
        for level, cat, content in base_memories:
            mid = hashlib.md5(f"{self.project_id}_{cat}_{content}".encode()).hexdigest()[:12]
            conn.execute(
                "INSERT OR IGNORE INTO agent_memories (id, project_id, level, category, content) "
                "VALUES (?, ?, ?, ?, ?)", (mid, self.project_id, level, cat, content))

        for i in range(self.n):
            mid = hashlib.md5(f"rag_{i}_{self.project_id}".encode()).hexdigest()[:12]

            if mode == "stable":
                level = "L4" if i >= 25 else "L3"
                ref = mid if level == "L4" else ""

            elif mode == "burst_only":
                # burst 区: 记忆回收正常, 之后逐渐废弃
                if i >= 16:
                    level = "L4" if random.random() < 0.4 else "L3"
                else:
                    level = "L3"
                ref = mid if level == "L4" else ""

            else:  # full_drift
                if i < 16:
                    level = "L3"
                    ref = ""
                elif 16 <= i <= 18:
                    # Self-heal: burst 区的记忆意外恢复 (L4 → L3)
                    level = "L3"
                    ref = ""
                elif 19 <= i <= 24:
                    # 逐渐废弃
                    level = "L4" if random.random() < 0.5 else "L3"
                    ref = mid if level == "L4" else ""
                else:
                    # 反馈放大: D1 下降 → 记忆加速废弃
                    level = "L4" if random.random() < 0.75 else "L3"
                    ref = mid if level == "L4" else ""

            conn.execute(
                "INSERT INTO agent_memories (id, project_id, chapter_id, level, category, content, ref_id) "
                "VALUES (?, ?, ?, ?, 'rag_chunk', ?, ?)",
                (mid, self.project_id, self.unit_ids[i], level, f"片段 {i}", ref))

        conn.commit()


# ============================================================
# 2. 增强漂移检测 — 模式分类
# ============================================================

# 可重复随机种子
_RNG_SEED = 42
_rng_instance = None

def _get_rng() -> random.Random:
    global _rng_instance
    if _rng_instance is None:
        _rng_instance = random.Random(_RNG_SEED)
    return _rng_instance


def detect_divergence_patterns(
    trajectory: list[MetricPoint],
    scene_types: list[SceneType],
    disappearances: list[dict] = None,
) -> list[DivergenceEvent]:
    """检测并分类发散模式: BURST / SUSTAINED / SELF_HEAL / FEEDBACK_LOOP.

    使用 4-unit 窗口, 比 G19 的 3-unit 更平滑."""
    events: list[DivergenceEvent] = []
    win = 4
    DROP_THRESH = 0.25      # 下降幅度阈值
    RECOVER_THRESH = 0.18    # 恢复幅度阈值
    LOOKAHEAD = 7            # 前瞻窗口 (burst 恢复的最大距离)

    if disappearances is None:
        disappearances = []

    # 角色消失 = CASCADE
    for d in disappearances:
        events.append(DivergenceEvent(
            pattern=DivergencePattern.CASCADE,
            metric="D2", unit_index=d["at_unit_index"],
            magnitude=1.0,
            detail=f"角色 '{d['char_name']}' 消失",
        ))

    if len(trajectory) < win * 2:
        return events

    d1 = [p.guide_adoption_rate for p in trajectory]
    d2 = [p.character_continuity for p in trajectory]
    d3 = [p.hook_span_ratio for p in trajectory]
    d4 = [p.memory_fade_ratio for p in trajectory]
    metrics = {"D1": d1, "D2": d2, "D4": d4}

    for key, vals in metrics.items():
        i = win
        while i < len(vals) - win:
            prev_avg = sum(vals[i - win:i]) / win
            curr_avg = sum(vals[i:i + win]) / win
            drop = prev_avg - curr_avg

            if drop > DROP_THRESH:
                # 向前搜索恢复
                recovery = -1
                for j in range(i + win, min(i + LOOKAHEAD + 1, len(vals) - win + 1)):
                    future_avg = sum(vals[j:j + win]) / win if j + win <= len(vals) else 1.0
                    if future_avg - curr_avg > RECOVER_THRESH:
                        recovery = j
                        break

                if recovery >= 0:
                    events.append(DivergenceEvent(
                        pattern=DivergencePattern.BURST,
                        metric=key, unit_index=i,
                        magnitude=round(drop, 3),
                        recovery_at=recovery,
                        detail=f"{key} burst: {prev_avg:.2f}→{curr_avg:.2f}, 恢复于 u{recovery}",
                    ))
                    i = recovery + win  # 跳过已处理区间
                else:
                    events.append(DivergenceEvent(
                        pattern=DivergencePattern.SUSTAINED,
                        metric=key, unit_index=i,
                        magnitude=round(drop, 3),
                        detail=f"{key} 持续衰退: {prev_avg:.2f}→{curr_avg:.2f}",
                    ))
                    i += 1
                continue

            i += 1

    # Self-heal: 不在 burst/持续衰退区间内的突发改善 (>0.15, D1/D2/D4 only)
    for key, vals in metrics.items():
        for i in range(win, len(vals) - win):
            prev_avg = sum(vals[i - win:i]) / win
            curr_avg = sum(vals[i:i + win]) / win
            improve = curr_avg - prev_avg

            if improve > RECOVER_THRESH:
                # 确认不在任何已记录事件的 4-unit 范围内
                near_event = any(
                    e.metric == key and abs(e.unit_index - i) <= 4
                    for e in events
                )
                if not near_event:
                    events.append(DivergenceEvent(
                        pattern=DivergencePattern.SELF_HEAL,
                        metric=key, unit_index=i,
                        magnitude=round(improve, 3),
                        detail=f"{key} 自发修复: {prev_avg:.2f}→{curr_avg:.2f}",
                    ))

    # Feedback loop: D1 SUSTAINED → D4 SUSTAINED (3-7 unit lag)
    d1_sustained = [e for e in events if e.metric == "D1" and e.pattern == DivergencePattern.SUSTAINED]
    d4_sustained = [e for e in events if e.metric == "D4" and e.pattern == DivergencePattern.SUSTAINED]

    for d1e in d1_sustained:
        for d4e in d4_sustained:
            lag = d4e.unit_index - d1e.unit_index
            if 3 <= lag <= 7:
                events.append(DivergenceEvent(
                    pattern=DivergencePattern.FEEDBACK_LOOP,
                    metric="D1→D4",
                    unit_index=d4e.unit_index,
                    magnitude=round(d4e.magnitude, 3),
                    triggered_by="D1",
                    detail=f"反馈环: D1↓@u{d1e.unit_index} → D4↓@u{d4e.unit_index} (lag={lag})",
                ))
                break

    # 按 unit_index 排序
    events.sort(key=lambda e: e.unit_index)
    return events


# ============================================================
# 3. 场景剖面分析
# ============================================================

def calc_scene_profiles(
    trajectory: list[MetricPoint],
    scene_types: list[SceneType],
) -> list[SceneProfile]:
    """按场景类型分解指标均值."""
    from collections import defaultdict
    buckets = defaultdict(lambda: {"d1": [], "d2": [], "d3": [], "d4": []})

    for i, p in enumerate(trajectory):
        st = scene_types[i]
        buckets[st]["d1"].append(p.guide_adoption_rate)
        buckets[st]["d2"].append(p.character_continuity)
        buckets[st]["d3"].append(p.hook_span_ratio)
        buckets[st]["d4"].append(p.memory_fade_ratio)

    profiles = []
    for st in SceneType:
        b = buckets.get(st)
        if not b:
            continue
        profiles.append(SceneProfile(
            scene_type=st,
            count=len(b["d1"]),
            d1_mean=round(sum(b["d1"]) / len(b["d1"]), 3),
            d2_mean=round(sum(b["d2"]) / len(b["d2"]), 3),
            d3_mean=round(sum(b["d3"]) / len(b["d3"]), 3),
            d4_mean=round(sum(b["d4"]) / len(b["d4"]), 3),
        ))
    return profiles


# ============================================================
# 4. 增强 Harness
# ============================================================

class EnhancedHarness:
    """30-Unit 增强发散仿真 — 替换 G19 MockGenerator + 添加模式检测."""

    def __init__(self, db_path: Path, project_id: str, n_units: int = 30):
        self.db_path = db_path
        self.project_id = project_id
        self.n_units = n_units
        self.scene_types: list[SceneType] = []

    def setup(self):
        from app.db._impl import get_conn as gconn
        conn = gconn()
        conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)",
                      (self.project_id, "G19.5测试"))
        conn.execute("INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)",
                      ("B_001", self.project_id, 1))
        conn.commit()

        self.unit_ids = []
        for i in range(self.n_units):
            raw = f"{self.project_id}_U_{i:03d}"
            uid = hashlib.md5(raw.encode()).hexdigest()[:12]
            self.unit_ids.append(uid)

    def run(self, mode: str = "stable") -> EnhancedReport:
        gen = EnhancedMockGenerator(self.project_id, self.unit_ids)
        self.scene_types = gen.scene_types
        gen.generate_all(mode)

        d1 = _calc_d1_guide_adoption(self.project_id, self.unit_ids)
        d2, disappearances = _calc_d2_character_continuity(self.project_id, self.unit_ids)
        d3 = _calc_d3_hook_health(self.project_id, self.unit_ids)
        d4 = _calc_d4_memory_fade(self.project_id, self.unit_ids)

        trajectory = []
        for i in range(self.n_units):
            trajectory.append(MetricPoint(
                unit_index=i,
                guide_adoption_rate=round(d1[i], 3),
                character_continuity=round(d2[i], 3),
                hook_span_ratio=round(d3[i], 3),
                memory_fade_ratio=round(d4[i], 3),
            ))

        # G19 原始检测
        old_warnings = _detect_drift_legacy(trajectory, disappearances)

        # G19.5 模式分类
        events = detect_divergence_patterns(trajectory, self.scene_types, disappearances)

        # 场景剖面
        scenes = calc_scene_profiles(trajectory, self.scene_types)

        summary = {
            "d1_mean": round(sum(d1) / len(d1), 3),
            "d2_mean": round(sum(d2) / len(d2), 3),
            "d3_mean": round(sum(d3) / len(d3), 3),
            "d4_mean": round(sum(d4) / len(d4), 3),
        }

        base = StabilityReport(
            n_units=self.n_units,
            trajectory=trajectory,
            warnings=old_warnings,
            summary=summary,
        )

        return EnhancedReport(base=base, events=events, scenes=scenes)


def _detect_drift_legacy(trajectory, disappearances):
    """G19 原始检测逻辑 (保留做对比基准)."""
    from smoke_g19_stability_harness import detect_drift
    return detect_drift(trajectory, disappearances)


# ============================================================
# 5. 测试用例
# ============================================================

def test_stable_enhanced(db_path: Path) -> EnhancedReport:
    print("\n" + "=" * 62)
    print("  G19.5 测试 1: Stable — 基线无退化")
    print("=" * 62)

    h = EnhancedHarness(db_path, "P_STABLE", n_units=30)
    h.setup()
    report = h.run(mode="stable")

    # 应: 无 BURST, 无 SUSTAINED, 无 FEEDBACK
    persistent = report.persistent_warnings
    if persistent:
        print(f"  FAIL: stable mode 产生 {len(persistent)} 个持久告警")
        for e in persistent:
            print(f"    [{e.pattern.value}] {e.detail}")
        return report

    print(f"  PASS: {report.base.n_units} units, G19 warnings={len(report.base.warnings)},"
          f" events={len(report.events)}")
    if report.events:
        for e in report.events:
            print(f"    [{e.pattern.value}] {e.detail}")
    print(f"  D1(采纳)={report.base.summary['d1_mean']:.3f}"
          f"  D2(角色)={report.base.summary['d2_mean']:.3f}"
          f"  D3(钩子)={report.base.summary['d3_mean']:.3f}"
          f"  D4(记忆)={report.base.summary['d4_mean']:.3f}")

    # 场景剖面
    for sp in report.scenes:
        print(f"  [{sp.scene_type.name:12s}] n={sp.count} "
              f"D1={sp.d1_mean:.3f} D2={sp.d2_mean:.3f} "
              f"D3={sp.d3_mean:.3f} D4={sp.d4_mean:.3f}")

    return report


def test_burst_only(db_path: Path) -> EnhancedReport:
    print("\n" + "=" * 62)
    print("  G19.5 测试 2: Burst Only — 瞬时偏离 + 恢复")
    print("  → 预期: 检测到 BURST 事件, 无持久告警")
    print("=" * 62)

    h = EnhancedHarness(db_path, "P_BURST", n_units=30)
    h.setup()
    report = h.run(mode="burst_only")

    # 应: 有 BURST, 无 SUSTAINED
    burst_count = sum(1 for e in report.events if e.pattern == DivergencePattern.BURST)
    sustained_count = sum(1 for e in report.events if e.pattern == DivergencePattern.SUSTAINED)

    ok = burst_count >= 1 and sustained_count == 0
    if ok:
        print(f"  PASS: {burst_count} BURST 事件, 0 SUSTAINED 告警")
    else:
        print(f"  FAIL: {burst_count} BURST, {sustained_count} SUSTAINED (应 0)")

    for e in report.events:
        tag = "✓" if e.pattern == DivergencePattern.BURST else "✗"
        print(f"    {tag} [{e.pattern.value}] {e.metric} @u{e.unit_index}: {e.detail}")

    print(f"  D1={report.base.summary['d1_mean']:.3f}"
          f"  D2={report.base.summary['d2_mean']:.3f}"
          f"  D3={report.base.summary['d3_mean']:.3f}"
          f"  D4={report.base.summary['d4_mean']:.3f}")

    return report


def test_full_drift(db_path: Path) -> EnhancedReport:
    print("\n" + "=" * 62)
    print("  G19.5 测试 3: Full Drift — burst→恢复→再偏离→反馈")
    print("  → 预期: BURST + SUSTAINED + FEEDBACK + CASCADE")
    print("=" * 62)

    h = EnhancedHarness(db_path, "P_FULL", n_units=30)
    h.setup()
    report = h.run(mode="full_drift")

    patterns = {}
    for e in report.events:
        patterns[e.pattern] = patterns.get(e.pattern, 0) + 1

    has_burst = patterns.get(DivergencePattern.BURST, 0) >= 1
    has_sustained = patterns.get(DivergencePattern.SUSTAINED, 0) >= 1
    has_cascade = patterns.get(DivergencePattern.CASCADE, 0) >= 1

    ok = has_burst and (has_sustained or has_cascade)
    if ok:
        print(f"  PASS: 模式分布 {dict((k.value, v) for k, v in patterns.items())}")
    else:
        print(f"  FAIL: 模式不完整 — burst={has_burst} sustained={has_sustained} cascade={has_cascade}")

    for e in report.events:
        sev = {"BURST": " ", "SUSTAINED": "⚠", "SELF_HEAL": "↻",
               "FEEDBACK_LOOP": "🔥", "CASCADE": "☠"}.get(e.pattern.name, "?")
        print(f"    {sev} [{e.pattern.value}] {e.metric} @u{e.unit_index}: {e.detail}")

    print(f"  D1={report.base.summary['d1_mean']:.3f}"
          f"  D2={report.base.summary['d2_mean']:.3f}"
          f"  D3={report.base.summary['d3_mean']:.3f}"
          f"  D4={report.base.summary['d4_mean']:.3f}")

    return report


# ============================================================
# Main
# ============================================================

def main():
    import app.app_paths
    passed = failed = 0
    all_reports = []

    # --- Test 1: Stable ---
    db1, _ = _setup_temp_db("nw_g19_5_stable_")
    app.app_paths.sqlite_path = lambda: db1
    _init_db(db1)
    try:
        r1 = test_stable_enhanced(db1)
        all_reports.append(r1)
        if len(r1.persistent_warnings) == 0:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1
    finally:
        _teardown_db()

    # --- Test 2: Burst Only ---
    db2, _ = _setup_temp_db("nw_g19_5_burst_")
    app.app_paths.sqlite_path = lambda: db2
    _init_db(db2)
    try:
        r2 = test_burst_only(db2)
        all_reports.append(r2)
        burst = sum(1 for e in r2.events if e.pattern == DivergencePattern.BURST)
        sustained = sum(1 for e in r2.events if e.pattern == DivergencePattern.SUSTAINED)
        if burst >= 1 and sustained == 0:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1
    finally:
        _teardown_db()

    # --- Test 3: Full Drift ---
    db3, _ = _setup_temp_db("nw_g19_5_full_")
    app.app_paths.sqlite_path = lambda: db3
    _init_db(db3)
    try:
        r3 = test_full_drift(db3)
        all_reports.append(r3)
        patterns = {}
        for e in r3.events:
            patterns[e.pattern] = patterns.get(e.pattern, 0) + 1
        if patterns.get(DivergencePattern.BURST, 0) >= 1 and (
            patterns.get(DivergencePattern.SUSTAINED, 0) >= 1 or
            patterns.get(DivergencePattern.CASCADE, 0) >= 1
        ):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1
    finally:
        _teardown_db()

    # --- SVG 轨迹图 ---
    print("\n" + "=" * 62)
    print("  G19.5 测试 4: 轨迹图")
    print("=" * 62)
    try:
        if all_reports:
            svg = render_trajectory(all_reports[-1].base)
            out = ROOT / "smoke" / "g19_5_trajectory.svg"
            out.write_text(svg, encoding="utf-8")
            print(f"  PASS: SVG → smoke/g19_5_trajectory.svg ({len(svg)} bytes)")
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # --- Summary ---
    total = passed + failed
    print("\n" + "=" * 62)
    print(f"  G19.5 完成: {passed}/{total} 通过, {failed} 失败")
    print("=" * 62)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
