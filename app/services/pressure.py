"""
E2 叙事压力计 (4 zone: green/yellow/orange/red)
- 每章 1 行: pressure / active_hooks / open_promises / unresolved_subplots
- zone 自动计算 (基于 pressure)
- deadline_chapter 可选 (用于红区阻断)
- 用途: v3_engine 第 3 步检查, 决定是否放行新钩子

DB: app.db.connection
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db._impl import transaction, get_conn
from app.core.constants import PressureZone, PRESSURE_THRESHOLDS

_logger = logging.getLogger("NovelWriter.services.pressure")


# 4 zone 排序
ZONE_ORDER = [
    PressureZone.GREEN,
    PressureZone.YELLOW,
    PressureZone.ORANGE,
    PressureZone.RED,
]

ZONE_LABELS = {
    PressureZone.GREEN: "🟢 自由 (0-30)",
    PressureZone.YELLOW: "🟡 谨慎 (30-70)",
    PressureZone.ORANGE: "🟠 必关 (70-95)",
    PressureZone.RED: "🔴 阻止 (95+)",
}

ZONE_COLORS = {
    PressureZone.GREEN: "#22c55e",
    PressureZone.YELLOW: "#eab308",
    PressureZone.ORANGE: "#f97316",
    PressureZone.RED: "#ef4444",
}


# ────────────────────── 数据类 ──────────────────────

@dataclass
class Pressure:
    """单章压力记录 (一行 DB 记录)。"""
    id: str
    project_id: str
    chapter_id: str
    pressure: int = 0
    active_hooks: int = 0
    open_promises: int = 0
    unresolved_subplots: int = 0
    zone: str = PressureZone.GREEN
    deadline_chapter: Optional[int] = None
    created_at: str = ""

    @property
    def label(self) -> str:
        return ZONE_LABELS.get(self.zone, self.zone)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "pressure": self.pressure,
            "active_hooks": self.active_hooks,
            "open_promises": self.open_promises,
            "unresolved_subplots": self.unresolved_subplots,
            "zone": self.zone,
            "zone_label": self.label,
            "deadline_chapter": self.deadline_chapter,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row) -> "Pressure":
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            chapter_id=row["chapter_id"],
            pressure=row["pressure"] or 0,
            active_hooks=row["active_hooks"] or 0,
            open_promises=row["open_promises"] or 0,
            unresolved_subplots=row["unresolved_subplots"] or 0,
            zone=row["zone"] or PressureZone.GREEN,
            deadline_chapter=row["deadline_chapter"],
            created_at=row["created_at"] or "",
        )


# ────────────────────── 写入 ──────────────────────

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def compute_zone(pressure: int) -> str:
    """
    根据压力值计算 zone。
    - 0-29:   green
    - 30-69:  yellow
    - 70-94:  orange
    - 95-∞:   red
    """
    if pressure < 0:
        pressure = 0
    # ORANGE threshold = RED 起点 (>=95)
    if pressure >= PRESSURE_THRESHOLDS[PressureZone.ORANGE]:
        return PressureZone.RED
    if pressure >= PRESSURE_THRESHOLDS[PressureZone.YELLOW]:
        return PressureZone.ORANGE
    if pressure >= PRESSURE_THRESHOLDS[PressureZone.GREEN]:
        return PressureZone.YELLOW
    return PressureZone.GREEN


def compute_pressure(
    active_hooks: int = 0,
    open_promises: int = 0,
    unresolved_subplots: int = 0,
    *,
    weights: Optional[dict[str, int]] = None,
) -> int:
    """
    根据钩子/承诺/支线数计算压力值。
    - 默认权重: hook=5, promise=8, subplot=3
    - 总压力 = Σ(count × weight)
    """
    if weights is None:
        weights = {"hook": 5, "promise": 8, "subplot": 3}
    h = max(0, int(active_hooks)) * weights.get("hook", 5)
    p = max(0, int(open_promises)) * weights.get("promise", 8)
    s = max(0, int(unresolved_subplots)) * weights.get("subplot", 3)
    return h + p + s


def record(
    project_id: str,
    chapter_id: str,
    *,
    active_hooks: int = 0,
    open_promises: int = 0,
    unresolved_subplots: int = 0,
    deadline_chapter: Optional[int] = None,
    pressure: Optional[int] = None,
) -> Pressure:
    """
    记录一章压力 (upsert: 同 chapter 多次写入会覆盖)。
    - pressure 不传时自动根据 3 个分量计算
    - zone 自动根据 pressure 计算
    """
    if not project_id or not chapter_id:
        raise ValueError("project_id / chapter_id 必填")
    if pressure is None:
        pressure = compute_pressure(active_hooks, open_promises, unresolved_subplots)
    pressure = max(0, int(pressure))
    zone = compute_zone(pressure)

    p = Pressure(
        id=_new_id(),
        project_id=project_id,
        chapter_id=chapter_id,
        pressure=pressure,
        active_hooks=max(0, int(active_hooks)),
        open_promises=max(0, int(open_promises)),
        unresolved_subplots=max(0, int(unresolved_subplots)),
        zone=zone,
        deadline_chapter=deadline_chapter,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    with transaction() as conn:
        conn.execute(
            "DELETE FROM narrative_pressures WHERE project_id=? AND chapter_id=?",
            (project_id, chapter_id),
        )
        conn.execute(
            """
            INSERT INTO narrative_pressures
                (id, project_id, chapter_id, pressure, active_hooks, open_promises,
                 unresolved_subplots, zone, deadline_chapter, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (p.id, p.project_id, p.chapter_id, p.pressure, p.active_hooks,
             p.open_promises, p.unresolved_subplots, p.zone, p.deadline_chapter, p.created_at),
        )
    _logger.info("记录压力: %s @ %s → %s (%s)", chapter_id, project_id, p.pressure, p.zone)
    return p


def get_for_chapter(project_id: str, chapter_id: str) -> Optional[Pressure]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM narrative_pressures WHERE project_id=? AND chapter_id=?",
        (project_id, chapter_id),
    ).fetchone()
    if row is None:
        return None
    return Pressure.from_row(row)


def list_for_project(project_id: str) -> list[Pressure]:
    """列出项目所有章压力, 按 chapter_id 排序。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM narrative_pressures WHERE project_id=? ORDER BY chapter_id ASC",
        (project_id,),
    ).fetchall()
    return [Pressure.from_row(r) for r in rows]


def get_latest(project_id: str) -> Optional[Pressure]:
    """取项目内最新一章压力。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM narrative_pressures WHERE project_id=? ORDER BY chapter_id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return Pressure.from_row(row)


def get_trend(project_id: str, last_n: int = 5) -> list[Pressure]:
    """取最近 N 章压力 (用于趋势分析)。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM narrative_pressures WHERE project_id=? ORDER BY chapter_id DESC LIMIT ?",
        (project_id, last_n),
    ).fetchall()
    return list(reversed([Pressure.from_row(r) for r in rows]))


# ────────────────────── 决策辅助 ──────────────────────

def can_open_new_hook(pressure_val: int) -> tuple[bool, str]:
    """
    决策: 现有压力下能否开新钩子?
    - green:  允许
    - yellow: 允许 (建议控制)
    - orange: 不建议 (必关某些旧的)
    - red:    阻止 (需先解决)
    """
    zone = compute_zone(pressure_val)
    if zone == PressureZone.GREEN:
        return True, "🟢 自由, 可开新钩子"
    if zone == PressureZone.YELLOW:
        return True, "🟡 谨慎, 可开 1-2 个但需关注"
    if zone == PressureZone.ORANGE:
        return False, "🟠 必关, 建议先关 1-2 个旧钩子"
    return False, "🔴 阻止, 必先解决旧承诺/支线"


def zone_summary(project_id: str) -> dict[str, int]:
    """统计各 zone 章节数。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT zone, COUNT(*) AS n FROM narrative_pressures WHERE project_id=? GROUP BY zone",
        (project_id,),
    ).fetchall()
    return {r["zone"]: r["n"] for r in rows}


def delete_for_chapter(project_id: str, chapter_id: str) -> int:
    """删除某章压力记录 (章节删除时用)。"""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM narrative_pressures WHERE project_id=? AND chapter_id=?",
        (project_id, chapter_id),
    )
    return cur.rowcount or 0


# ────────────────────── 格式化 ──────────────────────

def format_for_prompt(p: Pressure) -> str:
    """单章压力格式化 (prompt 拼装)。"""
    if p is None:
        return "(无压力记录)"
    lines = [
        f"【{p.chapter_id} 叙事压力】",
        f"  - 区域: {p.label}",
        f"  - 总压力: {p.pressure}",
        f"  - 活跃钩子: {p.active_hooks}",
        f"  - 待履行承诺: {p.open_promises}",
        f"  - 未解支线: {p.unresolved_subplots}",
    ]
    if p.deadline_chapter is not None:
        lines.append(f"  - 截止章: {p.deadline_chapter}")
    return "\n".join(lines)


def format_trend(pressures: list[Pressure]) -> str:
    """趋势格式化。"""
    if not pressures:
        return "(无压力趋势)"
    lines = ["【叙事压力趋势】"]
    for p in pressures:
        lines.append(f"  {p.chapter_id}: {p.pressure} ({p.label})")
    return "\n".join(lines)


# ────────────────────── 节奏报告 (v3.4 新增) ──────────────────────

def rhythm_report(project_id: str, last_n_chapters: int = 10) -> dict:
    """
    长篇节奏报告: 分析最近N章的压力分布、钩子密度、情绪曲线。
    
    Returns:
        {
            "pressure_distribution": {"green": N, "yellow": N, "orange": N, "red": N},
            "avg_pressure": float,
            "hook_density": float,  # 平均每章活跃钩子数
            "trend": "rising" | "falling" | "stable",  # 压力趋势
            "warnings": list[str],  # 节奏问题警告
            "suggestions": list[str],  # 优化建议
        }
    """
    pressures = list_for_project(project_id)
    if not pressures:
        return {
            "pressure_distribution": {"green": 0, "yellow": 0, "orange": 0, "red": 0},
            "avg_pressure": 0,
            "hook_density": 0,
            "trend": "stable",
            "warnings": [],
            "suggestions": ["暂无章节数据，无法生成节奏报告"],
        }
    
    # 取最近N章
    recent = pressures[-last_n_chapters:] if len(pressures) > last_n_chapters else pressures
    
    # 压力分布统计
    dist = {"green": 0, "yellow": 0, "orange": 0, "red": 0}
    for p in recent:
        zone = p.zone
        if zone in dist:
            dist[zone] += 1
    
    # 平均压力
    avg_pressure = sum(p.pressure for p in recent) / len(recent)
    
    # 钩子密度 (平均每章活跃钩子数)
    avg_hooks = sum(p.active_hooks for p in recent) / len(recent)
    
    # 压力趋势 (对比前5章和后5章)
    if len(recent) >= 10:
        first_half = recent[:5]
        second_half = recent[-5:]
        avg_first = sum(p.pressure for p in first_half) / 5
        avg_second = sum(p.pressure for p in second_half) / 5
        if avg_second > avg_first + 10:
            trend = "rising"
        elif avg_second < avg_first - 10:
            trend = "falling"
        else:
            trend = "stable"
    else:
        trend = "stable"
    
    # 生成警告和建议
    warnings = []
    suggestions = []
    
    # 警告1: 红区过多
    if dist["red"] >= 3:
        warnings.append(f"最近{len(recent)}章中有{dist['red']}章处于红区，压力过大")
        suggestions.append("建议安排1-2章的缓冲章节，回收部分钩子和承诺")
    
    # 警告2: 绿区过多 (节奏太平)
    if dist["green"] >= len(recent) * 0.7:
        warnings.append(f"最近{len(recent)}章中有{dist['green']}章处于绿区，节奏偏平")
        suggestions.append("建议增加冲突和悬念，提升叙事张力")
    
    # 警告3: 钩子密度过高
    if avg_hooks > 5:
        warnings.append(f"平均每章{avg_hooks:.1f}个活跃钩子，密度过高")
        suggestions.append("建议回收部分旧钩子，避免读者记忆负担")
    
    # 警告4: 压力持续上升
    if trend == "rising" and avg_pressure > 60:
        warnings.append("压力持续上升，可能需要高潮后的缓冲")
        suggestions.append("建议在接下来的1-2章安排阶段性胜利或情感释放")
    
    # 警告5: 压力持续下降
    if trend == "falling" and avg_pressure < 30:
        warnings.append("压力持续下降，叙事可能缺乏张力")
        suggestions.append("建议引入新的冲突或悬念，重新抓住读者注意力")
    
    # 通用建议
    if not warnings:
        suggestions.append("节奏控制良好，继续保持")
    
    return {
        "pressure_distribution": dist,
        "avg_pressure": round(avg_pressure, 1),
        "hook_density": round(avg_hooks, 1),
        "trend": trend,
        "warnings": warnings,
        "suggestions": suggestions,
    }


def format_rhythm_report(report: dict) -> str:
    """格式化节奏报告为可读文本。"""
    lines: list[str] = []
    
    # 压力分布
    dist = report["pressure_distribution"]
    lines.append("压力分布:")
    lines.append(f"  🟢 绿区: {dist['green']}章")
    lines.append(f"  🟡 黄区: {dist['yellow']}章")
    lines.append(f"  🟠 橙区: {dist['orange']}章")
    lines.append(f"  🔴 红区: {dist['red']}章")
    lines.append("")
    
    # 核心指标
    lines.append(f"平均压力: {report['avg_pressure']}")
    lines.append(f"钩子密度: {report['hook_density']}个/章")
    trend_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}
    lines.append(f"压力趋势: {trend_icon.get(report['trend'], '➡️')} {report['trend']}")
    lines.append("")
    
    # 警告
    if report["warnings"]:
        lines.append("⚠️ 警告:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
        lines.append("")
    
    # 建议
    if report["suggestions"]:
        lines.append("💡 建议:")
        for s in report["suggestions"]:
            lines.append(f"  - {s}")

    return "\n".join(lines)


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审, 4 维度)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回叙事压力相关的 Guide 列表 (4 维度).

    4 维度:
      1. Narrative Pressure (叙事节奏) - 来自 narrative_pressures 表
      2. Character Pressure (角色目标压力) - 来自 open_promises + character_state
      3. Timeline Pressure (时间线压力) - 角色有截止日期的目标
      4. Reader Pressure (读者阅读节奏) - N 章未高潮提示

    每个维度独立生成一条 Guide, Orchestrator 可按 priority 排序注入.
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT

    if not project_id:
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    guides: list[Guide] = []

    # ---- 维度 1: Narrative Pressure (基于已有 zone) ----
    try:
        latest = get_latest(project_id)
        if latest:
            zone = latest.zone
            pressure_val = latest.pressure or 0
            active_hooks = latest.active_hooks or 0
            open_promises = latest.open_promises or 0

            if zone in ("orange", "red"):
                advice = (
                    f"叙事压力进入 {zone} zone ({pressure_val}/100), "
                    f"active_hooks={active_hooks}, open_promises={open_promises}。"
                    f"建议下一 unit 回收部分伏笔/承诺, 释放压力。"
                )
                possible_actions = [
                    Action(label="回收伏笔", description="兑现一个 active hook, 降低 pressure"),
                    Action(label="兑现承诺", description="履行一个 open promise, 缓解节奏"),
                    Action(label="维持张力", description="保持当前节奏, 但要避免压力继续上升"),
                ]
                priority = 0.8 if zone == "red" else 0.65
            elif zone == "yellow":
                advice = (
                    f"叙事压力 yellow ({pressure_val}/100), 节奏接近临界点。"
                    f"如未来 1-2 unit 不处理, 可能进入 orange zone。"
                )
                possible_actions = [
                    Action(label="谨慎推进", description="继续当前节奏, 但避免新增 plant"),
                ]
                priority = 0.5
            else:  # green
                advice = (
                    f"叙事压力 green ({pressure_val}/100), 节奏平稳。"
                    f"如需要增加戏剧性, 可适当新增 plant。"
                )
                possible_actions = [
                    Action(label="继续", description="维持当前节奏"),
                    Action(label="可加钩子", description="如剧情需要, 可新增 plant"),
                ]
                priority = 0.3

            guides.append(Guide(
                source="pressure",
                priority=priority,
                confidence=0.95,
                scope=GUIDE_SCOPE_UNIT,
                advice=advice,
                reason=f"基于 narrative_pressures 表最新一条: zone={zone}, pressure={pressure_val}",
                evidence_ids=[latest.id] if hasattr(latest, "id") else [],
                possible_actions=possible_actions,
                context={
                    "dimension": "narrative",
                    "zone": zone,
                    "pressure": pressure_val,
                    "active_hooks": active_hooks,
                    "open_promises": open_promises,
                },
            ))
    except Exception:
        pass

    # ---- 维度 2: Character Pressure (角色目标压力) ----
    try:
        from app.services import memory as _mem
        # 统计 role pressure: 角色有 deadline 的承诺数量
        open_promises = _mem.get_open_promises_as_of_unit(
            project_id, as_of_unit=unit_id, as_of_step=0
        )
        # 简化: 角色压力 = open_promises 中 deadline_related 的数量
        char_pressure_count = len(open_promises)
        if char_pressure_count > 0:
            guides.append(Guide(
                source="pressure",
                priority=min(0.7, 0.3 + 0.05 * char_pressure_count),
                confidence=0.6,  # 较低置信, 因为只是 count 估算
                scope=GUIDE_SCOPE_UNIT,
                advice=(
                    f"角色目标压力: {char_pressure_count} 个未兑现承诺。"
                    f"AI 写作时需注意角色不能突然忘记这些目标。"
                ),
                reason=f"基于 open_promises 数量估算 (Character Pressure 维度)",
                evidence_ids=[m.id for m in open_promises[:5]],
                possible_actions=[
                    Action(label="角色推进", description="让主角/配角主动推进目标"),
                    Action(label="兑现承诺", description="履行部分承诺释放压力"),
                ],
                context={
                    "dimension": "character",
                    "open_promises": char_pressure_count,
                },
            ))
    except Exception:
        pass

    # ---- 维度 3: Timeline Pressure (时间线压力) ----
    # 当前数据模型无 deadline 字段, 此维度作为占位
    # v3.6 引入 Decision 层后, 再基于 Decision 中的 reason 提取 deadline 信息
    try:
        # 计算单元平均字数 vs target, 如偏差大 → 时间线压力高
        from app.services import story_unit_service_v2 as _unit_svc
        unit = _unit_svc.get(unit_id)
        if unit:
            current_chars = unit.word_count or 0
            target_chars = unit.target_chars or 0
            if target_chars > 0:
                progress = current_chars / target_chars
                if progress < 0.3:
                    guides.append(Guide(
                        source="pressure",
                        priority=0.55,
                        confidence=0.7,
                        scope="Unit",
                        advice=f"单元写作进度仅 {progress*100:.0f}%, 距离目标字数 {target_chars} 还差 {target_chars - current_chars} 字。",
                        reason=f"Timeline Pressure: 当前 {current_chars}/{target_chars} 字",
                        evidence_ids=[],
                        possible_actions=[
                            Action(label="加速写作", description="提高每步字数"),
                            Action(label="调整目标", description="如果目标过高, 适当下调 target_chars"),
                        ],
                        context={"dimension": "timeline", "progress": progress, "current": current_chars, "target": target_chars},
                    ))
    except Exception:
        pass

    # ---- 维度 4: Reader Pressure (读者阅读节奏) ----
    # 简化: 用 trend 中连续低 zone 数, 推算读者可能疲劳
    try:
        trend = get_trend(project_id, last_n=5)
        if len(trend) >= 3:
            recent_zones = [p.zone for p in trend[-3:]]
            if all(z == "green" for z in recent_zones):
                guides.append(Guide(
                    source="pressure",
                    priority=0.5,
                    confidence=0.65,
                    scope=GUIDE_SCOPE_BOOK,
                    advice=(
                        f"最近 {len(recent_zones)} 个 unit 都处于 green zone (压力平稳)。"
                        f"读者可能期待下一个高潮, 建议在当前或下个 unit 引入转折。"
                    ),
                    reason=f"Reader Pressure: 最近 zone={recent_zones}",
                    evidence_ids=[],
                    possible_actions=[
                        Action(label="引入转折", description="在当前 unit 制造冲突升级"),
                        Action(label="继续平稳", description="保持当前节奏, 让读者休息"),
                    ],
                    context={"dimension": "reader", "recent_zones": recent_zones},
                ))
    except Exception:
        pass

    return guides


# 导出
__all__ = [
    "Pressure",
    "ZONE_ORDER", "ZONE_LABELS", "ZONE_COLORS",
    "compute_zone", "compute_pressure",
    "record", "get_for_chapter", "list_for_project", "get_latest", "get_trend",
    "can_open_new_hook", "zone_summary", "delete_for_chapter",
    "format_for_prompt", "format_trend",
    "rhythm_report", "format_rhythm_report",  # v3.4 新增
]
