"""
Virtual Unit Adapter（v3.5.1+）

让 Story Engine 永远只看到 Unit 接口。
老项目的 Chapter 自动包装为 Virtual Unit，进入 run_unit()。

数据流：
  - 老 Chapter（无 source_unit_id）→ wrap → Virtual Unit
  - Virtual Unit 的修改通过 sync_to_chapter() 写回 Chapter
  - 已有 source_unit_id 的 Chapter 不重复包装，直接返回 unit_id
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.db.models import StoryUnitV2
from app.services import chapter_service, story_unit_service_v2 as _unit_svc
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.virtual_unit_adapter")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


# 虚拟单元的 source_unit_id 映射缓存: chapter_id -> unit_id
# 重启进程后失效，需要重新 wrap（幂等）
_MAP_CACHE: dict[str, str] = {}


def _read_mapping(chapter_id: str) -> Optional[str]:
    """从 chapters.source_unit_id 读现有映射."""
    chapter = chapter_service.get(chapter_id)
    return chapter.get("source_unit_id") or None


def _write_mapping(chapter_id: str, unit_id: str) -> None:
    """写 chapters.source_unit_id."""
    chapter_service.update(chapter_id, source_unit_id=unit_id)


def wrap_chapter_as_virtual_unit(chapter_id: str) -> str:
    """把一个 chapter 包装为 Virtual Unit，返回 unit_id.

    - 如果该 chapter 已有 source_unit_id，直接返回
    - 否则创建一个新的 Virtual Unit，把 chapter 内容灌入 paragraphs

    Virtual Unit 的特征：
      - unit_type = "virtual"
      - title = chapter.title
      - draft = chapter.draft
      - word_count = chapter.word_count
      - synopsis = "[Virtual Unit] 由 Chapter 自动包装"
    """
    chapter = chapter_service.get(chapter_id)

    existing = _read_mapping(chapter_id)
    if existing:
        try:
            _unit_svc.get(existing)
            _MAP_CACHE[chapter_id] = existing
            return existing
        except NotFoundError:
            _logger.warning("Chapter %s 指向 unit %s 但 Unit 不存在, 重新包装", chapter_id, existing)

    project_id = _resolve_project_id(chapter.get("book_id"))
    title = chapter.get("title") or f"[Virtual] Chapter {chapter.get('chapter_no')}"
    draft = chapter.get("draft") or ""
    word_count = int(chapter.get("word_count") or len(draft))

    unit = _unit_svc.create(
        project_id=project_id,
        title=title,
        unit_type="virtual",
        synopsis=f"[Virtual Unit] 自动由 Chapter {chapter_id} 包装",
    )

    if draft:
        from app.services import unit_paragraph_service as _para_svc
        _para_svc.replace_full_text(unit.id, project_id, draft)

    _unit_svc.update(
        unit.id,
        draft=draft,
        word_count=word_count,
        status="writing",
    )

    _write_mapping(chapter_id, unit.id)
    _MAP_CACHE[chapter_id] = unit.id

    _logger.info("包装 Virtual Unit: chapter=%s → unit=%s", chapter_id, unit.id)
    return unit.id


def sync_to_chapter(unit_id: str) -> Optional[str]:
    """把 Virtual Unit 的当前 draft 同步回 Chapter.

    返回对应的 chapter_id, 若不是 Virtual Unit 或无对应 chapter 返回 None.
    """
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT id FROM chapters WHERE source_unit_id = ? LIMIT 1", (unit_id,)
    ).fetchone()
    if not row:
        return None
    chapter_id = row["id"]

    unit = _unit_svc.get(unit_id)
    chapter_service.update(
        chapter_id,
        draft=unit.draft or "",
        word_count=int(unit.word_count or 0),
    )
    _logger.info("Virtual Unit 同步回 Chapter: unit=%s → chapter=%s", unit_id, chapter_id)
    return chapter_id


def is_virtual_unit(unit_id: str) -> bool:
    """判断一个 Unit 是否是 Virtual Unit."""
    try:
        unit = _unit_svc.get(unit_id)
        return unit.unit_type == "virtual"
    except NotFoundError:
        return False


def list_virtual_units(project_id: str) -> list[StoryUnitV2]:
    """列出项目所有 Virtual Unit."""
    return [
        u for u in _unit_svc.list_for_project(project_id)
        if u.unit_type == "virtual"
    ]


def _resolve_project_id(book_id: Optional[str]) -> str:
    """通过 book_id 反查 project_id."""
    if not book_id:
        raise ValidationError("book_id is empty, cannot resolve project_id")
    db = _db_conn.get_conn()
    row = db.execute("SELECT project_id FROM books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        raise NotFoundError("Book", book_id)
    return row["project_id"]


def auto_wrap_all_chapters(project_id: str) -> int:
    """老项目打开时自动包装所有 Chapter 为 Virtual Unit.

    返回包装数量. 已包装的 chapter 会跳过 (幂等).
    """
    db = _db_conn.get_conn()
    rows = db.execute(
        """SELECT ch.id FROM chapters ch
           JOIN books b ON ch.book_id = b.id
           WHERE b.project_id = ?
             AND (ch.source_unit_id IS NULL OR ch.source_unit_id = '')
        """,
        (project_id,),
    ).fetchall()

    count = 0
    for row in rows:
        try:
            wrap_chapter_as_virtual_unit(row["id"])
            count += 1
        except Exception as e:
            _logger.warning("包装 Chapter %s 失败: %s", row["id"], e)
    _logger.info("项目 %s 自动包装 %d 个 Virtual Unit", project_id, count)
    return count