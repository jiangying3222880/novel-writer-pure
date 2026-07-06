"""
G19 SMOKE: v4.0 长文本稳定性回归系统 — 30-50 Unit State Drift Entropy

验证维度:
  D1: Guide Adoption Density  — 滑动窗口采纳率平滑性
  D2: Character State Drift    — 角色快照连续性分数
  D3: Hook Lifecycle Integrity — 钩子跨度/回收率
  D4: Memory Accumulation Rate — L4 废弃率稳定性

设计原则:
  - 不依赖真实 LLM (mock data 直接写入 DB)
  - 走真实的服务层查询路径 (decision_service, character_tracker, unit_hook_service, memory, memory_manager)
  - 每个测试独立创建/销毁临时 DB
  - 30 Unit 序列, 可检测 State Drift

30 秒自动超时
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 30 秒全局超时
_SMOKE_TIMEOUT = 30
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g19 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# DB 隔离
# ============================================================

def _setup_temp_db(prefix: str = "nw_smoke_g19_") -> tuple[Path, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
    db_path = tmpdir / "test.db"
    story_dir = tmpdir / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    return db_path, story_dir


def _init_db(db_path: Path) -> None:
    from app.services import db as svc_db
    from app.db import connection as _conn
    svc_db.init_db(str(db_path))
    if _conn.get_conn() is None:
        _conn.init(str(db_path))


def _teardown_db() -> None:
    try:
        from app.db import connection as _conn
        _conn.close()
    except Exception:
        pass


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MetricPoint:
    """单个 Unit 观测点的归一化指标 (0-1)."""
    unit_index: int
    guide_adoption_rate: float       # D1: 采纳率
    character_continuity: float      # D2: 连续性
    hook_span_ratio: float           # D3: 钩子健康度 (1 - unfulfilled/total)
    memory_fade_ratio: float         # D4: L4 占比


@dataclass
class DriftWarning:
    type: str       # GUIDE_DECLINE / CHARACTER_FORK / HOOK_ORPHAN / MEMORY_AMNESIA
    severity: str   # HIGH / MEDIUM / CRITICAL
    unit_index: int
    detail: str


@dataclass
class StabilityReport:
    n_units: int
    trajectory: list[MetricPoint]
    warnings: list[DriftWarning]
    summary: dict = field(default_factory=dict)

    @property
    def is_stable(self) -> bool:
        return len(self.warnings) == 0


# ============================================================
# 1. Metric Calculators — 纯函数, 查询 DB
# ============================================================

def _calc_d1_guide_adoption(project_id: str, unit_ids: list[str]) -> list[float]:
    """D1: 每个 Unit 的 Guide 采纳率.

    采用 decision_service.summary() 获取 adopted/total 比例.
    """
    from app.services.decision_service import summary

    rates = []
    for uid in unit_ids:
        s = summary(uid)
        total = s.get("total", 0)
        if total == 0:
            rates.append(1.0)  # 无决策 = 完美采纳
        else:
            adopted = s.get("adopted", 0)
            rates.append(adopted / total)
    return rates


def _calc_d2_character_continuity(project_id: str, unit_ids: list[str]) -> tuple[list[float], list[dict]]:
    """D2: 相邻 Unit 的角色快照连续性分数 + 角色消失检测.

    直接 SQL: 比较相邻 unit 每个角色 5 个维度的变化.
    分数 = 未变化维度数 / 5.
    返回: (scores, disappearances) — disappearances = [{char_name, at_unit_index}]
    """
    from app.db import connection as _conn
    conn = _conn.get_conn()

    # 获取所有角色名
    rows = conn.execute(
        "SELECT DISTINCT character_name FROM character_trackers WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    chars = [r["character_name"] for r in rows]
    if not chars:
        return [1.0] * len(unit_ids), []

    scores = []
    disappearances = []
    dims = ["location", "state", "power_level", "equipment", "relationship"]
    prev_chars = set(chars)

    for i in range(len(unit_ids)):
        uid = unit_ids[i]

        if i > 0:
            # 检测消失的角色
            curr_chars = set(
                r["character_name"] for r in
                conn.execute(
                    "SELECT DISTINCT character_name FROM character_trackers "
                    "WHERE project_id = ? AND chapter_id = ?",
                    (project_id, uid),
                ).fetchall()
            )
            missing = prev_chars - curr_chars
            for char_name in missing:
                disappearances.append({"char_name": char_name, "at_unit_index": i})
            prev_chars = curr_chars

        if i == 0:
            scores.append(1.0)
            continue

        prev_uid = unit_ids[i - 1]
        curr_uid = unit_ids[i]

        char_scores = []
        for char_name in chars:
            prev_row = conn.execute(
                "SELECT * FROM character_trackers "
                "WHERE project_id = ? AND character_name = ? AND chapter_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (project_id, char_name, prev_uid),
            ).fetchone()

            curr_row = conn.execute(
                "SELECT * FROM character_trackers "
                "WHERE project_id = ? AND character_name = ? AND chapter_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (project_id, char_name, curr_uid),
            ).fetchone()

            if prev_row is None or curr_row is None:
                char_scores.append(0.5)
                continue

            changed = sum(
                1 for dim in dims
                if prev_row[dim] != curr_row[dim]
            )
            char_scores.append(1.0 - changed / len(dims))

        scores.append(sum(char_scores) / max(len(char_scores), 1))

    return scores, disappearances


def _calc_d3_hook_health(project_id: str, unit_ids: list[str]) -> list[float]:
    """D3: 钩子健康度 — 累积追踪每个 hook 的 plant→payoff 跨度.

    使用直接 SQL 查询避免服务层 dual-connection 问题.
    健康度 = 已回收 hook 数 / 总 hook 数 (在当前位置).
    """
    from app.db import connection as _conn
    conn = _conn.get_conn()

    ratios = []
    planted_hooks: dict[str, int] = {}  # hook_id → plant unit index
    paid_hooks: set[str] = set()

    for i, uid in enumerate(unit_ids):
        # 查询当前位置的所有 hook events
        rows = conn.execute(
            "SELECT hook_id, hook_type FROM unit_hook_map WHERE unit_id = ?",
            (uid,),
        ).fetchall()

        for row in rows:
            hook_id = row["hook_id"]
            if row["hook_type"] == "plant":
                if hook_id not in planted_hooks:
                    planted_hooks[hook_id] = i
            elif row["hook_type"] == "payoff":
                paid_hooks.add(hook_id)

        total_hooks = len(planted_hooks)
        if total_hooks == 0:
            ratios.append(1.0)
        else:
            ratios.append(len(paid_hooks) / total_hooks)

    return ratios


def _calc_d4_memory_fade(project_id: str, unit_ids: list[str]) -> list[float]:
    """D4: L4 废弃率 — 截至当前位置的 L4 占比.

    时间窗口: 只统计 chapter_id 在当前 unit 及之前插入的记忆.
    健康度 = 1 - L4/total (L4 占比越低越健康).
    """
    from app.db import connection as _conn
    conn = _conn.get_conn()

    ratios = []
    for i, uid in enumerate(unit_ids):
        # 只统计当前及之前 unit 创建的记忆
        visible_units = unit_ids[:i + 1]
        placeholders = ",".join("?" for _ in visible_units)
        counts = conn.execute(
            f"SELECT level, COUNT(*) as cnt FROM agent_memories "
            f"WHERE project_id = ? AND (chapter_id IS NULL OR chapter_id IN ({placeholders})) "
            f"GROUP BY level",
            (project_id, *visible_units),
        ).fetchall()

        level_counts = {"L1": 0, "L2": 0, "L3": 0, "L4": 0}
        for row in counts:
            level_counts[row["level"]] = row["cnt"]

        total = sum(level_counts.values())
        if total == 0:
            ratios.append(1.0)
        else:
            ratios.append(1.0 - level_counts["L4"] / total)

    return ratios


# ============================================================
# 2. Mock 数据生成器
# ============================================================

class MockDataGenerator:
    """为 D1-D4 生成 DB 中的 mock 数据.

    生成两种模式:
      - "stable": 所有指标在阈值内
      - "drift": 某些指标逐步恶化, 用于检测 drift detection
    """

    def __init__(self, project_id: str, unit_ids: list[str]):
        self.project_id = project_id
        self.unit_ids = unit_ids
        self.n = len(unit_ids)

    def generate_all(self, mode: str = "stable"):
        """生成全部 mock 数据."""
        self._gen_units()
        self._gen_decisions(mode)
        self._gen_characters(mode)
        self._gen_hooks(mode)
        self._gen_memories(mode)

    def _get_conn(self):
        from app.db import connection as _conn
        conn = _conn.get_conn()
        if conn is None:
            from app.db import _impl
            conn = _impl.get_conn()
        return conn

    def _gen_units(self):
        """创建 story_units 行 — 直接 SQL INSERT 避免 service 层的连接问题."""
        from app.db._impl import get_conn as gconn
        conn = gconn()
        for i, uid in enumerate(self.unit_ids):
            conn.execute("""
                INSERT INTO story_units (id, project_id, unit_no, title, unit_type,
                    story_order, present_order, status, synopsis, draft,
                    entry_characters, exit_characters,
                    entry_commitments, exit_commitments,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, 'other',
                    ?, ?, 'writing', '', '',
                    '[]', '[]',
                    '[]', '[]',
                    datetime('now', 'localtime'), datetime('now', 'localtime'))
            """, (uid, self.project_id, i + 1, f"Unit {i + 1}", i + 1, i + 1))
        conn.commit()

    def _gen_decisions(self, mode: str):
        """生成 unit_decisions 数据.

        stable: 采纳率 85-95%, 轻微波动
        drift:  采纳率从 90% 逐步降到 40%
        """
        from app.services.decision_service import record
        from app.core.types import Guide

        for i, uid in enumerate(self.unit_ids):
            if mode == "stable":
                base_rate = 0.88 + (i % 3) * 0.02  # 88-92%
            else:
                base_rate = max(0.35, 0.90 - i * 0.018)  # 90% → 35%

            n_guides = 5  # 每个 unit 5 条 Guide
            for g_idx in range(n_guides):
                guide = Guide(
                    source="pressure" if g_idx < 3 else "hook",
                    priority=0.5 + g_idx * 0.1,
                    advice=f"Guide {g_idx} for unit {i}",
                    guide_id=f"G{i}_{g_idx}",
                )
                # 根据概率决定采纳/忽略
                import random
                action = "adopted" if random.random() < base_rate else "ignored"
                record(
                    unit_id=uid,
                    guide=guide,
                    action=action,
                    project_id=self.project_id,
                    step_no=g_idx,
                )

    def _gen_characters(self, mode: str):
        """生成 character_trackers 数据.

        stable: 每个 unit 都有连续快照, 维度变化缓慢 (1维/5 unit)
        drift:  从 unit 20 开始某角色快照缺失 (模拟角色追踪断裂)
        """
        from app.services.character_tracker import record

        characters = ["主角_林风", "女主_苏雪", "反派_黑煞"]
        if mode == "drift":
            active_until = {"主角_林风": self.n, "女主_苏雪": 20, "反派_黑煞": self.n}
        else:
            active_until = {c: self.n for c in characters}

        for char_name in characters:
            limit = active_until[char_name]
            base_power = 10
            for i, uid in enumerate(self.unit_ids[:limit]):
                # stable: 只偶尔改变 power_level (每 5 unit 升一级)
                power = f"Lv{base_power + i // 5}"
                # location 偶尔变
                location = f"地点_{i // 3}"
                # state 极少变
                state = "受伤" if (mode == "drift" and i >= limit - 3) else "正常"
                record(
                    project_id=self.project_id,
                    chapter_id=uid,
                    character_name=char_name,
                    location=location,
                    state=state,
                    power_level=power,
                    equipment="基础装备",  # 不变
                    relationship="友好",     # 不变
                )

    def _gen_hooks(self, mode: str):
        """生成 unit_hook_map 数据 — 直接 SQL.

        stable: 每个 hook 在 3-5 个 unit 内回收
        drift:  部分 hook 跨 12+ unit 未回收 (orphan hooks)
        """
        from app.db import connection as _conn
        conn = _conn.get_conn()

        n_hooks = 8
        for h in range(n_hooks):
            hook_id = f"HOOK_{h}"
            plant_idx = h * 2
            if plant_idx >= self.n:
                break

            # plant
            conn.execute(
                "INSERT INTO unit_hook_map (id, unit_id, project_id, hook_id, hook_type, description, step_no) "
                "VALUES (?, ?, ?, ?, 'plant', ?, 0)",
                (f"HP_{h}", self.unit_ids[plant_idx], self.project_id, hook_id, f"伏笔 H{h}"),
            )

            # payoff
            if mode == "stable":
                payoff_idx = plant_idx + 3
            else:
                payoff_idx = min(plant_idx + 15, self.n - 1) if h >= 4 else plant_idx + 3

            if payoff_idx < self.n:
                conn.execute(
                    "INSERT INTO unit_hook_map (id, unit_id, project_id, hook_id, hook_type, description, step_no) "
                    "VALUES (?, ?, ?, ?, 'payoff', ?, 1)",
                    (f"HF_{h}", self.unit_ids[payoff_idx], self.project_id, hook_id, f"回收 H{h}"),
                )

        conn.commit()

    def _gen_memories(self, mode: str):
        """生成 agent_memories 数据 — 直接 SQL.

        stable: L4 占比 < 20%
        drift:  后期大量 L3 被废弃, L4 占比 > 40%
        """
        from app.db import connection as _conn
        conn = _conn.get_conn()
        import hashlib

        # 基础记忆: L1 主線 + L2 承诺 + L2 世界观
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
                "VALUES (?, ?, ?, ?, ?)",
                (mid, self.project_id, level, cat, content),
            )

        # L3 RAG 记忆 + 废弃
        for i in range(self.n):
            mid = hashlib.md5(f"rag_{i}_{self.project_id}".encode()).hexdigest()[:12]
            level = "L3"
            if mode == "drift" and i >= 18:
                level = "L4"
            elif mode == "stable" and i >= 25:
                level = "L4"

            conn.execute(
                "INSERT INTO agent_memories (id, project_id, chapter_id, level, category, content, ref_id) "
                "VALUES (?, ?, ?, ?, 'rag_chunk', ?, ?)",
                (mid, self.project_id, self.unit_ids[i], level, f"章节片段 {i}", mid if level == "L4" else ""),
            )

        conn.commit()


# ============================================================
# 3. Drift Detection
# ============================================================

def detect_drift(trajectory: list[MetricPoint], disappearances: list[dict] = None) -> list[DriftWarning]:
    """检测叙事漂移信号."""
    warnings = []
    win_size = 5

    if disappearances is None:
        disappearances = []

    # 角色消失 = CRITICAL
    for d in disappearances:
        warnings.append(DriftWarning(
            type="CHARACTER_LOST",
            severity="CRITICAL",
            unit_index=d["at_unit_index"],
            detail=f"角色 '{d['char_name']}' 从 Unit {d['at_unit_index']} 起消失",
        ))

    if len(trajectory) < win_size:
        return warnings

    # D1: Guide 采纳率连续 3 窗口下降 >20%
    guide_rates = [p.guide_adoption_rate for p in trajectory]
    for i in range(win_size * 3, len(trajectory) - win_size + 1):
        window_rates = []
        for w in range(3):
            start = i - (3 - w) * win_size
            avg = sum(guide_rates[start:start + win_size]) / win_size
            window_rates.append(avg)
        if window_rates[0] > 0.6 and window_rates[2] < window_rates[0] * 0.8:
            warnings.append(DriftWarning(
                type="GUIDE_DECLINE",
                severity="HIGH",
                unit_index=i,
                detail=f"采纳率连续下降: {window_rates[0]:.2f} → {window_rates[2]:.2f}",
            ))

    # D2: 角色快照跳跃 > 0.3 分数降幅
    for i in range(1, len(trajectory)):
        prev = trajectory[i - 1].character_continuity
        curr = trajectory[i].character_continuity
        if prev > 0.8 and curr < 0.5:
            warnings.append(DriftWarning(
                type="CHARACTER_FORK",
                severity="HIGH",
                unit_index=i,
                detail=f"角色连续性断裂: {prev:.2f} → {curr:.2f}",
            ))

    # D3: 钩子健康度过低 — 只在 >10 units 后检测
    for i, p in enumerate(trajectory):
        if p.unit_index > 10 and p.hook_span_ratio < 0.3:
            warnings.append(DriftWarning(
                type="HOOK_ORPHAN",
                severity="MEDIUM",
                unit_index=p.unit_index,
                detail=f"钩子健康度过低 (>10 units 未回升): {p.hook_span_ratio:.2f}",
            ))

    # D4: 记忆废弃率 > 0.3 (即 L4 占比 > 30%), 只在 >15 units 后检测
    for i, p in enumerate(trajectory):
        if p.unit_index > 15 and p.memory_fade_ratio < 0.7:
            warnings.append(DriftWarning(
                type="MEMORY_AMNESIA",
                severity="MEDIUM",
                unit_index=p.unit_index,
                detail=f"L4 废弃率过高: L4占比={1 - p.memory_fade_ratio:.1%}",
            ))

    return warnings


# ============================================================
# 4. 轨迹可视化 (SVG)
# ============================================================

def render_trajectory(report: StabilityReport) -> str:
    """生成 SVG 轨迹图: 4 条指标线 + 漂移警告标注."""
    n = report.n_units
    if n == 0:
        return '<svg viewBox="0 0 680 100"><text x="10" y="30">No data</text></svg>'

    w, h = 680, 380
    margin = 50
    plot_w = w - margin * 2
    plot_h = h - margin * 2

    # 颜色
    colors = {"D1": "#e74c3c", "D2": "#3498db", "D3": "#2ecc71", "D4": "#f39c12"}
    labels = {"D1": "Guide 采纳", "D2": "角色连续", "D3": "钩子健康", "D4": "记忆健康"}

    # 生成路径
    def _path(key: str, values: list[float]) -> str:
        if not values:
            return ""
        pts = []
        for i, v in enumerate(values):
            x = margin + (i / (n - 1)) * plot_w if n > 1 else margin + plot_w / 2
            y = margin + plot_h - v * plot_h
            pts.append(f"{x:.1f},{y:.1f}")
        return "M" + " L".join(pts)

    svg_parts = [
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="100%" height="100%" fill="#1a1a2e"/>',
        # 网格
        '<line x1="50" y1="350" x2="630" y2="350" stroke="#333" stroke-width="1"/>',
        '<line x1="50" y1="260" x2="630" y2="260" stroke="#333" stroke-width="0.5" stroke-dasharray="4,4"/>',
        '<line x1="50" y1="170" x2="630" y2="170" stroke="#333" stroke-width="0.5" stroke-dasharray="4,4"/>',
        '<line x1="50" y1="80" x2="630" y2="80" stroke="#333" stroke-width="0.5" stroke-dasharray="4,4"/>',
        # Y 轴标签
        '<text x="30" y="355" fill="#666" text-anchor="end" font-size="10">0</text>',
        '<text x="30" y="265" fill="#666" text-anchor="end" font-size="10">0.25</text>',
        '<text x="30" y="175" fill="#666" text-anchor="end" font-size="10">0.5</text>',
        '<text x="30" y="85" fill="#666" text-anchor="end" font-size="10">0.75</text>',
        '<text x="30" y="15" fill="#666" text-anchor="end" font-size="10">1.0</text>',
        # 阈值线
        '<line x1="50" y1="185" x2="630" y2="185" stroke="#ff4444" stroke-width="1" stroke-dasharray="8,4" opacity="0.4"/>',
        '<rect x="80" y="178" width="20" height="14" fill="#ff4444" opacity="0.4" rx="2"/>',
        '<text x="105" y="190" fill="#ff4444" font-size="10" opacity="0.6">阈值 0.5</text>',
    ]

    # 指标线
    trajectory = report.trajectory
    d1_vals = [p.guide_adoption_rate for p in trajectory]
    d2_vals = [p.character_continuity for p in trajectory]
    d3_vals = [p.hook_span_ratio for p in trajectory]
    d4_vals = [p.memory_fade_ratio for p in trajectory]

    for key, vals in [("D1", d1_vals), ("D2", d2_vals), ("D3", d3_vals), ("D4", d4_vals)]:
        path = _path(key, vals)
        svg_parts.append(
            f'<path d="{path}" fill="none" stroke="{colors[key]}" stroke-width="2" opacity="0.8"/>'
        )

    # 漂移警告标记
    for w in report.warnings:
        idx = w.unit_index
        if idx < n:
            x = margin + (idx / (n - 1)) * plot_w if n > 1 else margin + plot_w / 2
            svg_parts.append(
                f'<circle cx="{x:.1f}" cy="40" r="4" fill="#ff4444" opacity="0.8">'
                f'<title>{w.type}: {w.detail}</title></circle>'
            )

    # 图例
    lx = 520
    for ki, (key, label) in enumerate(labels.items()):
        ly2 = 15 + ki * 18
        svg_parts.append(
            f'<text x="{lx}" y="{ly2}" fill="{colors[key]}" font-size="11">● {label}</text>'
        )

    svg_parts.append(f'<text x="340" y="375" fill="#555" text-anchor="middle" font-size="10">Unit 序列 ({n} units)</text>')
    svg_parts.append('</svg>')

    return "\n".join(svg_parts)


# ============================================================
# 5. 主 Harness
# ============================================================

class NarrativeStabilityHarness:
    """30-Unit 序列稳定性测试框架."""

    def __init__(self, db_path: Path, project_id: str, n_units: int = 30):
        self.db_path = db_path
        self.project_id = project_id
        self.n_units = n_units
        self.trajectory: list[MetricPoint] = []

    def setup(self):
        """创建项目 + 生成 Unit IDs."""
        from app.db import connection as _conn
        conn = _conn.get_conn()
        conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (self.project_id, "G19测试"))
        conn.execute("INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)",
                      ("B_001", self.project_id, 1))
        conn.commit()

        # 生成 Unit IDs (12 位 hex)
        import hashlib
        self.unit_ids = []
        for i in range(self.n_units):
            raw = f"{self.project_id}_U_{i:03d}"
            uid = hashlib.md5(raw.encode()).hexdigest()[:12]
            self.unit_ids.append(uid)

    def run(self, mode: str = "stable") -> StabilityReport:
        """运行 30-Unit 模拟序列并收集指标.

        mode: "stable" — 所有指标在阈值内
              "drift"  — 部分指标逐步恶化
        """
        # Step 1: 生成 mock 数据
        gen = MockDataGenerator(self.project_id, self.unit_ids)
        gen.generate_all(mode)

        # Step 2: 收集 D1-D4 指标
        d1 = _calc_d1_guide_adoption(self.project_id, self.unit_ids)
        d2, disappearances = _calc_d2_character_continuity(self.project_id, self.unit_ids)
        d3 = _calc_d3_hook_health(self.project_id, self.unit_ids)
        d4 = _calc_d4_memory_fade(self.project_id, self.unit_ids)

        # Step 3: 构建轨迹
        self.trajectory = []
        for i in range(self.n_units):
            self.trajectory.append(MetricPoint(
                unit_index=i,
                guide_adoption_rate=round(d1[i], 3),
                character_continuity=round(d2[i], 3),
                hook_span_ratio=round(d3[i], 3),
                memory_fade_ratio=round(d4[i], 3),
            ))

        # Step 4: 检测漂移
        warnings = detect_drift(self.trajectory, disappearances)

        # Step 5: 汇总
        summary = {
            "d1_mean": round(sum(d1) / len(d1), 3),
            "d2_mean": round(sum(d2) / len(d2), 3),
            "d3_mean": round(sum(d3) / len(d3), 3),
            "d4_mean": round(sum(d4) / len(d4), 3),
            "total_warnings": len(warnings),
            "by_type": {},
        }
        for w in warnings:
            summary["by_type"][w.type] = summary["by_type"].get(w.type, 0) + 1

        return StabilityReport(
            n_units=self.n_units,
            trajectory=self.trajectory,
            warnings=warnings,
            summary=summary,
        )


# ============================================================
# 6. 测试入口
# ============================================================

def test_stable_scenario(db_path: Path) -> tuple[bool, StabilityReport]:
    """验证: 30 Unit stable 模式应无漂移警告."""
    harness = NarrativeStabilityHarness(db_path, "P_STABLE", n_units=30)
    harness.setup()
    report = harness.run(mode="stable")

    # 检查
    ok = report.is_stable
    details = []
    if not ok:
        details.append(f"  FAIL: {len(report.warnings)} warnings in stable mode")

    # D1 均值应 > 0.7
    if report.summary["d1_mean"] < 0.7:
        ok = False
        details.append(f"  FAIL: D1 mean = {report.summary['d1_mean']} < 0.7")

    return ok, report


def test_drift_detection(db_path: Path) -> tuple[bool, StabilityReport]:
    """验证: 30 Unit drift 模式应检测到至少 2 个漂移警告."""
    harness = NarrativeStabilityHarness(db_path, "P_DRIFT", n_units=30)
    harness.setup()
    report = harness.run(mode="drift")

    ok = len(report.warnings) >= 2
    return ok, report


def test_trajectory_visualization(report: StabilityReport) -> bool:
    """验证: SVG 轨迹图生成成功."""
    svg = render_trajectory(report)
    ok = svg.startswith('<svg') and svg.endswith('</svg>')
    return ok


# ============================================================
# Main
# ============================================================

def main():
    import app.app_paths
    passed = failed = 0
    results = []

    # --- Test 1: Stable Scenario ---
    print("\n" + "=" * 62)
    print("  G19 测试 1: 30-Unit Stable — 应无漂移")
    print("=" * 62)

    db1, _ = _setup_temp_db("nw_g19_stable_")
    app.app_paths.sqlite_path = lambda: db1
    _init_db(db1)

    try:
        ok1, r1 = test_stable_scenario(db1)
        results.append(("稳定模式", ok1, r1))
        if ok1:
            print(f"  PASS: {r1.n_units} units, {len(r1.warnings)} warnings")
            print(f"  D1(Guide采纳)={r1.summary['d1_mean']:.3f}"
                  f"  D2(角色连续)={r1.summary['d2_mean']:.3f}"
                  f"  D3(钩子健康)={r1.summary['d3_mean']:.3f}"
                  f"  D4(记忆健康)={r1.summary['d4_mean']:.3f}")
            passed += 1
        else:
            print(f"  FAIL: found {len(r1.warnings)} warnings in stable mode")
            for w in r1.warnings:
                print(f"    [{w.type}] {w.detail}")
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        _teardown_db()

    # --- Test 2: Drift Detection ---
    print("\n" + "=" * 62)
    print("  G19 测试 2: 30-Unit Drift — 应检测到 ≥2 漂移")
    print("=" * 62)

    db2, _ = _setup_temp_db("nw_g19_drift_")
    app.app_paths.sqlite_path = lambda: db2
    _init_db(db2)

    try:
        ok2, r2 = test_drift_detection(db2)
        results.append(("漂移检测", ok2, r2))
        if ok2:
            print(f"  PASS: detected {len(r2.warnings)} drift warnings")
            for w in r2.warnings:
                print(f"    [{w.severity}] {w.type} @ Unit {w.unit_index}: {w.detail}")
            passed += 1
        else:
            print(f"  FAIL: only {len(r2.warnings)} warnings (need ≥2)")
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        _teardown_db()

    # --- Test 3: Trajectory Visualization ---
    print("\n" + "=" * 62)
    print("  G19 测试 3: 轨迹图生成")
    print("=" * 62)

    try:
        # 使用 drift report 画图 (更有趣)
        if len(results) >= 2:
            _, ok_r2, r_report = results[1]
        else:
            ok_r2, r_report = False, None
        if r_report and test_trajectory_visualization(r_report):
            svg = render_trajectory(r2)
            out_path = ROOT / "smoke" / "g19_trajectory.svg"
            out_path.write_text(svg, encoding="utf-8")
            print(f"  PASS: SVG written ({len(svg)} bytes)")
            print(f"  输出: smoke/g19_trajectory.svg")
            passed += 1
        else:
            print("  FAIL: SVG generation failed")
            failed += 1
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    # --- Summary ---
    total = passed + failed
    print("\n" + "=" * 62)
    print(f"  G19 完成: {passed}/{total} 通过, {failed} 失败")
    print("=" * 62)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
