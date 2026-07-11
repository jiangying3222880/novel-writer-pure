"""
IndexService — 事件驱动索引

当数据变更时自动更新索引，供 Finder 检索。
遵循原则: Index = Cache, 不是 Source of Truth.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.index_service")


def on_unit_created(project_id: str, unit_id: str) -> None:
    """单元创建后更新索引."""
    _update_unit_index(project_id, unit_id)


def on_unit_updated(project_id: str, unit_id: str) -> None:
    """单元更新后刷新索引."""
    _update_unit_index(project_id, unit_id)


def on_unit_deleted(project_id: str, unit_id: str) -> None:
    """单元删除后清理索引."""
    _remove_unit_index(unit_id)


def on_chapter_saved(project_id: str, chapter_id: str) -> None:
    """章节保存后更新索引."""
    _update_chapter_index(project_id, chapter_id)


def rebuild_project_index(project_id: str) -> int:
    """重建项目全量索引."""
    conn = get_conn()
    # 清理旧索引
    conn.execute("DELETE FROM knowledge_index WHERE source = ?", (f"unit:{project_id}",))
    conn.commit()

    # 重建单元索引
    rows = conn.execute(
        "SELECT id, title, synopsis, draft FROM story_units WHERE project_id = ?",
        (project_id,),
    ).fetchall()

    count = 0
    for row in rows:
        _index_text(
            source=f"unit:{project_id}",
            entity_id=row["id"],
            text=f"{row['title']} {row['synopsis'] or ''} {row['draft'] or ''}"[:2000],
        )
        count += 1

    _logger.info("重建项目索引: project=%s, %d 条", project_id[:8], count)
    return count


def _update_unit_index(project_id: str, unit_id: str) -> None:
    """更新单个单元的索引."""
    conn = get_conn()
    row = conn.execute(
        "SELECT title, synopsis, draft FROM story_units WHERE id = ?", (unit_id,)
    ).fetchone()
    if not row:
        return
    text = f"{row['title']} {row['synopsis'] or ''} {row['draft'] or ''}"[:2000]
    _index_text(source=f"unit:{project_id}", entity_id=unit_id, text=text)


def _update_chapter_index(project_id: str, chapter_id: str) -> None:
    """更新单个章节的索引."""
    conn = get_conn()
    row = conn.execute(
        "SELECT title, draft FROM chapters WHERE id = ?", (chapter_id,)
    ).fetchone()
    if not row:
        return
    text = f"{row['title']} {row['draft'] or ''}"[:2000]
    _index_text(source=f"chapter:{project_id}", entity_id=chapter_id, text=text)


def _remove_unit_index(unit_id: str) -> None:
    """移除单元索引."""
    conn = get_conn()
    conn.execute("DELETE FROM knowledge_index WHERE entity_id = ?", (unit_id,))
    conn.commit()


def _index_text(source: str, entity_id: str, text: str) -> None:
    """写入索引 (upsert)."""
    if not text.strip():
        return
    conn = get_conn()
    conn.execute(
        "DELETE FROM knowledge_index WHERE entity_id = ?", (entity_id,)
    )
    conn.execute(
        "INSERT INTO knowledge_index (source, entity_id, content) VALUES (?, ?, ?)",
        (source, entity_id, text),
    )
    conn.commit()
