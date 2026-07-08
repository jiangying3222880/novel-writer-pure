"""
Capability定义与管理

提供知识库按能力维度的索引和检索功能。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.knowledge.capability")


@dataclass
class Capability:
    """Capability定义"""
    id: str
    name: str
    display_name: str
    description: str = ""
    applicable_agents: list[str] = None

    def __post_init__(self):
        if self.applicable_agents is None:
            self.applicable_agents = []


# 预定义Capability常量
NARRATIVE = "narrative"
DIALOGUE = "dialogue"
CHARACTER = "character"
PLOT = "plot"
EMOTION = "emotion"
WORLDBUILDING = "worldbuilding"
LOGIC = "logic"
LANGUAGE = "language"
HISTORY = "history"
LEGAL = "legal"
MEDICAL = "medical"

ALL_CAPABILITIES = (
    NARRATIVE, DIALOGUE, CHARACTER, PLOT, EMOTION,
    WORLDBUILDING, LOGIC, LANGUAGE, HISTORY, LEGAL, MEDICAL,
)

# Agent与Capability的默认映射
AGENT_CAPABILITY_MAP = {
    "writer": [NARRATIVE, DIALOGUE, LANGUAGE, EMOTION],
    "planner": [NARRATIVE, PLOT, WORLDBUILDING],
    "critic": [NARRATIVE, CHARACTER, LOGIC],
    "editor": [LANGUAGE, NARRATIVE],
}


def get_all() -> list[Capability]:
    """获取所有Capability"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM knowledge_capabilities ORDER BY name"
    ).fetchall()

    return [_row_to_capability(row) for row in rows]


def get(capability_id: str) -> Capability | None:
    """获取单个Capability"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM knowledge_capabilities WHERE id = ?", (capability_id,)
    ).fetchone()

    return _row_to_capability(row) if row else None


def get_by_name(name: str) -> Capability | None:
    """按名称获取Capability"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM knowledge_capabilities WHERE name = ?", (name,)
    ).fetchone()

    return _row_to_capability(row) if row else None


def get_for_agent(agent_role: str) -> list[Capability]:
    """获取Agent适用的Capability"""
    cap_names = AGENT_CAPABILITY_MAP.get(agent_role, [])
    capabilities = []

    for name in cap_names:
        cap = get_by_name(name)
        if cap:
            capabilities.append(cap)

    return capabilities


def assign_to_doc(doc_id: str, capability_names: list[str]) -> None:
    """
    为知识文档分配Capability

    Args:
        doc_id: 文档ID
        capability_names: Capability名称列表
    """
    with transaction() as conn:
        # 先删除旧关联
        conn.execute(
            "DELETE FROM knowledge_doc_capabilities WHERE doc_id = ?",
            (doc_id,),
        )

        # 添加新关联
        for name in capability_names:
            cap = get_by_name(name)
            if cap:
                conn.execute(
                    "INSERT INTO knowledge_doc_capabilities (doc_id, capability_id) VALUES (?, ?)",
                    (doc_id, cap.id),
                )

    _logger.info(f"Assigned capabilities to doc {doc_id}: {capability_names}")


def get_capabilities_for_doc(doc_id: str) -> list[Capability]:
    """获取文档的Capability列表"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT c.* FROM knowledge_capabilities c
           JOIN knowledge_doc_capabilities dc ON c.id = dc.capability_id
           WHERE dc.doc_id = ?""",
        (doc_id,),
    ).fetchall()

    return [_row_to_capability(row) for row in rows]


def search_by_capability(
    capability_names: list[str],
    genre: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    按Capability检索知识文档

    Args:
        capability_names: Capability名称列表
        genre: 题材过滤
        limit: 返回数量限制

    Returns:
        list[dict]: 匹配的文档列表
    """
    conn = get_conn()

    # 获取Capability IDs
    cap_ids = []
    for name in capability_names:
        cap = get_by_name(name)
        if cap:
            cap_ids.append(cap.id)

    if not cap_ids:
        return []

    # 检索有这些Capability的文档
    placeholders = ",".join("?" * len(cap_ids))
    query = f"""
        SELECT DISTINCT d.* FROM knowledge_entries d
        JOIN knowledge_doc_capabilities dc ON d.id = dc.doc_id
        WHERE dc.capability_id IN ({placeholders})
    """
    params: list = list(cap_ids)

    if genre:
        query += " AND d.genre = ?"
        params.append(genre)

    query += " ORDER BY d.priority DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# --- 内部函数 ---

def _row_to_capability(row) -> Capability:
    """将数据库行转换为Capability"""
    return Capability(
        id=row[0],
        name=row[1],
        display_name=row[2],
        description=row[3] or "",
        applicable_agents=json.loads(row[4]) if row[4] else [],
    )
