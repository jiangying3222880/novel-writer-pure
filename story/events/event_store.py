"""
EventStore — 事件持久化层

独立于 unit_event_service 的 append-only 事件存储。
支持按 unit_id 查询、时间范围过滤、事件回放。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.story.event_store")


@dataclass
class StoredEvent:
    """已存储的事件."""
    id: str
    event_type: str
    entity_name: str = ""
    unit_id: str = ""
    project_id: str = ""
    old_value: str = ""
    new_value: str = ""
    field_name: str = ""
    description: str = ""
    step_no: int = 0
    created_at: str = ""


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append(
    event_type: str,
    *,
    entity_name: str = "",
    unit_id: str = "",
    project_id: str = "",
    old_value: str = "",
    new_value: str = "",
    field_name: str = "",
    description: str = "",
    step_no: int = 0,
) -> StoredEvent:
    """追加事件到存储."""
    event_id = _new_id()
    now = _now()

    with transaction() as conn:
        conn.execute(
            """INSERT INTO story_events
               (id, event_type, entity_name, unit_id, project_id,
                old_value, new_value, field_name, description, step_no, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, event_type, entity_name, unit_id, project_id,
             old_value, new_value, field_name, description, step_no, now),
        )

    return StoredEvent(
        id=event_id, event_type=event_type, entity_name=entity_name,
        unit_id=unit_id, project_id=project_id,
        old_value=old_value, new_value=new_value,
        field_name=field_name, description=description,
        step_no=step_no, created_at=now,
    )


def list_for_unit(unit_id: str, *, limit: int = 100) -> list[StoredEvent]:
    """按 unit_id 查询事件."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM story_events WHERE unit_id = ? ORDER BY step_no ASC LIMIT ?",
        (unit_id, limit),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def list_for_project(project_id: str, *, limit: int = 500) -> list[StoredEvent]:
    """按 project_id 查询事件."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM story_events WHERE project_id = ? ORDER BY created_at ASC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def clear(unit_id: str) -> int:
    """清除某 unit 的所有事件."""
    with transaction() as conn:
        cursor = conn.execute("DELETE FROM story_events WHERE unit_id = ?", (unit_id,))
    return cursor.rowcount


def _row_to_event(row) -> StoredEvent:
    return StoredEvent(
        id=row["id"],
        event_type=row["event_type"],
        entity_name=row["entity_name"] or "",
        unit_id=row["unit_id"] or "",
        project_id=row["project_id"] or "",
        old_value=row["old_value"] or "",
        new_value=row["new_value"] or "",
        field_name=row["field_name"] or "",
        description=row["description"] or "",
        step_no=row["step_no"] or 0,
        created_at=row["created_at"] or "",
    )
