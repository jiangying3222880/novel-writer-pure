"""
Character Arc Service — 角色弧线服务

从 book_outlines.character_arcs 激活角色成长弧追踪。

数据来源: book_outlines.character_arcs (JSON)
接入方式: collect_guides() → get_guides()
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.character_arc")


# ============================================================
# 数据模型
# ============================================================

def _get_arcs_for_project(project_id: str) -> list[dict]:
    """获取项目所有卷纲的 character_arcs, 合并为扁平列表."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT character_arcs FROM book_outlines WHERE project_id = ?",
        (project_id,),
    ).fetchall()

    all_arcs = []
    for row in rows:
        raw = row[0]
        if raw:
            try:
                arcs = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(arcs, list):
                    all_arcs.extend(arcs)
            except (json.JSONDecodeError, TypeError):
                pass
    return all_arcs


def get_arc_expectation(
    project_id: str,
    character_name: str,
    current_chapter_no: int,
) -> Optional[dict]:
    """获取角色在当前章节的预期弧线阶段.

    character_arcs JSON 格式约定:
    [
        {
            "character": "张无忌",
            "stages": [
                {"chapter_range": [1, 10], "stage": "犹豫", "milestone": "学习九阳神功"},
                {"chapter_range": [11, 20], "stage": "成长", "milestone": "六大派围攻光明顶"},
                {"chapter_range": [21, 30], "stage": "决断", "milestone": "决战光明顶"}
            ]
        }
    ]

    返回: {"stage": "犹豫", "milestone": "...", "chapter_range": [1, 10]} 或 None
    """
    all_arcs = _get_arcs_for_project(project_id)

    for char_arc in all_arcs:
        name = char_arc.get("character", "")
        if name != character_name:
            continue

        stages = char_arc.get("stages", [])
        for stage in stages:
            ch_range = stage.get("chapter_range", [0, 0])
            if len(ch_range) == 2 and ch_range[0] <= current_chapter_no <= ch_range[1]:
                return {
                    "stage": stage.get("stage", ""),
                    "milestone": stage.get("milestone", ""),
                    "chapter_range": ch_range,
                }
    return None


# ============================================================
# Guide 输出
# ============================================================

# 阶段情绪关键词 (启发式匹配)
_STAGE_KEYWORDS: dict[str, list[str]] = {
    "犹豫": ["犹豫", "迟疑", "不安", "害怕", "退缩", "迷茫"],
    "压抑": ["压抑", "隐忍", "沉默", "忍耐", "低落"],
    "成长": ["突破", "领悟", "进步", "提升", "变强"],
    "决断": ["决断", "果断", "坚定", "自信", "霸气"],
    "低谷": ["失败", "受伤", "绝望", "崩溃", "跌落"],
    "爆发": ["爆发", "怒吼", "爆发", "觉醒", "蜕变"],
}


def _heuristic_check(expected_stage: str, text: str) -> dict | None:
    """启发式检测: 正文是否偏离预期阶段.

    返回偏离信息 dict 或 None (无偏离).
    """
    if not expected_stage or not text:
        return None

    keywords = _STAGE_KEYWORDS.get(expected_stage, [])
    if not keywords:
        return None

    # 统计匹配到的关键词数
    matched = [kw for kw in keywords if kw in text]
    match_ratio = len(matched) / len(keywords) if keywords else 0

    # 如果正文完全不包含预期阶段的关键词, 可能偏离
    # 但这是一个软信号, 不是硬判断 — 所以 confidence 设低
    if match_ratio < 0.1 and len(text) > 200:
        return {
            "deviated": True,
            "confidence": 0.4,
            "expected_stage": expected_stage,
            "matched_keywords": matched,
            "warning": (
                f"角色弧线偏离预警：当前阶段应为【{expected_stage}】，"
                f"但正文未体现该阶段特征。建议检查角色表现是否符合大纲预期。"
            ),
        }
    return None


def get_guides(unit_id: str, project_id: str = "") -> list:
    """collect_guides() 接入点: 为当前 unit 生成角色弧线 Guide."""
    from app.core.types import Guide

    if not project_id:
        return []

    # 获取当前 unit 的章号
    from app.services import story_unit_service_v2 as _unit_svc
    try:
        unit = _unit_svc.get(unit_id)
    except Exception:
        return []

    # 用 unit_no 作为章节号的近似 (更精确的映射需要 unit → chapter 映射)
    current_chapter_no = unit.unit_no

    # 获取当前 unit 涉及的角色 (从 entry_characters 或 draft 中提取)
    # 这里用 entry_characters 字段 (如果有的话)
    characters = []
    if hasattr(unit, "entry_characters") and unit.entry_characters:
        try:
            characters = json.loads(unit.entry_characters) if isinstance(unit.entry_characters, str) else unit.entry_characters
        except (json.JSONDecodeError, TypeError):
            pass

    if not characters:
        return []

    guides = []
    for char_name in characters:
        expectation = get_arc_expectation(project_id, char_name, current_chapter_no)
        if not expectation:
            continue

        # 生成 Guide: 告知 Writer 当前角色应处于什么阶段
        stage = expectation["stage"]
        milestone = expectation.get("milestone", "")

        advice = f"角色【{char_name}】当前应处于「{stage}」阶段"
        if milestone:
            advice += f"，核心事件：{milestone}"

        guides.append(Guide(
            source="character_arc",
            priority=0.6,
            confidence=0.7,
            scope="Unit",
            advice=advice,
            reason=f"基于大纲预设的角色弧线，第{current_chapter_no}章该角色应处于{stage}阶段",
            evidence_ids=[f"arc:{char_name}:{current_chapter_no}"],
        ))

    return guides
