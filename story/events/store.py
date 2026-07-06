"""
EventStore — 事件持久化层

Append-only 存储，支持按 unit_id 查询和时间范围过滤。
"""
from __future__ import annotations
import logging
from typing import Optional
from story.events.types import StoryEvent

_logger = logging.getLogger("NovelWriter.story.event_store")


class EventStore:
    """事件存储接口 + SQLite 实现."""

    def __init__(self, db_conn=None):
        self._db = db_conn

    def _get_db(self):
        if self._db is not None:
            return self._db
        try:
            from app.db._impl import get_conn
            return get_conn()
        except Exception:
            return None

    def append(self, event: StoryEvent) -> None:
        """追加事件到存储."""
        db = self._get_db()
        if db is None:
            _logger.debug("EventStore: no DB, event %s not persisted", event.id)
            return
        try:
            db.execute(
                """INSERT INTO story_events
                   (id, event_type, entity_name, unit_id, project_id,
                    old_value, new_value, field_name, description,
                    step_no, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    event.id,
                    event.type,
                    event.payload.get("entity_name", ""),
                    event.unit_id,
                    event.project_id,
                    str(event.payload.get("old_value", "")),
                    str(event.payload.get("new_value", "")),
                    event.payload.get("field_name", ""),
                    event.payload.get("description", ""),
                    event.payload.get("step_no", 0),
                ),
            )
        except Exception as e:
            _logger.warning("EventStore.append failed: %s", e)

    def get_events(self, unit_id: str) -> list[StoryEvent]:
        """获取指定 unit 的所有事件."""
        db = self._get_db()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT * FROM story_events WHERE unit_id = ? ORDER BY created_at",
                (unit_id,),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        except Exception as e:
            _logger.warning("EventStore.get_events failed: %s", e)
            return []

    def get_events_since(self, unit_id: str, since_ts: float) -> list[StoryEvent]:
        """获取指定 unit 在某时间戳之后的事件."""
        db = self._get_db()
        if db is None:
            return []
        try:
            rows = db.execute(
                """SELECT * FROM story_events
                   WHERE unit_id = ? AND created_at > datetime(?, 'unixepoch')
                   ORDER BY created_at""",
                (unit_id, since_ts),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        except Exception as e:
            _logger.warning("EventStore.get_events_since failed: %s", e)
            return []

    def clear(self, unit_id: str) -> None:
        """清除指定 unit 的所有事件."""
        db = self._get_db()
        if db is None:
            return
        try:
            db.execute("DELETE FROM story_events WHERE unit_id = ?", (unit_id,))
        except Exception as e:
            _logger.warning("EventStore.clear failed: %s", e)

    def count(self, unit_id: str) -> int:
        """统计指定 unit 的事件数量."""
        db = self._get_db()
        if db is None:
            return 0
        try:
            row = db.execute(
                "SELECT COUNT(*) FROM story_events WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    @staticmethod
    def _row_to_event(row) -> StoryEvent:
        """将数据库行转换为 StoryEvent."""
        return StoryEvent(
            id=row["id"] if "id" in row.keys() else "",
            type=row["event_type"] if "event_type" in row.keys() else "",
            payload={
                "entity_name": row["entity_name"] if "entity_name" in row.keys() else "",
                "field_name": row["field_name"] if "field_name" in row.keys() else "",
                "old_value": row["old_value"] if "old_value" in row.keys() else "",
                "new_value": row["new_value"] if "new_value" in row.keys() else "",
                "description": row["description"] if "description" in row.keys() else "",
                "step_no": row["step_no"] if "step_no" in row.keys() else 0,
            },
            unit_id=row["unit_id"] if "unit_id" in row.keys() else "",
            project_id=row["project_id"] if "project_id" in row.keys() else "",
        )


# 全局单例
_store: EventStore | None = None


def get_event_store() -> EventStore:
    global _store
    if _store is None:
        _store = EventStore()
    return _store
