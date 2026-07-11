"""
Entity Index — 统一实体索引

跨模块的实体检索: 角色、地点、物品、事件的统一查询入口。
"""
from __future__ import annotations

import logging
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.entity_index")


def search_entities(
    project_id: str,
    query: str,
    *,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """统一实体检索.

    Args:
        project_id: 项目ID
        query: 搜索关键词
        entity_type: 可选过滤 (character/location/item/event)
        limit: 返回数量

    Returns:
        list[dict]: 匹配的实体列表
    """
    conn = get_conn()
    results = []

    # 搜索角色
    if entity_type is None or entity_type == "character":
        rows = conn.execute(
            """SELECT id, name, role, personality, description
               FROM world_characters
               WHERE project_id = ? AND (name LIKE ? OR personality LIKE ? OR description LIKE ?)
               LIMIT ?""",
            (project_id, f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "type": "character",
                "id": r["id"],
                "name": r["name"],
                "role": r["role"] or "",
                "description": (r["personality"] or "") + " " + (r["description"] or ""),
            })

    # 搜索地点
    if entity_type is None or entity_type == "location":
        rows = conn.execute(
            """SELECT id, name, description
               FROM world_locations
               WHERE project_id = ? AND (name LIKE ? OR description LIKE ?)
               LIMIT ?""",
            (project_id, f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "type": "location",
                "id": r["id"],
                "name": r["name"],
                "description": r["description"] or "",
            })

    # 搜索物品
    if entity_type is None or entity_type == "item":
        rows = conn.execute(
            """SELECT id, name, description
               FROM world_items
               WHERE project_id = ? AND (name LIKE ? OR description LIKE ?)
               LIMIT ?""",
            (project_id, f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "type": "item",
                "id": r["id"],
                "name": r["name"],
                "description": r["description"] or "",
            })

    return results[:limit]


def get_entity(project_id: str, entity_type: str, entity_id: str) -> Optional[dict]:
    """获取单个实体详情."""
    conn = get_conn()

    if entity_type == "character":
        row = conn.execute(
            "SELECT * FROM world_characters WHERE id = ? AND project_id = ?",
            (entity_id, project_id),
        ).fetchone()
        if row:
            return {"type": "character", **dict(row)}

    elif entity_type == "location":
        row = conn.execute(
            "SELECT * FROM world_locations WHERE id = ? AND project_id = ?",
            (entity_id, project_id),
        ).fetchone()
        if row:
            return {"type": "location", **dict(row)}

    elif entity_type == "item":
        row = conn.execute(
            "SELECT * FROM world_items WHERE id = ? AND project_id = ?",
            (entity_id, project_id),
        ).fetchone()
        if row:
            return {"type": "item", **dict(row)}

    return None
