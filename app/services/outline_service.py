"""
H1 ai_outline_gen 配套: 章节大纲 (3 版本) 服务层.

数据模型 (chapter_outlines 表, 见 migration 029):
  - chapter_id + version (A/B/C) -> outline / core_events / emotion_arc / word_target
  - 1 章最多 3 个版本; 用户可标记某个版本为 "selected"

公开 API:
  - OutlineService.save_outline(chapter_id, version, outline, ...)
  - OutlineService.list_outlines(chapter_id) -> list[dict]
  - OutlineService.get_outline(chapter_id, version) -> dict | None
  - OutlineService.select_version(chapter_id, version) -> None
  - OutlineService.get_selected(chapter_id) -> dict | None
  - OutlineService.delete_outline(chapter_id, version) -> None
  - OutlineService.delete_all_for_chapter(chapter_id) -> None
  - OutlineService.diff_versions(chapter_id) -> dict  # A vs B vs C 对比

错误:
  - 重复 (chapter_id, version) -> IntegrityError
  - 版本必须 A/B/C
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from app.db import _impl as _db_conn

log = logging.getLogger(__name__)

VALID_VERSIONS = ("A", "B", "C")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class OutlineServiceError(Exception):
    pass


# --------------------------------------------------------------------- #
# 写
# --------------------------------------------------------------------- #

def save_outline(
    chapter_id: str,
    version: str,
    outline: str,
    core_events: Optional[str] = None,
    emotion_arc: Optional[str] = None,
    word_target: Optional[int] = None,
) -> dict:
    """保存一章的一个版本大纲. 若已存在, 覆盖 (upsert)."""
    if version not in VALID_VERSIONS:
        raise OutlineServiceError(f"version 必须是 A/B/C, 收到 {version!r}")
    if not outline or not outline.strip():
        raise OutlineServiceError("outline 内容不能为空")
    with _db_conn.transaction() as db:
        existing = db.execute(
            "SELECT id FROM chapter_outlines WHERE chapter_id=? AND version=?",
            (chapter_id, version),
        ).fetchone()
        now = _now()
        if existing:
            db.execute(
                """UPDATE chapter_outlines
                   SET outline=?, core_events=?, emotion_arc=?, word_target=?
                   WHERE chapter_id=? AND version=?""",
                (outline.strip(), core_events, emotion_arc, word_target,
                 chapter_id, version),
            )
            oid = existing["id"]
        else:
            oid = str(uuid.uuid4())
            db.execute(
                """INSERT INTO chapter_outlines
                   (id, chapter_id, version, outline, core_events,
                    emotion_arc, word_target, selected, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (oid, chapter_id, version, outline.strip(),
                 core_events, emotion_arc, word_target, now),
            )
    return get_outline(chapter_id, version)  # type: ignore[return-value]


def select_version(chapter_id: str, version: str) -> dict:
    """标记某版本为 selected (同时清掉同章其他版本的 selected)."""
    if version not in VALID_VERSIONS:
        raise OutlineServiceError(f"version 必须是 A/B/C, 收到 {version!r}")
    if not get_outline(chapter_id, version):
        raise OutlineServiceError(f"该章 {version} 版本大纲不存在")
    with _db_conn.transaction() as db:
        db.execute(
            "UPDATE chapter_outlines SET selected=0 WHERE chapter_id=?",
            (chapter_id,),
        )
        db.execute(
            "UPDATE chapter_outlines SET selected=1 WHERE chapter_id=? AND version=?",
            (chapter_id, version),
        )
    return get_outline(chapter_id, version)  # type: ignore[return-value]


def delete_outline(chapter_id: str, version: str) -> bool:
    if version not in VALID_VERSIONS:
        raise OutlineServiceError(f"version 必须是 A/B/C, 收到 {version!r}")
    with _db_conn.transaction() as db:
        cur = db.execute(
            "DELETE FROM chapter_outlines WHERE chapter_id=? AND version=?",
            (chapter_id, version),
        )
    return cur.rowcount > 0


def delete_all_for_chapter(chapter_id: str) -> int:
    with _db_conn.transaction() as db:
        cur = db.execute(
            "DELETE FROM chapter_outlines WHERE chapter_id=?", (chapter_id,)
        )
    return cur.rowcount


# --------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------- #

def list_outlines(chapter_id: str) -> List[dict]:
    """返回该章的所有版本大纲, 按 version 排序 A/B/C."""
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM chapter_outlines WHERE chapter_id=? "
            "ORDER BY version",
            (chapter_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_outline(chapter_id: str, version: str) -> Optional[dict]:
    if version not in VALID_VERSIONS:
        return None
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapter_outlines WHERE chapter_id=? AND version=?",
            (chapter_id, version),
        ).fetchone()
    return dict(row) if row else None


def get_selected(chapter_id: str) -> Optional[dict]:
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapter_outlines WHERE chapter_id=? AND selected=1",
            (chapter_id,),
        ).fetchone()
    return dict(row) if row else None


def count_versions(chapter_id: str) -> int:
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT COUNT(*) AS c FROM chapter_outlines WHERE chapter_id=?",
            (chapter_id,),
        ).fetchone()
    return int(row["c"] or 0)


# --------------------------------------------------------------------- #
# 对比 (UI 用)
# --------------------------------------------------------------------- #

def diff_versions(chapter_id: str) -> dict:
    """返回 A/B/C 三版本的并排对比. 缺失的版本填空字符串."""
    outlines = {o["version"]: o for o in list_outlines(chapter_id)}
    return {
        "A": outlines.get("A", {"version": "A", "outline": "", "core_events": "",
                                 "emotion_arc": "", "word_target": None, "selected": 0}),
        "B": outlines.get("B", {"version": "B", "outline": "", "core_events": "",
                                 "emotion_arc": "", "word_target": None, "selected": 0}),
        "C": outlines.get("C", {"version": "C", "outline": "", "core_events": "",
                                 "emotion_arc": "", "word_target": None, "selected": 0}),
    }
