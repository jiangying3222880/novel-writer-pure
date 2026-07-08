"""
卷纲服务 - 支持分卷编排

提供卷纲的CRUD操作和AI生成功能，让用户可以规划每卷的核心内容和目标。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.services.book_outline")


@dataclass
class BookOutline:
    """卷纲数据"""
    id: str
    book_id: str
    project_id: str
    core_theme: str = ""
    emotion_arc: str = ""
    key_events: list[str] = None
    character_arcs: list[dict] = None
    hook_plants: list[str] = None
    hook_payoffs: list[str] = None
    target_word_count: int = 0
    target_unit_count: int = 0
    status: str = "planning"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if self.key_events is None:
            self.key_events = []
        if self.character_arcs is None:
            self.character_arcs = []
        if self.hook_plants is None:
            self.hook_plants = []
        if self.hook_payoffs is None:
            self.hook_payoffs = []


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create(
    book_id: str,
    project_id: str,
    *,
    core_theme: str = "",
    emotion_arc: str = "",
    key_events: list[str] | None = None,
    character_arcs: list[dict] | None = None,
    hook_plants: list[str] | None = None,
    hook_payoffs: list[str] | None = None,
    target_word_count: int = 0,
    target_unit_count: int = 0,
) -> BookOutline:
    """创建卷纲"""
    outline_id = str(uuid.uuid4())
    now = _now()

    with transaction() as conn:
        conn.execute(
            """INSERT INTO book_outlines
               (id, book_id, project_id, core_theme, emotion_arc,
                key_events, character_arcs, hook_plants, hook_payoffs,
                target_word_count, target_unit_count, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                outline_id, book_id, project_id, core_theme, emotion_arc,
                json.dumps(key_events or [], ensure_ascii=False),
                json.dumps(character_arcs or [], ensure_ascii=False),
                json.dumps(hook_plants or [], ensure_ascii=False),
                json.dumps(hook_payoffs or [], ensure_ascii=False),
                target_word_count, target_unit_count, "planning", now, now,
            ),
        )

    _logger.info(f"BookOutline created: {outline_id} for book {book_id}")
    return get(outline_id)


def get(outline_id: str) -> BookOutline | None:
    """获取卷纲"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM book_outlines WHERE id = ?", (outline_id,)
    ).fetchone()

    if not row:
        return None

    return _row_to_outline(row)


def get_by_book(book_id: str) -> BookOutline | None:
    """获取卷的卷纲"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM book_outlines WHERE book_id = ? LIMIT 1", (book_id,)
    ).fetchone()

    if not row:
        return None

    return _row_to_outline(row)


def list_by_project(project_id: str) -> list[BookOutline]:
    """获取项目所有卷纲"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM book_outlines WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()

    return [_row_to_outline(row) for row in rows]


def update(outline_id: str, **fields) -> BookOutline | None:
    """更新卷纲"""
    allowed_fields = {
        "core_theme", "emotion_arc", "key_events", "character_arcs",
        "hook_plants", "hook_payoffs", "target_word_count", "target_unit_count", "status"
    }

    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    if not updates:
        return get(outline_id)

    # 处理JSON字段
    for key in ["key_events", "character_arcs", "hook_plants", "hook_payoffs"]:
        if key in updates and isinstance(updates[key], list):
            updates[key] = json.dumps(updates[key], ensure_ascii=False)

    updates["updated_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [outline_id]

    with transaction() as conn:
        conn.execute(
            f"UPDATE book_outlines SET {set_clause} WHERE id = ?",
            values,
        )

    _logger.info(f"BookOutline updated: {outline_id}")
    return get(outline_id)


def delete(outline_id: str) -> bool:
    """删除卷纲"""
    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM book_outlines WHERE id = ?", (outline_id,)
        )
    return cursor.rowcount > 0


def validate_outline(outline_id: str) -> dict:
    """验证卷纲完整性"""
    outline = get(outline_id)
    if not outline:
        return {"valid": False, "errors": ["卷纲不存在"]}

    errors = []
    if not outline.core_theme:
        errors.append("缺少核心主题")
    if not outline.emotion_arc:
        errors.append("缺少情绪曲线")
    if not outline.key_events:
        errors.append("缺少关键事件")

    return {"valid": len(errors) == 0, "errors": errors}


def generate_outline_from_concept(
    book_id: str,
    project_id: str,
    concept: str,
) -> BookOutline:
    """
    根据概念生成卷纲（调用AI）

    Args:
        book_id: 卷ID
        project_id: 项目ID
        concept: 用户输入的卷概念

    Returns:
        BookOutline: 生成的卷纲
    """
    # TODO: 调用AI引擎生成卷纲
    # 这里先用模板生成，后续接入AI

    outline = create(
        book_id=book_id,
        project_id=project_id,
        core_theme=concept,
        emotion_arc="待AI生成",
        key_events=["待AI生成"],
    )

    _logger.info(f"BookOutline generated from concept: {outline.id}")
    return outline


# --- 内部函数 ---

def _row_to_outline(row) -> BookOutline:
    """将数据库行转换为BookOutline"""
    return BookOutline(
        id=row[0],
        book_id=row[1],
        project_id=row[2],
        core_theme=row[3] or "",
        emotion_arc=row[4] or "",
        key_events=json.loads(row[5]) if row[5] else [],
        character_arcs=json.loads(row[6]) if row[6] else [],
        hook_plants=json.loads(row[7]) if row[7] else [],
        hook_payoffs=json.loads(row[8]) if row[8] else [],
        target_word_count=row[9] or 0,
        target_unit_count=row[10] or 0,
        status=row[11] or "planning",
        created_at=row[12] or "",
        updated_at=row[13] or "",
    )
