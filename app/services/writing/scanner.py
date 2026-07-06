"""
Scanning 工具 (Phase 3 M3).

扫前后 = 拿一个关键词 / 实体名, 找出全书中所有相关段, 让用户:
  - 决定是否需要重写
  - 决定是否需要实体重塑
  - 决定是否触发批量重生成

设计: 不调 LLM, 纯文本匹配. 用户拿结果后自己决定下一步.

M3-B: 搬到 app/services/writing/ 下, 原 app.core 留 re-export shim.
"""
from __future__ import annotations
import logging
import re
from collections import defaultdict
from typing import Optional

from app.services import project_service, chapter_service
from app.core.exceptions import NotFoundError, ValidationError, ServiceError

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 工具: 拿章节当前 draft
# --------------------------------------------------------------------- #

def _get_chapter_text(chapter_id: str) -> str:
    """优先 current_draft, 没有则 draft 列, 都没有则空串."""
    draft = chapter_service.get_current_draft(chapter_id)
    if draft and draft.get("content"):
        return draft["content"]
    ch = chapter_service.get(chapter_id)
    return ch.get("draft") or ch.get("final") or ""


def split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# --------------------------------------------------------------------- #
# 扫前后
# --------------------------------------------------------------------- #

def find_mentions(
    project_id: str,
    keyword: str,
    *,
    case_sensitive: bool = False,
    max_chapters: int = 0,
) -> dict:
    """扫全书, 找包含 keyword 的所有段.

    Args:
        project_id: 项目 ID
        keyword: 关键词 / 实体名
        case_sensitive: 是否区分大小写
        max_chapters: 限制章节数 (0 = 不限)

    Returns:
        {
            "keyword": str,
            "total_mentions": int,
            "total_chapters": int,
            "mentions": [
                {
                    "chapter_id": str,
                    "chapter_no": int,
                    "title": str,
                    "paragraph_index": int,
                    "paragraph_text": str,
                    "match_count": int,    # 该段内出现次数
                },
                ...
            ]
        }

    Raises:
        ValidationError: keyword 为空
        NotFoundError:   project 不存在
    """
    if not keyword or not keyword.strip():
        raise ValidationError("keyword 不能为空")
    # 404 guard
    project_service.get(project_id)

    # 拿到 project 下所有 books 的所有 chapters (走 L2 services.db.connection, 共享同 DB)
    from app.db import _impl as _db_connection
    with _db_connection() as conn:
        rows = conn.execute(
            """SELECT c.id, c.chapter_no, c.title FROM chapters c
               JOIN books b ON c.book_id = b.id
               WHERE b.project_id = ?
               ORDER BY b.volume_no, c.chapter_no""",
            (project_id,),
        ).fetchall()
    chapters = [dict(r) for r in rows]
    if max_chapters > 0:
        chapters = chapters[:max_chapters]

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(keyword), flags)

    mentions: list[dict] = []
    for ch in chapters:
        text = _get_chapter_text(ch["id"])
        if not text:
            continue
        for idx, para in enumerate(split_paragraphs(text)):
            matches = pattern.findall(para)
            if matches:
                mentions.append({
                    "chapter_id": ch["id"],
                    "chapter_no": ch["chapter_no"],
                    "title": ch.get("title") or "",
                    "paragraph_index": idx,
                    "paragraph_text": para,
                    "match_count": len(matches),
                })

    return {
        "keyword": keyword,
        "total_mentions": len(mentions),
        "total_chapters": len({m["chapter_id"] for m in mentions}),
        "mentions": mentions,
    }


def find_entity_chapters(project_id: str, entity_name: str) -> dict:
    """找某 entity 出现过的所有章 (基于 entity_appearances 索引).

    与 find_mentions 区别: 这个用索引, 速度快; 那个扫全文, 慢但精确.
    """
    if not entity_name:
        raise ValidationError("entity_name 不能为空")
    cr = chapter_reader()
    apps = cr.list_entity_appearances_for_project(
        project_id, entity_name=entity_name,
    )
    matched = apps.get("appearances", [])
    # 按 chapter 分组
    by_ch: dict[str, list[dict]] = defaultdict(list)
    for a in matched:
        by_ch[a["chapter_id"]].append({
            "paragraph_index": a.get("paragraph_index"),
            "appearance_id": a["id"],
        })
    # 拉 chapter 元信息
    chapters: list[dict] = []
    for ch_id, items in by_ch.items():
        try:
            ch = cr.get(ch_id)
        except NotFoundError:
            continue
        chapters.append({
            "chapter_id": ch_id,
            "chapter_no": ch.get("chapter_no"),
            "title": ch.get("title") or "",
            "paragraphs": items,
        })
    chapters.sort(key=lambda x: x["chapter_no"] or 0)
    return {
        "entity_name": entity_name,
        "total_chapters": len(chapters),
        "total_appearances": len(matched),
        "chapters": chapters,
    }
