"""
Story Engine 核心类型定义

v3.5.1: Guide dataclass (5 字段基础版)
v3.5.2: Guide dataclass 升级到 7 字段 (GPT 评审)
  - priority / confidence / scope / advice / reason / evidence_ids / possible_actions

设计原则: Guidance 而非 Constraint
  - score 是判决, advice 是建议
  - 系统不替任何人做决定
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# v3.5.2 新增: Action + Scope 类型
# ============================================================

@dataclass
class Action:
    """Guide 的可选项, 让 AI/作者选择.

    例: pressure guide 可能给出 3 个 Action:
      - "下一 Scene 回收伏笔" (影响 1 个 unit)
      - "延后 2 个 unit" (避免破坏节奏)
      - "删除此伏笔" (彻底放弃)
    """
    label: str                # "下一 Scene 回收" / "延后" / "删除伏笔"
    description: str = ""     # 选项含义
    estimated_impact: dict = field(default_factory=dict)  # 影响范围预估


# Scope 枚举值 (字符串)
GUIDE_SCOPE_PARAGRAPH = "Paragraph"
GUIDE_SCOPE_SCENE = "Scene"
GUIDE_SCOPE_UNIT = "Unit"
GUIDE_SCOPE_BOOK = "Book"
VALID_SCOPES = {
    GUIDE_SCOPE_PARAGRAPH, GUIDE_SCOPE_SCENE, GUIDE_SCOPE_UNIT, GUIDE_SCOPE_BOOK,
}


# ============================================================
# Guide dataclass (v3.5.2 升级)
# ============================================================

@dataclass
class Guide:
    """统一的引导接口, 所有模块都输出这个 (v3.5.2 7 字段版, v3.6 加 guide_id).

    字段说明:
      guide_id:    稳定 ID (source + advice hash, 同一条建议跨 unit 不变)
      priority:    优先级 0-1, 先处理谁 (不是危险度, 是顺序)
      confidence:  置信度 0-1, AI 有多确定 (作者可忽略低置信)
      scope:       作用范围 Paragraph/Scene/Unit/Book
      advice:      人话建议 (核心)
      reason:      为什么这么建议 (推理链)
      evidence_ids: 可追溯证据 (paragraph_id / hook_id / event_id)
      possible_actions: 多选项 (让 AI/作者选)

    向后兼容:
      - severity 字段保留 (作为 priority 的别名, 旧代码读 severity 仍工作)
      - context 字段保留 (机器可读的结构化数据)
      - to_prompt_block() 行为不变
    """
    source: str
    priority: float = 0.5            # 0-1, 默认中等优先级
    advice: str = ""
    confidence: float = 0.7         # 0-1, 默认较高置信
    scope: str = "Unit"              # Paragraph / Scene / Unit / Book
    reason: str = ""                 # 为什么这么建议
    evidence_ids: list = field(default_factory=list)
    possible_actions: list = field(default_factory=list)  # list[Action]
    context: dict = field(default_factory=dict)           # 向后兼容
    severity: float = 0.5           # 向后兼容, 等于 priority
    guide_id: str = ""              # v3.6: 稳定 ID
    conflicts_with: list = field(default_factory=list)    # v4.0: 冲突的 guide_id 列表
    supports: list = field(default_factory=list)          # v4.0: 支持的 guide_id 列表

    def __post_init__(self):
        # 兼容旧字段: 如果只设了 severity, 同步到 priority
        if self.severity != 0.5 and self.priority == 0.5:
            self.priority = self.severity
        elif self.priority != 0.5 and self.severity == 0.5:
            self.severity = self.priority

        # scope 校验
        if self.scope not in VALID_SCOPES:
            self.scope = "Unit"

        # 数值范围裁剪
        self.priority = max(0.0, min(1.0, float(self.priority)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

        # v3.6: 自动生成稳定 guide_id (source + advice md5, 幂等)
        if not self.guide_id:
            import hashlib
            raw = f"{self.source}|{self.advice}".encode("utf-8")
            self.guide_id = hashlib.md5(raw).hexdigest()[:12]

    def to_prompt_block(self) -> str:
        """格式化进 LLM prompt (向后兼容).

        v3.5.2 增强:
          - 在建议前标注 scope 和 confidence (让 AI 知道确定度)
          - 添加 reason (推理链)
        """
        conf_marker = ""
        if self.confidence < 0.5:
            conf_marker = "[AI 不太确定, 可忽略] "
        return (
            f"[{self.source} 建议 | scope={self.scope} | "
            f"confidence={self.confidence:.2f}] "
            f"{conf_marker}{self.advice}"
            + (f" (理由: {self.reason})" if self.reason else "")
        )

    def to_dict(self) -> dict:
        """序列化 (供 UI / API)."""
        return {
            "guide_id": self.guide_id,
            "source": self.source,
            "priority": self.priority,
            "confidence": self.confidence,
            "scope": self.scope,
            "advice": self.advice,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
            "possible_actions": [
                {"label": a.label, "description": a.description,
                 "estimated_impact": a.estimated_impact}
                for a in self.possible_actions
            ],
            "context": dict(self.context),
            "severity": self.severity,  # 向后兼容
            "conflicts_with": list(self.conflicts_with),  # v4.0
            "supports": list(self.supports),              # v4.0
        }


# ============================================================
# v3.6: Decision dataclass
# ============================================================

@dataclass
class Decision:
    """AI/作者对 Guide 的采纳决策记录.

    v3.6 核心: 记录"AI 采纳/忽略/修改了哪个 Guide"并注入 prompt.
    """
    unit_id: str
    guide_id: str               # 对应 Guide.guide_id
    action: str                 # "adopted" / "ignored" / "modified"
    reason: str = ""            # 为什么采纳/忽略
    step_no: int = 0
    project_id: str = ""
    guide_source: str = ""
    id: str = ""
    decided_by: str = "ai"      # "ai" / "author"
    decided_at: str = ""
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "project_id": self.project_id,
            "step_no": self.step_no,
            "guide_id": self.guide_id,
            "guide_source": self.guide_source,
            "action": self.action,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "context": self.context,
        }

    @classmethod
    def from_row(cls, row) -> "Decision":
        import json
        ctx_raw = row["context"] or "{}"
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            unit_id=row["unit_id"],
            step_no=row["step_no"] or 0,
            guide_id=row["guide_id"],
            guide_source=row["guide_source"],
            action=row["action"],
            reason=row["reason"] or "",
            decided_by=row["decided_by"] or "ai",
            decided_at=row["decided_at"] or "",
            context=json.loads(ctx_raw),
        )


# ============================================================
# collect_guides (v3.5.2 接入所有模块)
# ============================================================

def collect_guides(unit_id: str, project_id: str = "") -> list[Guide]:
    """统一收集所有模块的 Guide (v3.5.2 升级, v4.0 集成冲突图).

    返回按 priority 倒序排列的 Guide 列表, Orchestrator 注入 Writer prompt 时使用.
    v4.0: Guide 带 conflicts_with/supports, 调用方可用 guide_graph.analyze() 构建冲突图.

    接入顺序 (按 Source 字典序, 让输出稳定):
      - character_state (角色状态)
      - consistency (一致性)
      - hook (钩子)
      - memory (记忆)
      - pressure (压力)
      - reader_signal (读者信号)
      - style (风格)
      - voice (声音)
      - unit_event (事件流)

    每个模块内部 try/except, 单个失败不影响整体.
    """
    guides: list[Guide] = []

    # ---- character_state (角色状态) ----
    try:
        from app.services import character_state as _cs
        if hasattr(_cs, "get_guides"):
            guides.extend(_cs.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- character_arc (角色弧线) ----
    try:
        from app.services import character_arc_service as _arc
        if hasattr(_arc, "get_guides"):
            guides.extend(_arc.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- consistency (一致性) ----
    try:
        from app.services import consistency as _consistency
        if hasattr(_consistency, "get_guides"):
            guides.extend(_consistency.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- hook (钩子) ----
    try:
        from app.services import unit_hook_service as _hook
        if hasattr(_hook, "get_guides"):
            guides.extend(_hook.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- memory (记忆) ----
    try:
        from app.services import memory as _mem
        if hasattr(_mem, "get_guides"):
            guides.extend(_mem.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- pressure (压力) ----
    try:
        from app.services import pressure as _pres
        if hasattr(_pres, "get_guides"):
            guides.extend(_pres.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- reader_signal (读者信号) ----
    try:
        from app.services import reader_signal as _reader
        if hasattr(_reader, "get_guides"):
            guides.extend(_reader.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- style (风格) ----
    try:
        from app.services import style_fingerprint as _style
        if hasattr(_style, "get_guides"):
            guides.extend(_style.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- voice (声音) ----
    try:
        from app.services import voice_profile as _voice
        if hasattr(_voice, "get_guides"):
            guides.extend(_voice.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # ---- unit_event (事件流) ----
    try:
        from app.services import unit_event_service as _ev
        if hasattr(_ev, "get_guides"):
            guides.extend(_ev.get_guides(unit_id, project_id=project_id))
    except Exception:
        pass

    # v4.0: 自动构建冲突图, 标记 conflicts_with/supports
    try:
        from app.services.guide_graph import analyze as _analyze_graph
        graph = _analyze_graph(guides)
        if graph.edges:
            _set_graph_edges(guides, graph)
    except Exception:
        pass

    # 按 priority 倒序 (v3.5.2: 替换 severity)
    return sorted(guides, key=lambda g: -g.priority)


def _set_graph_edges(guides: list[Guide], graph) -> None:
    """v4.0: 把冲突图边写入 Guide 对象."""
    guide_map = {g.guide_id: g for g in guides}
    for edge in graph.edges:
        a = guide_map.get(edge.guide_a)
        b = guide_map.get(edge.guide_b)
        if a is None or b is None:
            continue
        if edge.is_conflict:
            if edge.guide_b not in a.conflicts_with:
                a.conflicts_with.append(edge.guide_b)
            if edge.guide_a not in b.conflicts_with:
                b.conflicts_with.append(edge.guide_a)
        elif edge.is_support:
            if edge.guide_b not in a.supports:
                a.supports.append(edge.guide_b)
            if edge.guide_a not in b.supports:
                b.supports.append(edge.guide_a)


def collect_guides_dict(unit_id: str, project_id: str = "") -> list[dict]:
    """collect_guides() 的 dict 序列化版本, 供 UI / API."""
    return [g.to_dict() for g in collect_guides(unit_id, project_id=project_id)]