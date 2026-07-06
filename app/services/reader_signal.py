"""
Reader Signal Service（v3.5.2+）

基于追读率/弃读率/读后行为返回 Reader Guide.

设计来源:
- GPT 路线图 v3.5.2: "Reader 返回 Guide (这里可能弃读)"
- workbuddy 评审: 不要用硬规则, 提供建议

数据来源:
- 追读率 (retention): 外部传入 (UI 或第三方平台)
- narrative_pressures 表: 间接反映读者疲劳度
- chapter_critiques 表: 评后落点 (低分章节 = 弃读风险)

v3.5.2 暂不实现实时追踪, 基于已有静态指标生成 Guide.
"""
from __future__ import annotations
import logging
from typing import Optional

_logger = logging.getLogger("NovelWriter.services.reader_signal")


def get_guides(unit_id: str, project_id: str = "", *, retention: Optional[float] = None) -> list:
    """返回读者行为相关的 Guide 列表.

    Args:
        unit_id: 当前 unit
        project_id: 项目 ID
        retention: 外部传入的追读率 (0-1), 如果 None 则从 narrative_pressures 推断
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

    # ---- 维度 1: 外部追读率 ----
    if retention is not None:
        if retention < 0.30:
            guides.append(Guide(
                source="reader",
                priority=0.9,
                confidence=0.9,
                scope=GUIDE_SCOPE_UNIT,
                advice=(
                    f"读者追读率仅 {retention:.0%}, 进入危险区 (<30%)。"
                    f"建议本 unit 制造情感冲击或大反转, 避免读者流失。"
                ),
                reason=f"外部传入 retention={retention:.4f} < 0.30",
                evidence_ids=[f"retention:{project_id}"],
                possible_actions=[
                    Action(label="立即转折", description="本 unit 加入重大反转或情感高潮"),
                    Action(label="角色生死", description="让核心角色面临命运抉择"),
                    Action(label="爆点", description="兑现一个长期钩子, 给读者爽感"),
                ],
                context={"retention": retention, "zone": "danger"},
            ))
        elif retention < 0.50:
            guides.append(Guide(
                source="reader",
                priority=0.65,
                confidence=0.8,
                scope=GUIDE_SCOPE_UNIT,
                advice=(
                    f"读者追读率 {retention:.0%} (30-50% 区间)。"
                    f"建议适度增加冲突密度, 避免平铺直叙。"
                ),
                reason=f"外部传入 retention={retention:.4f} in [0.30, 0.50)",
                evidence_ids=[f"retention:{project_id}"],
                possible_actions=[
                    Action(label="加冲突", description="本 unit 增加至少 1 个新冲突"),
                    Action(label="加悬念", description="结尾留钩子, 引导下章追读"),
                ],
                context={"retention": retention, "zone": "warning"},
            ))
        elif retention >= 0.70:
            guides.append(Guide(
                source="reader",
                priority=0.3,
                confidence=0.85,
                scope=GUIDE_SCOPE_UNIT,
                advice=(
                    f"读者追读率 {retention:.0%} (>=70%) 健康区。"
                    f"读者已被吸引, 建议保持当前节奏。"
                ),
                reason=f"外部传入 retention={retention:.4f} >= 0.70",
                evidence_ids=[f"retention:{project_id}"],
                possible_actions=[
                    Action(label="维持节奏", description="保持当前风格"),
                    Action(label="可深化", description="趁热深化世界观/人物关系"),
                ],
                context={"retention": retention, "zone": "healthy"},
            ))

    # ---- 维度 2: 间接推断 (基于 narrative_pressures trend) ----
    try:
        from app.services import pressure as _pressure
        trend = _pressure.get_trend(project_id, last_n=5)
        if len(trend) >= 5:
            # 计算最近 trend 中 green zone 占比
            green_count = sum(1 for p in trend if p.zone == "green")
            green_ratio = green_count / len(trend)
            if green_ratio >= 0.8:
                guides.append(Guide(
                    source="reader",
                    priority=0.45,
                    confidence=0.6,  # 间接推断, 置信度低
                    scope=GUIDE_SCOPE_UNIT,
                    advice=(
                        f"最近 {len(trend)} 个 unit 压力分布: {green_count}/{len(trend)} green。"
                        f"读者可能进入审美疲劳, 建议适当加入紧张元素。"
                    ),
                    reason=f"trend green ratio={green_ratio:.2f} >= 0.80",
                    evidence_ids=[p.id for p in trend if hasattr(p, "id") and p.zone == "green"][:5],
                    possible_actions=[
                        Action(label="加张力", description="下一个 unit 加入紧张事件"),
                    ],
                    context={"green_ratio": green_ratio, "trend_size": len(trend)},
                ))
    except Exception:
        pass

    return guides