"""
Character State Guide Service (v3.5.2+)

基于 character_tracker 返回角色状态 Guide.
探测角色异常信号: 状态危机/实力变化/关系演变/角色消失.

设计来源:
- GPT 路线图 v3.5.2: Observe 模块 Characters 页面要"角色状态"
- workbuddy 评审: 用 character_tracker 的 diff + get_all_latest 生成 Guide

v3.5.2 实现: 基于 db 已有数据, 返回限 5 条 Guide.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT, GUIDE_SCOPE_SCENE

_logger = logging.getLogger("NovelWriter.services.character_state")

# 状态风险关键词 → 风险等级
STATE_RISK_PATTERNS: dict[str, float] = {
    "死亡": 0.95, "濒死": 0.90, "昏": 0.85, "重伤": 0.85,
    "垂死": 0.90, "中毒": 0.70, "诅咒": 0.70, "虚弱": 0.50,
    "崩溃": 0.65, "失控": 0.60, "昏迷": 0.85,
}


def _get_unit_info(unit_id: str) -> tuple[str, str, dict, dict]:
    from app.services import story_unit_service_v2 as _unit_svc
    unit = _unit_svc.get(unit_id)
    entry_chars = json.loads(unit.entry_characters) if unit.entry_characters else {}
    exit_chars = json.loads(unit.exit_characters) if unit.exit_characters else {}
    return unit.project_id, unit.pov_character or "", entry_chars, exit_chars


def _assess_state_risk(state_value: str) -> tuple[float, str]:
    if not state_value:
        return 0.0, ""
    for kw, risk in sorted(STATE_RISK_PATTERNS.items(), key=lambda x: -len(x[0])):
        if kw in state_value:
            return risk, kw
    return 0.0, ""


def get_guides(unit_id: str, project_id: str = "") -> list[Guide]:
    guides: list[Guide] = []

    try:
        from app.services import character_tracker as _ct
    except Exception:
        return guides

    try:
        proj_id, pov_char, entry_chars, exit_chars = _get_unit_info(unit_id)
    except Exception:
        return guides

    if project_id:
        proj_id = project_id

    all_latest = {}
    try:
        all_latest = _ct.get_all_latest(proj_id)
    except Exception:
        pass

    # ---- 维度 1: 状态危机检测 ----
    for name, snap in all_latest.items():
        if not snap.state:
            continue
        risk, keyword = _assess_state_risk(snap.state)
        if risk < 0.50:
            continue
        confidence = min(risk + 0.1, 0.90)
        guides.append(Guide(
            source="character_state",
            priority=0.85 if risk >= 0.80 else 0.65,
            confidence=confidence,
            scope=GUIDE_SCOPE_UNIT,
            advice=(
                f"角色 {name} 状态异常: {snap.state}。"
                f"当前 unit 需考虑该角色的状态影响, 避免行动逻辑断层。"
            ),
            reason=f"state 包含风险关键词 '{keyword}', risk={risk:.2f}",
            evidence_ids=[snap.id],
            possible_actions=[
                Action(label="延续状态", description=f"{name} 的状态在本 unit 中合理延续"),
                Action(label="状态转折", description=f"本 unit 触发 {name} 的状态转变" if risk < 0.85 else f"{name} 不可轻描淡写地带过"),
            ],
            context={"character": name, "state": snap.state, "risk": risk, "keyword": keyword},
        ))

    # ---- 维度 2: POV 角色未追踪 ----
    if pov_char and pov_char not in all_latest:
        guides.append(Guide(
            source="character_state",
            priority=0.55,
            confidence=0.70,
            scope=GUIDE_SCOPE_UNIT,
            advice=(
                f"POV 角色 {pov_char} 尚无 tracker 记录。"
                f"建议在 unit 完成后记录其状态, 以便后续追踪。"
            ),
            reason=f"pov_character={pov_char} 不在 character_tracker 中",
            evidence_ids=[],
            possible_actions=[
                Action(label="记录 POV", description=f"本 unit 写完后 record {pov_char} 的状态"),
            ],
            context={"pov_character": pov_char},
        ))

    # ---- 维度 3: 出口角色与 tracker 最新不一致 ----
    if exit_chars:
        for name, exit_snapshot in exit_chars.items():
            if name not in all_latest:
                continue
            snap = all_latest[name]
            # 只检测 state 维度 (其他维度的用户传入格式不一致, 不硬比)
            if isinstance(exit_snapshot, dict) and "state" in exit_snapshot:
                exit_state = str(exit_snapshot.get("state", ""))
                if exit_state and snap.state and exit_state != snap.state:
                    guides.append(Guide(
                        source="character_state",
                        priority=0.55,
                        confidence=0.60,
                        scope=GUIDE_SCOPE_SCENE,
                        advice=(
                            f"角色 {name} 出口状态 ({exit_state}) 与 tracker 最新记录 ({snap.state}) 不一致。"
                            f"请确认哪个是故事的真实状态。"
                        ),
                        reason=f"exit_characters state mismatch: '{exit_state}' vs '{snap.state}'",
                        evidence_ids=[snap.id],
                        possible_actions=[
                            Action(label="同步 tracker", description=f"用 exit_characters 更新 tracker"),
                            Action(label="修正 exit", description=f"exit_characters 以 tracker 为准"),
                        ],
                        context={"character": name, "exit_state": exit_state, "tracker_state": snap.state},
                    ))

    # ---- 维度 4: 实力变化提示 ----
    for name, snap in all_latest.items():
        if not snap.power_level:
            continue
        keywords = ["突破", "提升", "晋级", "进阶", "晋级赛", "渡劫", "瓶颈", "退步", "封印"]
        matched = [kw for kw in keywords if kw in snap.power_level]
        if not matched:
            continue
        guides.append(Guide(
            source="character_state",
            priority=0.60,
            confidence=0.65,
            scope=GUIDE_SCOPE_UNIT,
            advice=(
                f"角色 {name} 实力状态: {snap.power_level}。"
                f"本 unit 中该角色的实力表现需与记录一致。"
            ),
            reason=f"power_level 含关键词 {matched}",
            evidence_ids=[snap.id],
            possible_actions=[
                Action(label="展现实力", description=f"本 unit 让 {name} 展现与境界匹配的能力"),
                Action(label="实力铺垫", description=f"境界变化不立即展露, 但笔触要有暗示"),
            ],
            context={"character": name, "power_level": snap.power_level, "keywords": matched},
        ))

    # 限 5 条
    guides.sort(key=lambda g: -g.priority)
    return guides[:5]
