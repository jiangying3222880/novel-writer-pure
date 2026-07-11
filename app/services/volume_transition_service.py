"""
卷间过渡管理服务

管理卷与卷之间的过渡关系 (migration 049).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.services.volume_transition")


@dataclass
class VolumeTransition:
    """卷间过渡"""
    id: str
    project_id: str
    from_book_id: str
    to_book_id: str
    transition_type: str = "direct"  # direct/cliffhanger/time_jump/parallel
    summary: str = ""
    required_memories: list[str] = field(default_factory=list)
    created_at: str = ""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create(
    project_id: str,
    from_book_id: str,
    to_book_id: str,
    *,
    transition_type: str = "direct",
    summary: str = "",
    required_memories: list[str] | None = None,
) -> VolumeTransition:
    """创建卷间过渡."""
    transition_id = str(uuid.uuid4())
    now = _now()

    with transaction() as conn:
        conn.execute(
            """INSERT INTO volume_transitions
               (id, project_id, from_book_id, to_book_id,
                transition_type, summary, required_memories, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transition_id, project_id, from_book_id, to_book_id,
                transition_type, summary,
                json.dumps(required_memories or [], ensure_ascii=False),
                now,
            ),
        )

    _logger.info("Volume transition created: %s → %s", from_book_id[:8], to_book_id[:8])
    return get(transition_id)


def get(transition_id: str) -> VolumeTransition | None:
    """获取过渡记录."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM volume_transitions WHERE id = ?", (transition_id,)
    ).fetchone()
    if not row:
        return None
    return _row_to_transition(row)


def list_for_project(project_id: str) -> list[VolumeTransition]:
    """列出项目所有过渡."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM volume_transitions WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    return [_row_to_transition(r) for r in rows]


def list_for_book(book_id: str) -> list[VolumeTransition]:
    """列出与某卷相关的过渡."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM volume_transitions WHERE from_book_id = ? OR to_book_id = ?",
        (book_id, book_id),
    ).fetchall()
    return [_row_to_transition(r) for r in rows]


def update(transition_id: str, **fields) -> VolumeTransition | None:
    """更新过渡."""
    allowed = {"transition_type", "summary", "required_memories"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get(transition_id)

    if "required_memories" in updates and isinstance(updates["required_memories"], list):
        updates["required_memories"] = json.dumps(updates["required_memories"], ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [transition_id]

    with transaction() as conn:
        conn.execute(f"UPDATE volume_transitions SET {set_clause} WHERE id = ?", values)

    return get(transition_id)


def delete(transition_id: str) -> bool:
    """删除过渡."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM volume_transitions WHERE id = ?", (transition_id,))
    return cursor.rowcount > 0


def _row_to_transition(row) -> VolumeTransition:
    return VolumeTransition(
        id=row["id"],
        project_id=row["project_id"],
        from_book_id=row["from_book_id"],
        to_book_id=row["to_book_id"],
        transition_type=row["transition_type"] or "direct",
        summary=row["summary"] or "",
        required_memories=json.loads(row["required_memories"] or "[]"),
        created_at=row["created_at"] or "",
    )
