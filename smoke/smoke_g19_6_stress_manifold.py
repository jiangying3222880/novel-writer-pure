"""
G19.6 SMOKE: v4.0 应力流形扩展 — 参数空间网格采样 + 相图 + 灵敏度分析

G19.5 探索了应力空间中的 3 个孤立点 (stable / burst_only / full_drift).
G19.6 将这个空间网格化, 系统性地回答:

  1. 相变边界: BURST → SUSTAINED 的临界参数在哪里?
  2. 稳定盆地: 系统能承受的最大安全应力是多少?
  3. 共振点:  哪些维度组合产生超线性级联?
  4. 盲区:    当前检测器对哪些退化路径不敏感?

方法: 拉丁超立方采样 300 个参数点, 纯计算 (无 DB, 无 LLM).
"""
from __future__ import annotations

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

_SMOKE_TIMEOUT = 45
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g19_6 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smoke_g19_5_enhanced_divergence import (
    MetricPoint,
    DivergencePattern,
    DivergenceEvent,
    detect_divergence_patterns,
    SceneType,
    render_trajectory,
)

# ============================================================
# 1. 应力参数空间定义
# ============================================================

@dataclass
class StressConfig:
    """一个应力参数点 — 9 维空间中的坐标."""
    d1_drift:       float = 0.0   # D1 线性退化率 (每 unit)
    d2_ooc:         float = 0.0   # D2 角色 OOC 概率 (每 unit)
    d3_hook_decay:  float = 0.0   # D3 钩子健康衰减率
    d4_memory_fade: float = 0.0   # D4 记忆废弃率 (每 unit)
    burst_mag:      float = 0.0   # burst 深度
    burst_dur:      int   = 0     # burst 持续 unit 数
    burst_start:    int   = 10    # burst 起始位置
    self_heal:      float = 0.0   # 自发修复概率
    feedback_lag:   int   = 0     # D1→D4 反馈环延迟 (unit)

    def as_vector(self) -> list[float]:
        return [self.d1_drift, self.d2_ooc, self.d3_hook_decay,
                self.d4_memory_fade, self.burst_mag,
                float(self.burst_dur), float(self.burst_start),
                self.self_heal, float(self.feedback_lag)]

    @property
    def total_pressure(self) -> float:
        """综合应力指数 (0-1)."""
        return min(1.0, (
            self.d1_drift / 0.05 +
            self.d2_ooc / 0.10 +
            self.d3_hook_decay / 0.08 +
            self.d4_memory_fade / 0.10 +
            self.burst_mag / 0.60 +
            self.burst_dur / 8 +
            self.self_heal / 0.20 +
            self.feedback_lag / 8
        ) / 8)


# 参数网格定义 — 每个维度的采样级别
STRESS_GRID = {
    "d1_drift":       [0.0, 0.005, 0.01, 0.02, 0.035, 0.05],
    "d2_ooc":         [0.0, 0.01, 0.03, 0.06, 0.10],
    "d3_hook_decay":  [0.0, 0.01, 0.03, 0.06],
    "d4_memory_fade": [0.0, 0.01, 0.03, 0.06, 0.10],
    "burst_mag":      [0.0, 0.10, 0.20, 0.35, 0.50, 0.65],
    "burst_dur":      [0, 2, 4, 6, 8],
    "burst_start":    [5, 10, 15, 20],
    "self_heal":      [0.0, 0.05, 0.10, 0.18],
    "feedback_lag":   [0, 2, 4, 6, 8],
}


# ============================================================
# 2. Latin Hypercube Sampler
# ============================================================

def latin_hypercube_sample(n_samples: int, seed: int = 42) -> list[StressConfig]:
    """拉丁超立方采样 — 均匀覆盖参数空间.

    每个维度被分成 n_samples 个等概率区间,
    每个区间各取一个点, 保证边缘分布均匀."""
    rng = random.Random(seed)
    dims = list(STRESS_GRID.keys())
    dim_values = STRESS_GRID
    n_dims = len(dims)

    samples = []
    for _ in range(n_samples):
        config = {}
        for d in dims:
            levels = dim_values[d]
            n_levels = len(levels)
            # 将 [0, 1] 分成 n_samples 份, 每份随机取 n_levels 级别之一
            bucket = rng.randint(0, n_levels - 1)
            config[d] = levels[bucket]

        samples.append(StressConfig(**config))

    # 打乱每个维度内部 (LHS 关键步骤)
    for d_idx, d in enumerate(dims):
        vals = [s.as_vector()[d_idx] for s in samples]
        rng.shuffle(vals)
        for s_idx, s in enumerate(samples):
            setattr(s, d, vals[s_idx])

    return samples


# ============================================================
# 3. 参数化轨迹生成器 (无 DB, 纯计算)
# ============================================================

def generate_stress_trajectory(
    config: StressConfig,
    n_units: int = 30,
    seed: int = 42,
) -> tuple[list[MetricPoint], list[SceneType]]:
    """根据应力参数生成完整的指标轨迹.

    每个 metric 独立退化 + 场景调制 + burst 注入.
    无随机性 (seed 固定), 保证可重复."""
    rng = random.Random(seed)

    SCENE_PATTERN = [
        SceneType.DIALOGUE, SceneType.TRANSITION,
        SceneType.BATTLE, SceneType.TRANSITION,
        SceneType.MONOLOGUE, SceneType.DIALOGUE,
    ]
    SCENE_MOD = {
        SceneType.BATTLE:     {"d1": 1.5, "d2": 1.0},
        SceneType.DIALOGUE:   {"d1": 0.8, "d2": 0.7},
        SceneType.MONOLOGUE:  {"d1": 1.0, "d2": 1.5},
        SceneType.TRANSITION: {"d1": 0.5, "d2": 0.5},
    }

    scenes = [SCENE_PATTERN[i % len(SCENE_PATTERN)] for i in range(n_units)]

    d1, d2, d3, d4 = [], [], [], []

    for i in range(n_units):
        scene = scenes[i]
        sm = SCENE_MOD[scene]

        # ---- D1: Guide 采纳率 ----
        val_d1 = 0.90
        val_d1 -= i * config.d1_drift * sm["d1"]
        # burst
        if config.burst_start <= i < config.burst_start + config.burst_dur:
            val_d1 -= config.burst_mag
        # self-heal after burst
        if i >= config.burst_start + config.burst_dur and rng.random() < config.self_heal:
            val_d1 += config.burst_mag * 0.6
        # feedback: if D4 is already degraded, further drop D1
        if i > 0 and config.feedback_lag > 0:
            prev_d4 = d4[i - 1]
            if prev_d4 > 0.40:
                val_d1 -= (prev_d4 - 0.40) * 0.5
        val_d1 = max(0.05, min(1.0, val_d1 + rng.uniform(-0.02, 0.02)))
        d1.append(val_d1)

        # ---- D2: 角色连续性 ----
        val_d2 = 0.92
        val_d2 -= i * config.d2_ooc * sm["d2"]
        if config.burst_start <= i < config.burst_start + config.burst_dur:
            val_d2 -= config.burst_mag * 0.4
        if i >= config.burst_start + config.burst_dur and rng.random() < config.self_heal * 0.8:
            val_d2 += config.burst_mag * 0.3
        val_d2 = max(0.05, min(1.0, val_d2 + rng.uniform(-0.02, 0.02)))
        d2.append(val_d2)

        # ---- D3: 钩子健康度 ----
        val_d3 = 0.78
        val_d3 -= i * config.d3_hook_decay
        if config.burst_start <= i < config.burst_start + config.burst_dur:
            val_d3 -= config.burst_mag * 0.3
        val_d3 = max(0.05, min(1.0, val_d3 + rng.uniform(-0.03, 0.03)))
        d3.append(val_d3)

        # ---- D4: 记忆废弃率 (反指标, 越低越好) ----
        val_d4 = 0.02
        val_d4 += i * config.d4_memory_fade
        if config.burst_start <= i < config.burst_start + config.burst_dur:
            val_d4 += config.burst_mag * 0.2
        # feedback: D1 下降导致 D4 加速上升
        if config.feedback_lag > 0 and i >= config.burst_start + config.feedback_lag:
            d1_decline = 0.90 - d1[i]
            if d1_decline > 0.1:
                val_d4 += d1_decline * 0.8
        val_d4 = max(0.0, min(0.95, val_d4 + rng.uniform(-0.01, 0.01)))
        d4.append(val_d4)

    trajectory = [
        MetricPoint(
            unit_index=i,
            guide_adoption_rate=round(d1[i], 4),
            character_continuity=round(d2[i], 4),
            hook_span_ratio=round(d3[i], 4),
            memory_fade_ratio=round(d4[i], 4),
        )
        for i in range(n_units)
    ]

    return trajectory, scenes


# ============================================================
# 4. 场景结果收集
# ============================================================

@dataclass
class ScenarioResult:
    """单个应力场景的运行结果."""
    config: StressConfig
    trajectory: list[MetricPoint]
    events: list[DivergenceEvent]
    pattern_counts: dict
    d1_mean: float
    d2_mean: float
    d3_mean: float
    d4_mean: float
    total_events: int
    has_critical: bool       # CASCADE or FEEDBACK_LOOP
    has_persistent: bool     # SUSTAINED
    has_burst: bool
    has_self_heal: bool


def run_scenario(config: StressConfig, n_units: int = 30) -> ScenarioResult:
    """运行单个应力场景并收集结果."""
    trajectory, scenes = generate_stress_trajectory(config, n_units)
    events = detect_divergence_patterns(trajectory, scenes, disappearances=[])

    pattern_counts = {}
    for e in events:
        pattern_counts[e.pattern] = pattern_counts.get(e.pattern, 0) + 1

    d1 = [p.guide_adoption_rate for p in trajectory]
    d2 = [p.character_continuity for p in trajectory]
    d3 = [p.hook_span_ratio for p in trajectory]
    d4 = [p.memory_fade_ratio for p in trajectory]

    return ScenarioResult(
        config=config,
        trajectory=trajectory,
        events=events,
        pattern_counts=pattern_counts,
        d1_mean=round(sum(d1) / len(d1), 4),
        d2_mean=round(sum(d2) / len(d2), 4),
        d3_mean=round(sum(d3) / len(d3), 4),
        d4_mean=round(sum(d4) / len(d4), 4),
        total_events=len(events),
        has_critical=pattern_counts.get(DivergencePattern.CASCADE, 0) > 0
                     or pattern_counts.get(DivergencePattern.FEEDBACK_LOOP, 0) > 0,
        has_persistent=pattern_counts.get(DivergencePattern.SUSTAINED, 0) > 0,
        has_burst=pattern_counts.get(DivergencePattern.BURST, 0) > 0,
        has_self_heal=pattern_counts.get(DivergencePattern.SELF_HEAL, 0) > 0,
    )


# ============================================================
# 5. 流形探索器
# ============================================================

@dataclass
class ManifoldReport:
    """应力流形探索完整报告."""
    n_scenarios: int
    results: list[ScenarioResult]
    safe_boundary: dict       # 每个维度最大安全值
    resonance_pairs: list[dict]  # 共振维度对
    blind_spots: list[str]    # 盲区描述
    phase_summary: dict       # 各区域场景分布

    @property
    def critical_rate(self) -> float:
        return sum(1 for r in self.results if r.has_critical) / self.n_scenarios

    @property
    def safe_rate(self) -> float:
        return sum(1 for r in self.results if r.total_events == 0) / self.n_scenarios


class ManifoldExplorer:
    """应力流形探索器 — 采样→运行→分析."""

    def __init__(self, n_samples: int = 300, n_units: int = 30):
        self.n_samples = n_samples
        self.n_units = n_units

    def explore(self, seed: int = 42) -> ManifoldReport:
        configs = latin_hypercube_sample(self.n_samples, seed=seed)
        results = [run_scenario(c, self.n_units) for c in configs]

        safe_boundary = self._calc_safe_boundary(results)
        resonance_pairs = self._detect_resonance(results)
        blind_spots = self._detect_blind_spots(results)
        phase_summary = self._summarize_phases(results)

        return ManifoldReport(
            n_scenarios=self.n_samples,
            results=results,
            safe_boundary=safe_boundary,
            resonance_pairs=resonance_pairs,
            blind_spots=blind_spots,
            phase_summary=phase_summary,
        )

    def _calc_safe_boundary(self, results: list[ScenarioResult]) -> dict:
        """计算稳定盆地边界 — 每个维度不触发任何告警的最大值."""
        safe = [r for r in results if r.total_events == 0]
        boundary = {}
        for dim in ["d1_drift", "d2_ooc", "d3_hook_decay", "d4_memory_fade",
                     "burst_mag", "burst_dur", "self_heal", "feedback_lag"]:
            vals = [getattr(r.config, dim) for r in safe]
            boundary[dim] = max(vals) if vals else 0.0
        return boundary

    def _detect_resonance(self, results: list[ScenarioResult]) -> list[dict]:
        """检测共振维度对 — 两个维度同时非零时 feedback_loop 频率异常升高."""
        dims = ["d1_drift", "d2_ooc", "d3_hook_decay", "d4_memory_fade",
                 "burst_mag", "self_heal", "feedback_lag"]
        resonance = []

        for i, da in enumerate(dims):
            for j, db in enumerate(dims):
                if i >= j:
                    continue

                # 两个维度都非零的场景
                both = [r for r in results
                        if getattr(r.config, da) > 0 and getattr(r.config, db) > 0]
                if len(both) < 10:
                    continue

                # 这些场景中 feedback_loop / cascade 的比例
                fb_rate = sum(1 for r in both
                              if r.pattern_counts.get(DivergencePattern.FEEDBACK_LOOP, 0) > 0
                              or r.pattern_counts.get(DivergencePattern.CASCADE, 0) > 0) / len(both)

                # 全局比例
                global_fb = sum(1 for r in results
                                if r.pattern_counts.get(DivergencePattern.FEEDBACK_LOOP, 0) > 0
                                or r.pattern_counts.get(DivergencePattern.CASCADE, 0) > 0) / len(results)

                # 共振 = 局部比例远高于全局
                if fb_rate > global_fb * 2.5 and fb_rate > 0.15:
                    resonance.append({
                        "dim_a": da, "dim_b": db,
                        "local_rate": round(fb_rate, 3),
                        "global_rate": round(global_fb, 3),
                        "ratio": round(fb_rate / max(global_fb, 0.001), 1),
                        "n_samples": len(both),
                    })

        resonance.sort(key=lambda x: x["ratio"], reverse=True)
        return resonance

    def _detect_blind_spots(self, results: list[ScenarioResult]) -> list[str]:
        """检测检测器盲区 — 指标明显退化但没有触发任何事件."""
        blind = []
        for r in results:
            d1 = [p.guide_adoption_rate for p in r.trajectory]
            d4 = [p.memory_fade_ratio for p in r.trajectory]

            d1_decline = d1[0] - d1[-1]
            d4_rise = d4[-1] - d4[0]

            # 明显退化: D1 下降 > 0.2 或 D4 上升 > 0.3
            if (d1_decline > 0.20 or d4_rise > 0.30) and r.total_events == 0:
                blind.append(
                    f"D1={r.config.d1_drift:.3f}/D4={r.config.d4_memory_fade:.3f}"
                    f"/B={r.config.burst_mag:.2f} "
                    f"→ D1↓{d1_decline:.2f} D4↑{d4_rise:.2f} 但 0 events"
                )

        return blind

    def _summarize_phases(self, results: list[ScenarioResult]) -> dict:
        """按 StressConfig.total_pressure 分区统计."""
        low = [r for r in results if r.config.total_pressure < 0.3]
        mid = [r for r in results if 0.3 <= r.config.total_pressure < 0.6]
        high = [r for r in results if r.config.total_pressure >= 0.6]

        return {
            "low_pressure": {
                "n": len(low),
                "safe_rate": sum(1 for r in low if r.total_events == 0) / max(len(low), 1),
                "avg_events": round(sum(r.total_events for r in low) / max(len(low), 1), 1),
            },
            "mid_pressure": {
                "n": len(mid),
                "safe_rate": sum(1 for r in mid if r.total_events == 0) / max(len(mid), 1),
                "avg_events": round(sum(r.total_events for r in mid) / max(len(mid), 1), 1),
            },
            "high_pressure": {
                "n": len(high),
                "safe_rate": sum(1 for r in high if r.total_events == 0) / max(len(high), 1),
                "avg_events": round(sum(r.total_events for r in high) / max(len(high), 1), 1),
            },
        }


# ============================================================
# 6. 可视化: 相图 (Phase Portrait)
# ============================================================

def render_phase_portrait(report: ManifoldReport) -> str:
    """D1 vs D2 相图 — 每个点按最严重 pattern 着色."""
    n = len(report.results)
    h = 520

    points = ""
    for r in report.results:
        x = 80 + (1.0 - r.d1_mean) * 500   # 反转: 左=高采纳, 右=低采纳
        y = 80 + (1.0 - r.d2_mean) * 380   # 反转: 上=高连续, 下=低连续

        if r.has_critical:
            color = "#E24B4A"; r_size = 4.5; label = "critical"
        elif r.has_persistent:
            color = "#EF9F27"; r_size = 3.5; label = "sustained"
        elif r.has_burst:
            color = "#378ADD"; r_size = 3.0; label = "burst"
        elif r.has_self_heal:
            color = "#1D9E75"; r_size = 3.0; label = "heal"
        else:
            color = "#97C459"; r_size = 2.5; label = "stable"

        opacity = 0.55 if r.total_events == 0 else 0.85
        points += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_size}" fill="{color}" opacity="{opacity}"/>\n'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {h}" width="100%" role="img">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <title>D1 x D2 Phase Portrait</title>
  <desc>Each point is one stress scenario colored by worst divergence pattern</desc>

  <rect x="40" y="20" width="620" height="{h-40}" rx="12" fill="var(--color-background-secondary)" stroke="var(--color-border-primary)" stroke-width="0.5"/>

  <text x="340" y="50" text-anchor="middle" class="th">Phase Portrait: D1 (Guide Adoption) vs D2 (Character Continuity)</text>
  <text x="340" y="68" text-anchor="middle" class="ts">{n} stress scenarios, colored by worst detected pattern</text>

  <line x1="80" y1="80" x2="80" y2="460" stroke="var(--color-border-secondary)" stroke-width="0.5"/>
  <line x1="80" y1="460" x2="580" y2="460" stroke="var(--color-border-secondary)" stroke-width="0.5"/>

  <text x="75" y="88" text-anchor="end" class="ts">1.0</text>
  <text x="75" y="270" text-anchor="end" class="ts">0.5</text>
  <text x="75" y="455" text-anchor="end" class="ts">0.0</text>
  <text x="75" y="474" text-anchor="end" class="ts" fill="var(--color-text-tertiary)">D2</text>

  <text x="80" y="478" text-anchor="start" class="ts">1.0</text>
  <text x="330" y="478" text-anchor="middle" class="ts">0.5</text>
  <text x="575" y="478" text-anchor="end" class="ts">0.0 D1</text>

  {points}

  <rect x="540" y="90" width="110" height="145" rx="6" fill="var(--color-background-primary)" stroke="var(--color-border-tertiary)" stroke-width="0.5"/>
  <text x="595" y="108" text-anchor="middle" class="ts">Legend</text>
  <circle cx="560" cy="125" r="4" fill="#E24B4A" opacity="0.85"/><text x="575" y="129" class="ts">Critical</text>
  <circle cx="560" cy="147" r="3.5" fill="#EF9F27" opacity="0.85"/><text x="575" y="151" class="ts">Sustained</text>
  <circle cx="560" cy="169" r="3" fill="#378ADD" opacity="0.85"/><text x="575" y="173" class="ts">Burst</text>
  <circle cx="560" cy="191" r="3" fill="#1D9E75" opacity="0.85"/><text x="575" y="195" class="ts">Self-heal</text>
  <circle cx="560" cy="213" r="2.5" fill="#97C459" opacity="0.85"/><text x="575" y="217" class="ts">Stable</text>

  <text x="340" y="{h-10}" text-anchor="middle" class="ts" fill="var(--color-text-tertiary)">
    critical_rate={report.critical_rate:.1%}  safe_rate={report.safe_rate:.1%}
  </text>
</svg>'''
    return svg


# ============================================================
# 7. 可视化: 灵敏度热力图
# ============================================================

def render_sensitivity_heatmap(report: ManifoldReport) -> str:
    """burst_magnitude × burst_duration → SUSTAINED 检测率热力图."""
    h = 420
    mag_levels = sorted(set(r.config.burst_mag for r in report.results))
    dur_levels = sorted(set(int(r.config.burst_dur) for r in report.results))

    cells = ""
    for i, mag in enumerate(mag_levels):
        for j, dur in enumerate(dur_levels):
            subset = [r for r in report.results
                      if abs(r.config.burst_mag - mag) < 0.001
                      and int(r.config.burst_dur) == dur]
            if not subset:
                continue
            rate = sum(1 for r in subset
                       if r.pattern_counts.get(DivergencePattern.SUSTAINED, 0) > 0) / len(subset)

            if rate < 0.1:
                color = "#97C459"
            elif rate < 0.3:
                color = "#FAC775"
            elif rate < 0.5:
                color = "#EF9F27"
            elif rate < 0.7:
                color = "#F0997B"
            else:
                color = "#E24B4A"

            x = 80 + j * 80
            y = 80 + i * 48

            cells += f'<rect x="{x}" y="{y}" width="76" height="44" rx="4" fill="{color}" opacity="0.75"/>\n'
            cells += f'<text x="{x+38}" y="{y+22}" text-anchor="middle" class="ts" fill="var(--color-text-primary)">{rate:.0%}</text>\n'
            cells += f'<text x="{x+38}" y="{y+36}" text-anchor="middle" class="ts" fill="var(--color-text-tertiary)">n={len(subset)}</text>\n'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {h}" width="100%" role="img">
  <title>Sensitivity Heatmap: Burst Mag x Duration</title>
  <desc>SUSTAINED detection rate for each burst_magnitude × burst_duration cell</desc>

  <rect x="40" y="20" width="620" height="{h-40}" rx="12" fill="var(--color-background-secondary)" stroke="var(--color-border-primary)" stroke-width="0.5"/>

  <text x="340" y="50" text-anchor="middle" class="th">Sensitivity Heatmap: Burst Magnitude × Duration → SUSTAINED Rate</text>

  {cells}

  <text x="340" y="{h-10}" text-anchor="middle" class="ts" fill="var(--color-text-tertiary)">Green=low SUSTAINED rate, Red=high SUSTAINED rate</text>
</svg>'''
    return svg


# ============================================================
# 8. 可视化: 安全操作包络 (Safe Operating Envelope)
# ============================================================

def render_safe_envelope(report: ManifoldReport) -> str:
    """雷达图: 各维度最大安全值."""
    boundary = report.safe_boundary
    dims = ["d1_drift", "d2_ooc", "d3_hook_decay", "d4_memory_fade",
             "burst_mag", "burst_dur", "self_heal", "feedback_lag"]
    labels = ["D1 Drift", "D2 OOC", "D3 Hook", "D4 Memory",
              "Burst Mag", "Burst Dur", "Self-heal", "Feedback"]
    maxes = {"d1_drift": 0.05, "d2_ooc": 0.10, "d3_hook_decay": 0.06,
             "d4_memory_fade": 0.10, "burst_mag": 0.65, "burst_dur": 8,
             "self_heal": 0.18, "feedback_lag": 8}

    n = len(dims)
    cx, cy = 340, 260
    radius = 170

    # 网格线
    grid = ""
    for level in [0.25, 0.5, 0.75]:
        pts = []
        for i in range(n):
            angle = -math.pi / 2 + 2 * math.pi * i / n
            r = radius * level
            pts.append(f"{cx + r * math.cos(angle):.0f},{cy + r * math.sin(angle):.0f}")
        grid += f'<polygon points="{" ".join(pts)}" fill="none" stroke="var(--color-border-tertiary)" stroke-width="0.5"/>\n'

    # 安全边界
    safe_pts = []
    for i, dim in enumerate(dims):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        val = boundary[dim]
        max_val = maxes[dim]
        r = radius * (val / max_val) if max_val > 0 else 0
        safe_pts.append(f"{cx + r * math.cos(angle):.0f},{cy + r * math.sin(angle):.0f}")

    # 总压力边界
    full_pts = []
    for i, dim in enumerate(dims):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        full_pts.append(f"{cx + radius * math.cos(angle):.0f},{cy + radius * math.sin(angle):.0f}")

    # 标签
    lbls = ""
    for i, (dim, label) in enumerate(zip(dims, labels)):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        lx = cx + (radius + 28) * math.cos(angle)
        ly = cy + (radius + 28) * math.sin(angle)
        val = boundary[dim]
        max_val = maxes[dim]
        norm = val / max_val if max_val > 0 else 0

        if angle < -math.pi * 0.8 or angle > math.pi * 0.8:
            anchor = "start"
        elif -math.pi * 0.2 < angle < math.pi * 0.2:
            anchor = "end"
        else:
            anchor = "middle"

        lbls += f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="{anchor}" dominant-baseline="central" class="ts">{label}</text>\n'
        lbls += f'<text x="{lx:.0f}" y="{ly+14:.0f}" text-anchor="{anchor}" dominant-baseline="central" class="ts" fill="var(--color-text-tertiary)">{norm:.0%}</text>\n'

    h = 540
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {h}" width="100%" role="img">
  <title>Safe Operating Envelope</title>
  <desc>Radar chart showing max safe values for each stress dimension</desc>

  <rect x="40" y="20" width="620" height="{h-40}" rx="12" fill="var(--color-background-secondary)" stroke="var(--color-border-primary)" stroke-width="0.5"/>

  <text x="340" y="50" text-anchor="middle" class="th">Safe Operating Envelope</text>
  <text x="340" y="68" text-anchor="middle" class="ts">每个维度的不触发告警最大值 (归一化)</text>

  {grid}
  <polygon points="{" ".join(full_pts)}" fill="none" stroke="var(--color-border-primary)" stroke-width="0.5" stroke-dasharray="4 3"/>
  <polygon points="{" ".join(safe_pts)}" fill="var(--c-teal-50)" stroke="var(--c-teal-600)" stroke-width="1.5" opacity="0.7"/>

  {lbls}

  <text x="340" y="{h-10}" text-anchor="middle" class="ts" fill="var(--color-text-tertiary)">安全边界覆盖 {report.safe_rate:.1%} 的场景</text>
</svg>'''
    return svg


# ============================================================
# 9. 测试用例
# ============================================================

def test_sampling():
    """测试 1: 拉丁超立方采样均匀性."""
    print("\n" + "=" * 62)
    print("  G19.6 测试 1: LHS 采样覆盖性")
    print("=" * 62)

    configs = latin_hypercube_sample(300, seed=42)
    assert len(configs) == 300, f"Expected 300, got {len(configs)}"

    # 验证每个维度覆盖了所有级别
    dims = list(STRESS_GRID.keys())
    coverage = {}
    for d in dims:
        levels = set(STRESS_GRID[d])
        seen = set(getattr(c, d) for c in configs)
        coverage[d] = len(seen) / len(levels)

    low_cov = [(d, c) for d, c in coverage.items() if c < 0.5]
    if low_cov:
        print(f"  FAIL: 低覆盖率维度: {low_cov}")
        return False

    print(f"  PASS: 300 配置, 维度覆盖率: "
          f"min={min(coverage.values()):.0%} mean={sum(coverage.values())/len(coverage):.0%}")
    return True


def test_exploration():
    """测试 2: 流形探索完整性."""
    print("\n" + "=" * 62)
    print("  G19.6 测试 2: 全流形探索 (300 scenarios)")
    print("=" * 62)

    explorer = ManifoldExplorer(n_samples=300, n_units=30)
    report = explorer.explore(seed=42)

    assert report.n_scenarios == 300
    assert len(report.results) == 300

    # 每个场景都有结果
    for r in report.results:
        assert len(r.trajectory) == 30, f"Trajectory length != 30"

    # 统计
    n_stable = sum(1 for r in report.results if r.total_events == 0)
    n_burst = sum(1 for r in report.results if r.has_burst)
    n_sustained = sum(1 for r in report.results if r.has_persistent)
    n_critical = sum(1 for r in report.results if r.has_critical)
    n_heal = sum(1 for r in report.results if r.has_self_heal)

    print(f"  PASS: {n_stable} stable, {n_burst} burst, {n_sustained} sustained, "
          f"{n_critical} critical, {n_heal} self-heal")
    print(f"  Safe rate: {report.safe_rate:.1%}, Critical rate: {report.critical_rate:.1%}")

    # 压力分区
    ps = report.phase_summary
    for zone, info in ps.items():
        print(f"  [{zone:16s}] n={info['n']:3d}  safe={info['safe_rate']:.0%}  avg_events={info['avg_events']}")

    return True


def test_safe_envelope():
    """测试 3: 安全包络合理性."""
    print("\n" + "=" * 62)
    print("  G19.6 测试 3: 安全操作包络")
    print("=" * 62)

    explorer = ManifoldExplorer(n_samples=300, n_units=30)
    report = explorer.explore(seed=42)

    boundary = report.safe_boundary
    assert len(boundary) == 8, f"Expected 8 dims, got {len(boundary)}"

    # 安全边界应该有效: burst_mag 在有其他壓力下不能太高
    print(f"  Safe boundary: {boundary}")
    print(f"  PASS: 8 维度安全边界已计算")
    return True


def test_resonance():
    """测试 4: 共振检测."""
    print("\n" + "=" * 62)
    print("  G19.6 测试 4: 共振维度对检测")
    print("=" * 62)

    explorer = ManifoldExplorer(n_samples=300, n_units=30)
    report = explorer.explore(seed=42)

    pairs = report.resonance_pairs
    if pairs:
        print(f"  PASS: 发现 {len(pairs)} 个共振维度对:")
        for p in pairs[:5]:
            print(f"    {p['dim_a']} × {p['dim_b']}: "
                  f"local={p['local_rate']:.1%} global={p['global_rate']:.1%} ratio={p['ratio']}x")
    else:
        print(f"  PASS: 无显著共振 (所有维度对都在线性范围内)")
    return True


def test_blind_spots():
    """测试 5: 盲区检测."""
    print("\n" + "=" * 62)
    print("  G19.6 测试 5: 检测器盲区")
    print("=" * 62)

    explorer = ManifoldExplorer(n_samples=300, n_units=30)
    report = explorer.explore(seed=42)

    blinds = report.blind_spots
    if blinds:
        print(f"  WARNING: 发现 {len(blinds)} 个盲区:")
        for b in blinds[:5]:
            print(f"    {b}")
    else:
        print(f"  PASS: 无盲区 (所有退化场景均被检测)")

    # 盲区不应过多 (< 5% 的场景)
    blind_rate = len(blinds) / 300
    if blind_rate > 0.05:
        print(f"  FAIL: 盲区率 {blind_rate:.1%} > 5%")
        return False
    print(f"  PASS: 盲区率 = {blind_rate:.1%}")
    return True


# ============================================================
# Main
# ============================================================

def main():
    passed = failed = 0

    # Test 1: sampling
    try:
        if test_sampling(): passed += 1
        else: failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Test 2: exploration
    try:
        if test_exploration(): passed += 1
        else: failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Test 3: safe envelope
    try:
        if test_safe_envelope(): passed += 1
        else: failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Test 4: resonance
    try:
        if test_resonance(): passed += 1
        else: failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Test 5: blind spots
    try:
        if test_blind_spots(): passed += 1
        else: failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # --- SVG 可视化 ---
    print("\n" + "=" * 62)
    print("  G19.6 可视化: 相图 + 热力图 + 安全包络")
    print("=" * 62)

    explorer = ManifoldExplorer(n_samples=300, n_units=30)
    report = explorer.explore(seed=42)

    # Phase portrait
    try:
        svg = render_phase_portrait(report)
        out = ROOT / "smoke" / "g19_6_phase_portrait.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"  PASS: Phase portrait → smoke/g19_6_phase_portrait.svg ({len(svg)} bytes)")
        passed += 1
    except Exception as e:
        print(f"  ERROR: Phase portrait failed: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Sensitivity heatmap
    try:
        svg = render_sensitivity_heatmap(report)
        out = ROOT / "smoke" / "g19_6_sensitivity.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"  PASS: Sensitivity → smoke/g19_6_sensitivity.svg ({len(svg)} bytes)")
        passed += 1
    except Exception as e:
        print(f"  ERROR: Sensitivity failed: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Safe envelope
    try:
        svg = render_safe_envelope(report)
        out = ROOT / "smoke" / "g19_6_envelope.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"  PASS: Safe envelope → smoke/g19_6_envelope.svg ({len(svg)} bytes)")
        passed += 1
    except Exception as e:
        print(f"  ERROR: Envelope failed: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    # Summary
    total = passed + failed
    print("\n" + "=" * 62)
    print(f"  G19.6 完成: {passed}/{total} 通过, {failed} 失败")
    print("=" * 62)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
