"""
E3 记忆总管 (Memory Manager)
- 调度: memory (L1-L4) + pressure + anti_ai + character_tracker
- 入口: assemble_for_writing() - 拼装供 v3_engine 用的 prompt section
- 决策: can_proceed() - 当前压力下能否开新钩子
- 写后: after_writing() - 自动更新 (压力/承诺/遗忘) + 反 AI 检查
- 预览: preview() - 给 UI 展示当前记忆状态

v4.1: protected/compressible 分层
- protected: 永远进 prompt (出场角色、未回收伏笔、世界规则)
- compressible: 可压缩/丢弃 (旧弧线、不出场角色、已完成承诺)

DB: app.db.connection
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.core.constants import MemoryLevel, PressureZone
from app.services import anti_ai, character_tracker, memory, pressure

_logger = logging.getLogger("NovelWriter.services.memory_manager")


# ────────────────────── 拼装结果数据类 ──────────────────────

@dataclass
class AssembleResult:
    """assemble_for_writing() 返回的拼装结果。"""
    # 核心记忆
    l1_arcs: list[memory.Memory] = field(default_factory=list)
    l2_commitments: list[memory.Memory] = field(default_factory=list)
    l2_world_rules: list[memory.Memory] = field(default_factory=list)

    # 人物状态
    character_snapshots: dict[str, character_tracker.TrackerSnapshot] = field(default_factory=dict)
    chapter_characters: list[str] = field(default_factory=list)  # 本章出场角色

    # 当前压力
    current_pressure: Optional[pressure.Pressure] = None
    pressure_zone: str = PressureZone.GREEN
    pressure_label: str = ""
    can_open_hook: bool = True
    hook_message: str = ""

    # v4.1: 分层文本
    protected_text: str = ""   # 永远进 prompt
    compressible_text: str = "" # 可压缩/丢弃
    full_text: str = ""        # 兼容旧接口 (protected + compressible)

    # 反 AI 味提示 (include_anti_ai_tips=True 时填充)
    anti_ai_tips: str = ""

    def to_dict(self) -> dict:
        return {
            "l1_count": len(self.l1_arcs),
            "l2_commit_count": len(self.l2_commitments),
            "l2_rule_count": len(self.l2_world_rules),
            "char_count": len(self.character_snapshots),
            "chapter_char_count": len(self.chapter_characters),
            "pressure": self.current_pressure.pressure if self.current_pressure else 0,
            "zone": self.pressure_zone,
            "can_open_hook": self.can_open_hook,
            "protected_chars": len(self.protected_text),
            "compressible_chars": len(self.compressible_text),
        }


# ────────────────────── 拼装入口 ──────────────────────

def assemble_for_writing(
    project_id: str,
    chapter_id: str,
    *,
    include_anti_ai_tips: bool = True,
    max_chars: int = 2000,
) -> AssembleResult:
    """
    写章节前拼装所有上下文 (供 v3_engine 注入 prompt)。

    包含:
      1. L1 故事弧 (主线/副线/人物弧)
      2. L2 已触发承诺 + 待履行承诺 + 世界规则
      3. 角色最新状态 (character_tracker)
      4. 当前叙事压力 + zone + 决策
      5. 反 AI 味提示 (静态, 6 项检查要点)
    """
    result = AssembleResult()

    # 1. L1 故事弧
    for cat in memory.L1_CATEGORIES:
        result.l1_arcs.extend(memory.list_by_category(
            project_id, cat, as_of_chapter=chapter_id,
        ))

    # 2. L2 承诺 + 世界规则
    result.l2_commitments = memory.get_active_commitments(project_id, as_of_chapter=chapter_id)
    # open_promises 也带上 (提醒别忘)
    result.l2_commitments += memory.get_open_promises(project_id, as_of_chapter=chapter_id)
    # 世界规则 (无 chapter 限定)
    for cat in (memory.CAT_WORLD_POWER, memory.CAT_WORLD_VIEW):
        result.l2_world_rules.extend(memory.list_by_category(project_id, cat))

    # 3. 角色状态
    all_chars = character_tracker.get_all_latest(project_id)
    result.character_snapshots = {
        name: snap for name, snap in all_chars.items()
        if snap.chapter_id <= chapter_id
    }

    # 4. 当前压力 (as_of 上一个章)
    # 取当前 chapter_id 之前最后一条压力作为"历史压力"
    conn_pressure = _get_previous_pressure(project_id, chapter_id)
    if conn_pressure:
        result.current_pressure = conn_pressure
        result.pressure_zone = conn_pressure.zone
        result.pressure_label = conn_pressure.label
        result.can_open_hook, result.hook_message = pressure.can_open_new_hook(conn_pressure.pressure)

    # 5. 反 AI 味提示
    if include_anti_ai_tips:
        result.anti_ai_tips = _ANTI_AI_TIPS

    # 拼装 full_text
    result.full_text = _format_assembled(result, max_chars=max_chars)
    return result


# ────────────────────── 决策 ──────────────────────

def can_proceed(project_id: str, chapter_id: str) -> tuple[bool, str]:
    """
    决策: 写当前章前, 是否放行?
    - red zone 直接阻断
    - orange zone 警告 + 建议先关旧
    - yellow/green 放行
    """
    p = _get_previous_pressure(project_id, chapter_id)
    if p is None:
        return True, "无历史压力, 放行"
    if p.zone == PressureZone.RED:
        return False, f"🔴 上一章处于 red 区 (压力 {p.pressure}), 必须先解决旧承诺/支线"
    if p.zone == PressureZone.ORANGE:
        return True, f"🟠 上一章处于 orange 区 (压力 {p.pressure}), 建议先关 1-2 个旧钩子"
    return True, f"放行 (压力 {p.pressure}, {p.zone})"


# ────────────────────── 写后自动更新 ──────────────────────

@dataclass
class AfterWriteResult:
    """after_writing() 返回的更新结果。"""
    # 反 AI 检查
    anti_ai_issues: list[anti_ai.Issue] = field(default_factory=list)
    anti_ai_blocked: bool = False
    anti_ai_summary: dict = field(default_factory=dict)

    # 自动更新
    new_pressure: Optional[pressure.Pressure] = None
    faded_count: int = 0

    def to_dict(self) -> dict:
        return {
            "anti_ai_total": len(self.anti_ai_issues),
            "anti_ai_blocked": self.anti_ai_blocked,
            "anti_ai_summary": self.anti_ai_summary,
            "new_pressure": self.new_pressure.pressure if self.new_pressure else 0,
            "new_zone": self.new_pressure.zone if self.new_pressure else "green",
            "faded_count": self.faded_count,
        }


def after_writing(
    project_id: str,
    chapter_id: str,
    draft: str,
    *,
    active_hooks: int = 0,
    open_promises: int = 0,
    unresolved_subplots: int = 0,
    expected_pov: str = "",
    auto_fade_old_rag: bool = True,
) -> AfterWriteResult:
    """
    写完一章后自动执行:
      1. 反 AI 味检查 (输出 issues + summary)
      2. 更新叙事压力
      3. (可选) 自动 fade 旧的 L3 RAG chunk
    """
    result = AfterWriteResult()

    # 1. 反 AI 检查
    issues = anti_ai.run_all(draft, expected_pov=expected_pov)
    result.anti_ai_issues = issues
    result.anti_ai_summary = anti_ai.summary(issues)
    result.anti_ai_blocked = result.anti_ai_summary.get("has_block", False)

    # 2. 更新压力
    new_p = pressure.record(
        project_id, chapter_id,
        active_hooks=active_hooks,
        open_promises=open_promises,
        unresolved_subplots=unresolved_subplots,
    )
    result.new_pressure = new_p

    # 3. 自动 fade 旧 L3 (保留最近 20 条, 其它入 L4)
    if auto_fade_old_rag:
        rag_chunks = memory.list_by_level(project_id, MemoryLevel.L3_RAG)
        # 按 created_at 升序, 保留后 20 条
        if len(rag_chunks) > 20:
            for old in rag_chunks[:-20]:
                try:
                    memory.fade(project_id, old.id)
                    result.faded_count += 1
                except ValueError:
                    pass  # 已被 fade 跳过

    _logger.info("写后更新: %s @ %s, issues=%d, pressure=%d, faded=%d",
                 chapter_id, project_id, len(issues), new_p.pressure, result.faded_count)
    return result


# ────────────────────── 预览 (UI 用) ──────────────────────

def preview(project_id: str, chapter_id: str) -> dict:
    """
    给 UI 预览: 当前写这章能看到的所有记忆 + 压力。
    返回 dict (前端直接用)。
    """
    asm = assemble_for_writing(project_id, chapter_id)
    return {
        "chapter_id": chapter_id,
        "l1_arcs": [m.to_dict() for m in asm.l1_arcs],
        "l2_commitments": [m.to_dict() for m in asm.l2_commitments],
        "l2_world_rules": [m.to_dict() for m in asm.l2_world_rules],
        "characters": {
            name: snap.to_dict()
            for name, snap in asm.character_snapshots.items()
        },
        "pressure": asm.current_pressure.to_dict() if asm.current_pressure else None,
        "can_open_hook": asm.can_open_hook,
        "hook_message": asm.hook_message,
        "anti_ai_tips": asm.anti_ai_tips,
        "full_text_chars": len(asm.full_text),
    }


# ────────────────────── 内部工具 ──────────────────────

def _get_previous_pressure(project_id: str, chapter_id: str) -> Optional[pressure.Pressure]:
    """取 chapter_id 之前最后一条压力。"""
    all_p = pressure.list_for_project(project_id)
    prev = [p for p in all_p if p.chapter_id < chapter_id]
    if not prev:
        return None
    return prev[-1]


# 13 大去 AI 味静态提示 (拼入 prompt), v4.1 从 6 项扩展到全覆盖
_ANTI_AI_TIPS = """【13 大去 AI 味检查要点】

=== Gate A/B: 高危句式 ===
1. 禁用对比句: 严禁"不是A，而是B"句式，直接写B或用动作呈现
2. 万能状语: 避免"，带着……"万能状语，拆成独立短句或动作描写
3. AI模板表情: 禁用"眼中闪过/嘴角勾起/心中涌起/瞳孔微缩/深吸一口气"，改用具体动作或白描

=== 6 项基础检查 ===
4. 句式去重: 避免连续 3 句用同一句式开头
5. 对话个性: 同角色对话长短交替，语气词适度
6. 节奏呼吸: 避免全段长句 (>= 30 字) 或全段短句 (<= 5 字)
7. 修辞适度: 形容词/副词密度过高会显 AI 味
8. 视角一致: 不要 POV 漂移 (1 段用 first, 下段用 third)
9. 信息差: 不要堆叠"心想"剥夺读者揣测空间

=== Gate G: 解释腔/上帝视角 ===
10. 解释腔: 删除"之所以…是因为/原来…/这意味着"，因果只从动作对话里让读者拼
11. 上帝视角: 删除"她不知道的是/殊不知/多年以后/仿佛预示"，只写角色此刻知道的
12. 安排感: 删除"演得真好/他就是这样的人/关切得恰到好处"，只摆动作台词让读者判

=== Gate F: 结尾升华 ===
13. 结尾不升华: 章尾用动作/留白收束，严禁"终于明白/这一刻/一切…都…/这就是…/命运的齿轮…"
"""


def _format_assembled(asm: AssembleResult, *, max_chars: int) -> str:
    """把 AssembleResult 格式化成 prompt 文本。"""
    parts: list[str] = []

    # 1. L1 故事弧
    if asm.l1_arcs:
        parts.append("【故事弧 (L1)】")
        for m in asm.l1_arcs:
            chap = f" @ {m.chapter_id}" if m.chapter_id else ""
            parts.append(f"  - [{m.label}] {m.content}{chap}")

    # 2. L2 承诺
    if asm.l2_commitments:
        parts.append("\n【承诺 (L2)】")
        for m in asm.l2_commitments:
            tag = "已触发" if m.category == memory.CAT_COMMIT_ACTIVE else "待履行"
            parts.append(f"  - [{tag}] {m.content}")

    # 2b. L2 世界规则
    if asm.l2_world_rules:
        parts.append("\n【世界规则 (L2 不可变)】")
        for m in asm.l2_world_rules:
            parts.append(f"  - [{m.label}] {m.content}")

    # 3. 人物状态
    if asm.character_snapshots:
        parts.append("\n【人物最新状态】")
        for name, snap in list(asm.character_snapshots.items())[:10]:
            non_empty = [
                f"{character_tracker.DIM_LABELS[d]}={getattr(snap, d, '')}"
                for d in character_tracker.ALL_DIMS
                if getattr(snap, d, "")
            ]
            if non_empty:
                parts.append(f"  {name}: " + "; ".join(non_empty))

    # 4. 压力
    if asm.current_pressure:
        parts.append(f"\n【叙事压力】 {asm.pressure_label} (压力 {asm.current_pressure.pressure})")
        parts.append(f"  {asm.hook_message}")

    # 5. 反 AI 提示
    if asm.anti_ai_tips:
        parts.append("\n" + asm.anti_ai_tips)

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "…(已截断)"
    return text


# 导出
__all__ = [
    "AssembleResult", "AfterWriteResult",
    "assemble_for_writing", "can_proceed", "after_writing", "preview",
]
