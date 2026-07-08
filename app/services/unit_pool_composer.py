"""
单元组合器 - 根据卷纲自动选择并排列单元

从单元池中检索合适的单元，组合生成故事骨架。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.db._impl import get_conn
from app.services import unit_pool_service

_logger = logging.getLogger("NovelWriter.services.unit_pool_composer")


# 节奏类型常量
RHYTHM_TYPES = (
    "opening",      # 开篇
    "setup",        # 铺垫
    "rising",       # 升温
    "climax",       # 高潮
    "falling",      # 下降
    "transition",   # 转场
    "revelation",   # 揭秘
    "conflict",     # 冲突
    "resolution",   # 解决
    "ending",       # 结尾
    "other",        # 其他
)


@dataclass
class ComposedUnit:
    """组合后的单元"""
    pool_unit_id: str  # 源单元池ID
    title: str
    description: str
    rhythm_type: str
    order: int  # 在骨架中的顺序
    adaptation_notes: str = ""  # 适配说明


@dataclass
class StorySkeleton:
    """故事骨架"""
    units: list[ComposedUnit] = field(default_factory=list)
    total_estimated_words: int = 0
    rhythm_distribution: dict[str, int] = field(default_factory=dict)


def search_by_rhythm(
    genre: str | None = None,
    rhythm_type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    按节奏类型检索单元

    Args:
        genre: 题材过滤
        rhythm_type: 节奏类型
        tags: 标签过滤
        limit: 返回数量限制

    Returns:
        list[dict]: 匹配的单元列表
    """
    conn = get_conn()

    query = "SELECT * FROM unit_pool WHERE 1=1"
    params: list = []

    if genre:
        query += " AND genre = ?"
        params.append(genre)

    if rhythm_type:
        query += " AND rhythm_type = ?"
        params.append(rhythm_type)

    if tags:
        for tag in tags:
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")

    query += " ORDER BY quality_score DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [unit_pool_service._row_to_unit(row).__dict__ for row in rows]


def search_by_dependency(hook_id: str) -> list[dict]:
    """
    按伏笔依赖检索单元

    Args:
        hook_id: 伏笔ID

    Returns:
        list[dict]: 依赖该伏笔的单元列表
    """
    import json
    conn = get_conn()

    rows = conn.execute("SELECT * FROM unit_pool").fetchall()
    results = []

    for row in rows:
        unit = unit_pool_service._row_to_unit(row)
        provide_hooks = json.loads(unit.provide_hooks) if unit.provide_hooks else []
        if hook_id in provide_hooks:
            results.append(unit.__dict__)

    return results


def recommend_for_outline(
    book_id: str,
    project_id: str,
    outline: dict | None = None,
    target_unit_count: int = 10,
) -> list[dict]:
    """
    根据卷纲推荐单元

    Args:
        book_id: 卷ID
        project_id: 项目ID
        outline: 卷纲内容（core_theme, emotion_arc, key_events）
        target_unit_count: 目标单元数

    Returns:
        list[dict]: 推荐的单元列表
    """
    # 1. 获取项目题材
    from app.services import project_service
    project = project_service.get(project_id)
    genre = project.get("genre", "")

    # 2. 根据情绪曲线规划节奏分布
    rhythm_plan = _plan_rhythm_distribution(target_unit_count)

    # 3. 为每个节奏类型检索合适的单元
    recommended = []
    for rhythm, count in rhythm_plan.items():
        units = search_by_rhythm(genre=genre, rhythm_type=rhythm, limit=count)
        recommended.extend(units[:count])

    # 4. 如果数量不足，补充通用单元
    if len(recommended) < target_unit_count:
        remaining = target_unit_count - len(recommended)
        general_units = search_by_rhythm(genre=genre, limit=remaining)
        recommended.extend(general_units[:remaining])

    return recommended[:target_unit_count]


def compose_skeleton(
    book_id: str,
    unit_ids: list[str],
) -> StorySkeleton:
    """
    将选中单元组合成故事骨架

    Args:
        book_id: 卷ID
        unit_ids: 选中的单元ID列表

    Returns:
        StorySkeleton: 故事骨架
    """
    skeleton = StorySkeleton()

    for i, unit_id in enumerate(unit_ids):
        unit = unit_pool_service.get(unit_id)
        if not unit:
            continue

        composed = ComposedUnit(
            pool_unit_id=unit_id,
            title=unit.title,
            description=unit.description or "",
            rhythm_type=getattr(unit, 'rhythm_type', 'other'),
            order=i + 1,
        )
        skeleton.units.append(composed)
        skeleton.total_estimated_words += getattr(unit, 'target_words', 2000)

    # 统计节奏分布
    for unit in skeleton.units:
        rhythm = unit.rhythm_type
        skeleton.rhythm_distribution[rhythm] = skeleton.rhythm_distribution.get(rhythm, 0) + 1

    _logger.info(f"Composed skeleton: {len(skeleton.units)} units, {skeleton.total_estimated_words} words")
    return skeleton


def clone_skeleton_to_project(
    skeleton: StorySkeleton,
    project_id: str,
    book_id: str,
) -> list[str]:
    """
    将骨架克隆到项目

    Args:
        skeleton: 故事骨架
        project_id: 项目ID
        book_id: 卷ID

    Returns:
        list[str]: 创建的单元ID列表
    """
    from app.services import story_unit_service_v2

    created_ids = []

    for unit in skeleton.units:
        # 从单元池获取原始数据
        pool_unit = unit_pool_service.get(unit.pool_unit_id)
        if not pool_unit:
            continue

        # 在项目中创建单元
        new_unit = story_unit_service_v2.create(
            project_id=project_id,
            title=unit.title,
            book_id=book_id,
            unit_type=pool_unit.unit_type if hasattr(pool_unit, 'unit_type') else 'other',
            synopsis=unit.description,
        )
        created_ids.append(new_unit.id)

    _logger.info(f"Cloned skeleton to project: {len(created_ids)} units")
    return created_ids


# --- 内部函数 ---

def _plan_rhythm_distribution(target_count: int) -> dict[str, int]:
    """
    根据目标单元数规划节奏分布

    经典三幕式结构：
    - 第一幕（铺垫）：25%
    - 第二幕（发展）：50%
    - 第三幕（高潮+结局）：25%
    """
    if target_count <= 3:
        return {"setup": 1, "climax": 1, "resolution": 1}

    setup = max(1, target_count // 4)
    climax = max(1, target_count // 4)
    resolution = max(1, target_count // 4)
    rising = target_count - setup - climax - resolution

    return {
        "setup": setup,
        "rising": rising,
        "climax": climax,
        "resolution": resolution,
    }
