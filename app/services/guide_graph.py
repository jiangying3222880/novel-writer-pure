"""
Guide Graph Service (v4.0)

自动检测 Guide 之间的 conflict / support 关系, 生成冲突图 prompt 块.

设计原则:
  - 图关系不需要模块方手动标注 conflicts_with——自动推断
  - 冲突规则基于 advice 语义分析 (轻量关键字匹配, 不调 LLM)
  - 不替 AI 裁决冲突, 只报告"这里存在权衡"

API:
  - analyze(guides) → GuideGraphResult
  - build_graph_block(result) → str (prompt 注入用)
  - detect_conflict(g_a, g_b) → str | None (冲突原因或 None)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

_logger = logging.getLogger("NovelWriter.services.guide_graph")


# ============================================================
# Guide Graph 数据结构
# ============================================================

@dataclass
class GuideEdge:
    """Guide 之间的边 (conflict / support)."""
    guide_a: str   # guide_id
    guide_b: str   # guide_id
    relation: str  # "conflict" / "support"
    reason: str    # 判定原因

    @property
    def is_conflict(self) -> bool:
        return self.relation == "conflict"

    @property
    def is_support(self) -> bool:
        return self.relation == "support"


@dataclass
class GuideGraphResult:
    edges: list[GuideEdge] = field(default_factory=list)
    guide_lookup: dict = field(default_factory=dict)  # guide_id → Guide

    @property
    def conflicts(self) -> list[GuideEdge]:
        return [e for e in self.edges if e.is_conflict]

    @property
    def supports(self) -> list[GuideEdge]:
        return [e for e in self.edges if e.is_support]

    @property
    def has_conflicts(self) -> bool:
        return any(e.is_conflict for e in self.edges)

    def to_dict(self) -> dict:
        return {
            "edges": [
                {"a": e.guide_a, "b": e.guide_b, "relation": e.relation, "reason": e.reason}
                for e in self.edges
            ],
            "conflict_count": len(self.conflicts),
            "support_count": len(self.supports),
        }


# ============================================================
# 冲突检测规则 (基于 advice 关键字)
# ============================================================

# 冲突对: (方向 A 的关键字, 方向 B 的关键字) → 冲突原因描述
CONFLICT_RULES: list[tuple[list[str], list[str], str]] = [
    (["加速", "爆发", "高潮", "紧张", "密集", "快节奏"],
     ["放缓", "慢一点", "减速", "舒缓", "慢下来", "留白"],
     "节奏冲突: 一方建议加速, 另一方建议放缓"),
    (["回收", "兑现", "结尾", "收束", "关闭"],
     ["开放", "埋下", "新增", "铺垫", "延后", "搁置"],
     "伏笔策略冲突: 一方建议回收, 另一方建议继续铺垫"),
    (["情感冲击", "热血", "爽感", "爆点"],
     ["理性", "内敛", "克制", "压抑", "留白"],
     "情感基调冲突: 一方建议外放, 另一方建议内敛"),
    (["透明", "解释", "说明", "交代"],
     ["隐藏", "暗线", "暗示", "不解释", "留悬念"],
     "信息揭示冲突: 一方建议解释, 另一方建议隐藏"),
    (["对话", "对白", "人物互动"],
     ["描写", "场景", "环境", "旁白", "叙述"],
     "叙事手法冲突: 一方建议对话推进, 另一方建议场景描写"),
]


# 支持对: 如果两个 Guide 的 source 相同且 advice 方向一致
SOURCE_COLLABORATION = {
    "pressure": ["pressure", "hook"],
    "reader_signal": ["reader_signal", "pressure"],
    "character_state": ["character_state", "consistency"],
    "voice": ["voice", "style"],
    "style": ["style", "voice"],
}


def detect_conflict(g_a, g_b) -> str | None:
    """检测两个 Guide 是否冲突, 返回冲突原因或 None.

    g_a/g_b 可是 Guide 对象或 dict.
    """
    a_advice = g_a.advice if hasattr(g_a, "advice") else g_a.get("advice", "")
    b_advice = g_b.advice if hasattr(g_b, "advice") else g_b.get("advice", "")

    if not a_advice or not b_advice:
        return None

    for keywords_a, keywords_b, reason in CONFLICT_RULES:
        a_match = any(kw in a_advice for kw in keywords_a)
        b_match = any(kw in b_advice for kw in keywords_b)
        if a_match and b_match:
            return reason
        # 双向检测
        a_match_r = any(kw in a_advice for kw in keywords_b)
        b_match_r = any(kw in b_advice for kw in keywords_a)
        if a_match_r and b_match_r:
            return reason

    return None


def detect_support(g_a, g_b) -> str | None:
    """检测两个 Guide 是否方向一致 (support)."""
    a_src = g_a.source if hasattr(g_a, "source") else g_a.get("source", "")
    b_src = g_b.source if hasattr(g_b, "source") else g_b.get("source", "")

    for src, collab in SOURCE_COLLABORATION.items():
        if a_src == src and b_src in collab:
            a_advice = g_a.advice if hasattr(g_a, "advice") else g_a.get("advice", "")
            b_advice = g_b.advice if hasattr(g_b, "advice") else g_b.get("advice", "")
            # 简单判定: 如果 advice 中有相同关键词, 方向一致
            common_keywords = {"加速", "爆发", "回收", "紧张", "一致性", "风格", "对白"}
            if any(kw in a_advice and kw in b_advice for kw in common_keywords):
                return f"协同: [{a_src}] + [{b_src}] 方向一致"
    return None


# ============================================================
# 图分析
# ============================================================

def analyze(guides: list, *, skip_low_confidence: bool = True,
            project_id: str = "", unit_id: str = "") -> GuideGraphResult:
    """分析 Guide 列表中的冲突/支持关系.

    Args:
        guides: Guide 对象列表 (也可接受 dict)
        skip_low_confidence: 跳过 confidence < 0.5 的 Guide
        project_id: 项目ID (可选, 用于冲突日志)
        unit_id: 单元ID (可选, 用于冲突日志)

    Returns:
        GuideGraphResult
    """
    guide_lookup: dict[str, any] = {}
    active: list = []

    for g in guides:
        gid = g.guide_id if hasattr(g, "guide_id") else g.get("guide_id", "")
        conf = g.confidence if hasattr(g, "confidence") else g.get("confidence", 0.7)
        if skip_low_confidence and conf < 0.5:
            continue
        if gid:
            guide_lookup[gid] = g
            active.append(g)

    edges: list[GuideEdge] = []

    # O(n²) 对比——Guide 数量通常 < 20, 完全可接受
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            g_a = active[i]
            g_b = active[j]
            gid_a = g_a.guide_id if hasattr(g_a, "guide_id") else g_a.get("guide_id", "")
            gid_b = g_b.guide_id if hasattr(g_b, "guide_id") else g_b.get("guide_id", "")

            # 先检测冲突
            conflict_reason = detect_conflict(g_a, g_b)
            if conflict_reason:
                edges.append(GuideEdge(gid_a, gid_b, "conflict", conflict_reason))
                # 写入冲突日志
                if project_id and unit_id:
                    try:
                        from app.services.conflict_log import log_conflict
                        src_a = g_a.source if hasattr(g_a, "source") else g_a.get("source", "?")
                        src_b = g_b.source if hasattr(g_b, "source") else g_b.get("source", "?")
                        adv_a = g_a.advice if hasattr(g_a, "advice") else g_a.get("advice", "")
                        adv_b = g_b.advice if hasattr(g_b, "advice") else g_b.get("advice", "")
                        log_conflict(
                            project_id=project_id,
                            unit_id=unit_id,
                            conflict_type="causal",
                            description=f"{conflict_reason}: [{src_a}] {adv_a} vs [{src_b}] {adv_b}",
                            source_a=f"{src_a}/{gid_a}",
                            source_b=f"{src_b}/{gid_b}",
                            confidence=min(g_a.confidence if hasattr(g_a, "confidence") else g_a.get("confidence", 0.7),
                                          g_b.confidence if hasattr(g_b, "confidence") else g_b.get("confidence", 0.7)),
                        )
                    except Exception as e:
                        _logger.warning("Failed to log conflict: %s", e)
                continue

            # 再检测支持
            support_reason = detect_support(g_a, g_b)
            if support_reason:
                edges.append(GuideEdge(gid_a, gid_b, "support", support_reason))

    _logger.info("Guide Graph: %d nodes, %d edges (%d conflicts, %d supports)",
                 len(active), len(edges),
                 sum(1 for e in edges if e.is_conflict),
                 sum(1 for e in edges if e.is_support))
    return GuideGraphResult(edges=edges, guide_lookup=guide_lookup)


def build_graph_block(result: GuideGraphResult) -> str:
    """把 GuideGraphResult 格式化为 prompt 注入块.

    输出格式 (示例):
      ⚠️ Guide Conflicts Detected
      1. [pressure] ↔ [reader_signal]: 节奏冲突: 一方建议加速, 另一方建议放缓
         pressure: confidence=0.85 "加速回收伏笔"
         reader_signal: confidence=0.72 "减缓节奏, 给读者喘息空间"
         → 这是真正的创作权衡, 请基于上下文自主判断。
    """
    if not result.conflicts and not result.supports:
        return ""

    lines = []

    if result.conflicts:
        lines.append("## ⚠️ Guide Conflicts Detected (创作权衡, 非错误)")
        for i, edge in enumerate(result.conflicts):
            g_a = result.guide_lookup.get(edge.guide_a)
            g_b = result.guide_lookup.get(edge.guide_b)
            if g_a is None or g_b is None:
                continue
            src_a = g_a.source if hasattr(g_a, "source") else g_a.get("source", "?")
            src_b = g_b.source if hasattr(g_b, "source") else g_b.get("source", "?")
            adv_a = g_a.advice if hasattr(g_a, "advice") else g_a.get("advice", "")
            adv_b = g_b.advice if hasattr(g_b, "advice") else g_b.get("advice", "")
            conf_a = g_a.confidence if hasattr(g_a, "confidence") else g_a.get("confidence", 0.7)
            conf_b = g_b.confidence if hasattr(g_b, "confidence") else g_b.get("confidence", 0.7)

            lines.append(
                f"\n{i + 1}. [{src_a}] ↔ [{src_b}]: {edge.reason}"
            )
            lines.append(f"   [{src_a}] confidence={conf_a:.2f} \"{adv_a}\"")
            lines.append(f"   [{src_b}] confidence={conf_b:.2f} \"{adv_b}\"")
            lines.append("   → 这是真正的创作权衡, 请基于上下文自主判断。")

    if result.supports:
        lines.append("\n## ✅ Guide Supports (协同信号)")
        for i, edge in enumerate(result.supports):
            g_a = result.guide_lookup.get(edge.guide_a)
            if g_a is None:
                continue
            src_a = g_a.source if hasattr(g_a, "source") else g_a.get("source", "?")
            src_b = (result.guide_lookup.get(edge.guide_b) or {}).source if hasattr(
                result.guide_lookup.get(edge.guide_b), "source"
            ) else (result.guide_lookup.get(edge.guide_b) or {}).get("source", "?")
            lines.append(f"{i + 1}. [{src_a}] ⇔ [{src_b}]: {edge.reason}")

    return "\n".join(lines)


def build_graph_block_from_guides(guides: list) -> str:
    """v4.0: 从已标注 conflicts_with/supports 的 Guide 列表直接生成冲突图块.

    不调 analyze(), 复用 collect_guides() 内部已完成的冲突标注.
    Orchestrator 用这个替代 analyze() + build_graph_block(), 消除重复计算.
    """
    guide_map = {}
    for g in guides:
        gid = g.guide_id if hasattr(g, "guide_id") else g.get("guide_id", "")
        if gid:
            guide_map[gid] = g

    # 从 Guide 的 conflicts_with 恢复冲突边
    conflict_pairs: set[tuple[str, str]] = set()
    support_pairs: set[tuple[str, str]] = set()

    for g in guides:
        gid = g.guide_id if hasattr(g, "guide_id") else g.get("guide_id", "")
        cw = g.conflicts_with if hasattr(g, "conflicts_with") else g.get("conflicts_with", [])
        sp = g.supports if hasattr(g, "supports") else g.get("supports", [])
        for other in cw:
            pair = tuple(sorted((gid, other)))
            conflict_pairs.add(pair)
        for other in sp:
            pair = tuple(sorted((gid, other)))
            support_pairs.add(pair)

    has_content = bool(conflict_pairs) or bool(support_pairs)
    if not has_content:
        return ""

    lines = []
    conflict_list = sorted(conflict_pairs)
    support_list = sorted(support_pairs)

    if conflict_list:
        lines.append("## \u26a0\ufe0f Guide Conflicts Detected (\u521b\u4f5c\u6743\u8861, \u975e\u9519\u8bef)")
        for i, (gid_a, gid_b) in enumerate(conflict_list):
            g_a = guide_map.get(gid_a)
            g_b = guide_map.get(gid_b)
            if g_a is None or g_b is None:
                continue
            src_a = g_a.source if hasattr(g_a, "source") else g_a.get("source", "?")
            src_b = g_b.source if hasattr(g_b, "source") else g_b.get("source", "?")
            adv_a = g_a.advice if hasattr(g_a, "advice") else g_a.get("advice", "")
            adv_b = g_b.advice if hasattr(g_b, "advice") else g_b.get("advice", "")
            conf_a = g_a.confidence if hasattr(g_a, "confidence") else g_a.get("confidence", 0.7)
            conf_b = g_b.confidence if hasattr(g_b, "confidence") else g_b.get("confidence", 0.7)
            lines.append(f"\n{i + 1}. [{src_a}] \u2194 [{src_b}]: \u8282\u594f/\u7b56\u7565\u51b2\u7a81, \u8bf7\u57fa\u4e8e\u4e0a\u4e0b\u6587\u5224\u65ad")
            lines.append(f"   [{src_a}] confidence={conf_a:.2f} \"{adv_a}\"")
            lines.append(f"   [{src_b}] confidence={conf_b:.2f} \"{adv_b}\"")
            lines.append("   \u2192 \u8fd9\u662f\u771f\u6b63\u7684\u521b\u4f5c\u6743\u8861, \u8bf7\u57fa\u4e8e\u4e0a\u4e0b\u6587\u81ea\u4e3b\u5224\u65ad\u3002")

    if support_list:
        lines.append("\n## \u2705 Guide Supports (\u534f\u540c\u4fe1\u53f7)")
        for i, (gid_a, gid_b) in enumerate(support_list):
            g_a = guide_map.get(gid_a)
            g_b = guide_map.get(gid_b)
            if g_a is None or g_b is None:
                continue
            src_a = g_a.source if hasattr(g_a, "source") else g_a.get("source", "?")
            src_b = g_b.source if hasattr(g_b, "source") else g_b.get("source", "?")
            lines.append(f"{i + 1}. [{src_a}] \u21d4 [{src_b}]: \u65b9\u5411\u4e00\u81f4")

    return "\n".join(lines)


def collect_guides_with_graph(unit_id: str, project_id: str = "") -> tuple[list, GuideGraphResult]:
    """v4.0: collect_guides() + analyze() 一步到位.

    Returns:
        (guides, graph_result)
    """
    from app.core.types import collect_guides
    guides = collect_guides(unit_id, project_id=project_id)
    graph = analyze(guides)
    return guides, graph
