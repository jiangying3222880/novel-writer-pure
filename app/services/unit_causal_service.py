"""
Unit Causal Service — 因果图服务

管理 unit_causal_edges (因果边) 和 unit_causal_groups (剧情线)。
"""
from __future__ import annotations
import json
import logging
import uuid
from typing import Optional
from datetime import datetime

_logger = logging.getLogger("NovelWriter.services.unit_causal_service")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ============================================================
# 因果边 (Causal Edges)
# ============================================================

def create_edge(
    project_id: str,
    from_unit_id: str,
    to_unit_id: str,
    edge_type: str = "direct",
    description: str = "",
    strength: float = 0.5,
) -> dict:
    """创建因果边."""
    from app.db._impl import get_conn
    db = get_conn()
    edge_id = _new_id()
    now = _now()

    db.execute(
        """INSERT INTO unit_causal_edges
           (id, project_id, from_unit_id, to_unit_id, edge_type, description, strength, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (edge_id, project_id, from_unit_id, to_unit_id, edge_type, description, strength, now),
    )

    _logger.info("Created causal edge: %s -> %s (%s)", from_unit_id[:8], to_unit_id[:8], edge_type)
    return {"id": edge_id, "from_unit_id": from_unit_id, "to_unit_id": to_unit_id, "edge_type": edge_type}


def get_edges_for_unit(unit_id: str) -> list[dict]:
    """获取与某单元相关的所有因果边."""
    from app.db._impl import get_conn
    db = get_conn()
    rows = db.execute(
        "SELECT * FROM unit_causal_edges WHERE from_unit_id = ? OR to_unit_id = ? ORDER BY created_at",
        (unit_id, unit_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_edges_for_project(project_id: str) -> list[dict]:
    """获取项目的所有因果边."""
    from app.db._impl import get_conn
    db = get_conn()
    rows = db.execute(
        "SELECT * FROM unit_causal_edges WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_edge(edge_id: str) -> bool:
    """删除因果边."""
    from app.db._impl import get_conn
    db = get_conn()
    cursor = db.execute("DELETE FROM unit_causal_edges WHERE id = ?", (edge_id,))
    return cursor.rowcount > 0


def update_edge(edge_id: str, **kwargs) -> bool:
    """更新因果边."""
    from app.db._impl import get_conn
    db = get_conn()
    allowed = {"edge_type", "description", "strength"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [edge_id]
    cursor = db.execute(f"UPDATE unit_causal_edges SET {set_clause} WHERE id = ?", values)
    return cursor.rowcount > 0


# ============================================================
# 剧情线 (Causal Groups)
# ============================================================

def create_group(
    project_id: str,
    name: str,
    color: str = "#89b4fa",
    description: str = "",
) -> dict:
    """创建剧情线."""
    from app.db._impl import get_conn
    db = get_conn()
    group_id = _new_id()

    # 获取当前最大 sort_order
    row = db.execute(
        "SELECT COALESCE(MAX(sort_order), 0) FROM unit_causal_groups WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    next_order = (row[0] or 0) + 1

    db.execute(
        """INSERT INTO unit_causal_groups
           (id, project_id, name, color, description, unit_ids, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (group_id, project_id, name, color, description, "[]", next_order),
    )

    _logger.info("Created causal group: %s (%s)", name, group_id[:8])
    return {"id": group_id, "name": name, "color": color}


def get_groups_for_project(project_id: str) -> list[dict]:
    """获取项目的所有剧情线."""
    from app.db._impl import get_conn
    db = get_conn()
    rows = db.execute(
        "SELECT * FROM unit_causal_groups WHERE project_id = ? ORDER BY sort_order",
        (project_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["unit_ids"] = json.loads(d.get("unit_ids", "[]"))
        result.append(d)
    return result


def add_unit_to_group(group_id: str, unit_id: str) -> bool:
    """将单元添加到剧情线."""
    from app.db._impl import get_conn
    db = get_conn()
    row = db.execute("SELECT unit_ids FROM unit_causal_groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        return False
    ids = json.loads(row["unit_ids"] or "[]")
    if unit_id not in ids:
        ids.append(unit_id)
        db.execute("UPDATE unit_causal_groups SET unit_ids = ? WHERE id = ?", (json.dumps(ids), group_id))
    return True


def remove_unit_from_group(group_id: str, unit_id: str) -> bool:
    """从剧情线移除单元."""
    from app.db._impl import get_conn
    db = get_conn()
    row = db.execute("SELECT unit_ids FROM unit_causal_groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        return False
    ids = json.loads(row["unit_ids"] or "[]")
    if unit_id in ids:
        ids.remove(unit_id)
        db.execute("UPDATE unit_causal_groups SET unit_ids = ? WHERE id = ?", (json.dumps(ids), group_id))
    return True


def delete_group(group_id: str) -> bool:
    """删除剧情线."""
    from app.db._impl import get_conn
    db = get_conn()
    cursor = db.execute("DELETE FROM unit_causal_groups WHERE id = ?", (group_id,))
    return cursor.rowcount > 0
