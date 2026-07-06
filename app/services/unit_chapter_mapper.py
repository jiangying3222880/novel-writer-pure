"""
Unit-Chapter Mapper — 单元是真相源，章节是视图，双向同步

核心设计原则:
1. 单元 (story_units + unit_paragraphs) 是唯一真相源
2. 章节 (chapters) 是单元段落的"视图" — 内容 = 某些段落的子集
3. 双向同步:
   - 单元 → 章节: 单元内容变化时，同步到关联章节
   - 章节 → 单元: 用户修改章节时，精确同步回对应段落
4. 映射粒度: 段落级 (每个章节包含哪些段落，按顺序)
5. 章节可以跨单元吗？可以（比如两个短单元合并成一章），
   但单元始终是创作和管理的基本单位

数据:
- chapter_paragraph_map 表: chapter_id -> paragraph_id 映射 (排序)
  （如果需要，后续加 migration；当前先用段落的 char_offset 范围 + source_unit_id）

简化方案 (v1):
- 章节通过 source_unit_id + 字符范围 [start_para_idx, end_para_idx] 关联单元
- 同步时，根据段落索引范围组装/拆分
- 章节修改时，用 diff 方式同步回单元段落
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.db.models import UnitParagraph
from app.services import story_unit_service_v2 as _unit_svc
from app.services import unit_paragraph_service as _para_svc
from app.services import chapter_service as _chap_svc
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_chapter_mapper")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ============================================================
# Data structures
# ============================================================

@dataclass
class ChapterParagraphRange:
    """A chapter mapped to a range of paragraphs in a unit."""
    chapter_id: str
    unit_id: str
    start_para_idx: int  # 0-based, inclusive
    end_para_idx: int    # 0-based, inclusive
    paragraph_count: int = 0
    word_count: int = 0


@dataclass
class SyncResult:
    """Result of a sync operation."""
    ok: bool
    direction: str  # "unit_to_chapter" or "chapter_to_unit"
    unit_id: str
    chapter_id: str
    words_synced: int = 0
    paragraphs_changed: int = 0
    error: str = ""


# ============================================================
# Mapping management (paragraph range approach)
# ============================================================

def map_unit_to_chapters(
    unit_id: str,
    chapter_specs: list[dict],
    *,
    book_id: str,
    start_chapter_no: int = 1,
) -> list[dict]:
    """
    Create chapters from a unit, each covering a range of paragraphs.

    Args:
        unit_id: The source unit
        chapter_specs: List of {title, start_para_idx, end_para_idx}
        book_id: Book to create chapters in
        start_chapter_no: Starting chapter number

    Returns:
        List of created chapter dicts with paragraph range info
    """
    unit = _unit_svc.get(unit_id)
    paragraphs = _para_svc.list_for_unit(unit_id)
    total_paras = len(paragraphs)

    if not paragraphs:
        raise ValidationError("Unit has no paragraphs")

    # Validate specs
    for spec in chapter_specs:
        s = spec.get("start_para_idx", 0)
        e = spec.get("end_para_idx", total_paras - 1)
        if s < 0 or e >= total_paras or s > e:
            raise ValidationError(f"Invalid paragraph range: {s}-{e}")

    created = []
    for i, spec in enumerate(chapter_specs):
        s = spec["start_para_idx"]
        e = spec["end_para_idx"]
        title = spec.get("title", f"第{start_chapter_no + i}章")

        # Assemble chapter text from paragraphs
        chapter_text = "\n\n".join(p.text for p in paragraphs[s:e + 1])

        # Create chapter with unit linkage
        chap_dict = _chap_svc.create(
            book_id=book_id,
            chapter_no=start_chapter_no + i,
            title=title,
            status="draft",
            source_unit_id=unit_id,
            split_version=1,
            is_current_version=1,
        )
        chap_id = chap_dict["id"]

        # Set content
        _chap_svc.update(chap_id, draft=chapter_text, word_count=len(chapter_text))

        # Store paragraph range mapping (we'll use chapter_briefs or a new field)
        # For now, store in chapter_drafts source or just rely on the mapping
        # We use chapter_briefs.core_events field as JSON metadata for the range
        _store_para_range(chap_id, unit_id, s, e)

        _logger.info(
            "Mapped unit para %d-%d -> chapter %s (%d chars)",
            s, e, chap_id, len(chapter_text),
        )
        created.append({
            "id": chap_id,
            "title": title,
            "chapter_no": start_chapter_no + i,
            "unit_id": unit_id,
            "start_para_idx": s,
            "end_para_idx": e,
            "word_count": len(chapter_text),
        })

    # Mark unit as split
    _unit_svc.mark_split(unit_id)

    return created


def _store_para_range(chapter_id: str, unit_id: str, start_idx: int, end_idx: int) -> None:
    """Store paragraph range mapping in chapter metadata."""
    import json
    metadata = json.dumps({
        "source_unit_id": unit_id,
        "start_para_idx": start_idx,
        "end_para_idx": end_idx,
    }, ensure_ascii=False)

    with _db_conn.transaction() as tx:
        # Store paragraph range in scene_context field as JSON (reusing existing field)
        tx.execute(
            "UPDATE chapters SET scene_context = ?, updated_at = ? WHERE id = ?",
            (metadata, _now(), chapter_id),
        )


def _get_para_range(chapter_id: str) -> Optional[tuple[str, int, int]]:
    """Get paragraph range mapping for a chapter.
    Returns (unit_id, start_para_idx, end_para_idx) or None.
    """
    import json
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT scene_context, source_unit_id FROM chapters WHERE id = ?",
        (chapter_id,),
    ).fetchone()
    if not row:
        return None

    # Try scene_context first (JSON format)
    if row["scene_context"]:
        try:
            meta = json.loads(row["scene_context"])
            if "source_unit_id" in meta and "start_para_idx" in meta:
                return (
                    meta["source_unit_id"],
                    meta["start_para_idx"],
                    meta["end_para_idx"],
                )
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: just source_unit_id, assume full unit
    if row["source_unit_id"]:
        paragraphs = _para_svc.list_for_unit(row["source_unit_id"])
        if paragraphs:
            return (row["source_unit_id"], 0, len(paragraphs) - 1)

    return None


def get_chapters_for_unit(unit_id: str) -> list[dict]:
    """Get all chapters derived from a unit."""
    db = _db_conn.get_conn()
    rows = db.execute(
        "SELECT id, chapter_no, title, word_count, status FROM chapters WHERE source_unit_id = ? ORDER BY chapter_no",
        (unit_id,),
    ).fetchall()
    result = []
    for r in rows:
        para_range = _get_para_range(r["id"])
        item = {
            "id": r["id"],
            "chapter_no": r["chapter_no"],
            "title": r["title"] or "",
            "word_count": r["word_count"] or 0,
            "status": r["status"] or "draft",
        }
        if para_range:
            item["start_para_idx"] = para_range[1]
            item["end_para_idx"] = para_range[2]
        result.append(item)
    return result


# ============================================================
# Unit -> Chapter sync (push changes from unit to chapters)
# ============================================================

def sync_unit_to_chapters(unit_id: str) -> list[SyncResult]:
    """
    Sync unit content to all derived chapters.
    Called after unit content is modified.

    Returns list of SyncResult (one per chapter)
    """
    unit = _unit_svc.get(unit_id)
    chapters = get_chapters_for_unit(unit_id)

    if not chapters:
        return []

    paragraphs = _para_svc.list_for_unit(unit_id)
    results = []

    for chap in chapters:
        chap_id = chap["id"]
        result = _sync_unit_to_single_chapter(unit_id, chap_id, paragraphs)
        results.append(result)

    _logger.info(
        "Synced unit %s -> %d chapters",
        unit_id, len(results),
    )
    return results


def _sync_unit_to_single_chapter(
    unit_id: str,
    chapter_id: str,
    paragraphs: Optional[list[UnitParagraph]] = None,
) -> SyncResult:
    """Sync unit content to a single chapter."""
    try:
        para_range = _get_para_range(chapter_id)
        if not para_range:
            return SyncResult(
                ok=False,
                direction="unit_to_chapter",
                unit_id=unit_id,
                chapter_id=chapter_id,
                error="No paragraph range mapping found",
            )

        _, start_idx, end_idx = para_range

        if paragraphs is None:
            paragraphs = _para_svc.list_for_unit(unit_id)

        if not paragraphs:
            return SyncResult(
                ok=False,
                direction="unit_to_chapter",
                unit_id=unit_id,
                chapter_id=chapter_id,
                error="Unit has no paragraphs",
            )

        # Clamp range
        start_idx = max(0, min(start_idx, len(paragraphs) - 1))
        end_idx = max(start_idx, min(end_idx, len(paragraphs) - 1))

        # Build chapter text
        chapter_paras = paragraphs[start_idx:end_idx + 1]
        chapter_text = "\n\n".join(p.text for p in chapter_paras)
        word_count = len(chapter_text)

        # Update chapter
        _chap_svc.update(chapter_id, draft=chapter_text, word_count=word_count)

        return SyncResult(
            ok=True,
            direction="unit_to_chapter",
            unit_id=unit_id,
            chapter_id=chapter_id,
            words_synced=word_count,
            paragraphs_changed=end_idx - start_idx + 1,
        )

    except Exception as e:
        _logger.error("Sync unit->chapter failed: %s", e)
        return SyncResult(
            ok=False,
            direction="unit_to_chapter",
            unit_id=unit_id,
            chapter_id=chapter_id,
            error=str(e),
        )


# ============================================================
# Chapter -> Unit sync (push changes from chapter back to unit)
# ============================================================

def sync_chapter_to_unit(chapter_id: str) -> SyncResult:
    """
    Sync chapter content back to the source unit.
    This is the "chapter as editor" mode — user edits a chapter,
    and the changes flow back to the unit's paragraphs.

    Strategy:
    1. Get chapter's current text and mapped paragraph range
    2. Split chapter text into paragraphs
    3. Replace the corresponding paragraph range in the unit
    4. Refresh char offsets for all paragraphs after the changed range
    """
    try:
        para_range = _get_para_range(chapter_id)
        if not para_range:
            return SyncResult(
                ok=False,
                direction="chapter_to_unit",
                unit_id="",
                chapter_id=chapter_id,
                error="No paragraph range mapping found",
            )

        unit_id, start_idx, end_idx = para_range

        # Get chapter content
        chap = _chap_svc.get(chapter_id)
        chap_content = ""
        if isinstance(chap, dict):
            chap_content = chap.get("draft", "") or chap.get("final", "")
        else:
            chap_content = getattr(chap, "draft", "") or getattr(chap, "final", "")

        if not chap_content:
            return SyncResult(
                ok=False,
                direction="chapter_to_unit",
                unit_id=unit_id,
                chapter_id=chapter_id,
                error="Chapter has no content",
            )

        # Split chapter text into paragraphs
        new_paragraphs = _para_svc.split_into_paragraphs(chap_content)
        if not new_paragraphs:
            return SyncResult(
                ok=False,
                direction="chapter_to_unit",
                unit_id=unit_id,
                chapter_id=chapter_id,
                error="Chapter content has no paragraphs",
            )

        # Get current unit paragraphs
        unit_paragraphs = _para_svc.list_for_unit(unit_id)

        # Replace the paragraph range
        # Strategy: delete old paragraphs in range, insert new ones
        count_changed = _replace_paragraph_range(
            unit_id, start_idx, end_idx, new_paragraphs,
        )

        # Refresh all char offsets
        _para_svc.refresh_offsets(unit_id)

        # Sync back to all chapters (since unit content changed)
        sync_unit_to_chapters(unit_id)

        new_total = len(_para_svc.list_for_unit(unit_id))

        return SyncResult(
            ok=True,
            direction="chapter_to_unit",
            unit_id=unit_id,
            chapter_id=chapter_id,
            words_synced=len(chap_content),
            paragraphs_changed=count_changed,
        )

    except Exception as e:
        _logger.error("Sync chapter->unit failed: %s", e)
        return SyncResult(
            ok=False,
            direction="chapter_to_unit",
            unit_id="",
            chapter_id=chapter_id,
            error=str(e),
        )


def _replace_paragraph_range(
    unit_id: str,
    start_idx: int,
    end_idx: int,
    new_paragraph_texts: list[str],
) -> int:
    """
    Replace a range of paragraphs in a unit with new ones.
    Strategy: assemble the full new text from old paragraphs + new paragraphs,
    then use replace_full_text to rebuild everything.

    Returns number of new paragraphs.
    """
    unit = _unit_svc.get(unit_id)
    project_id = unit.project_id
    paragraphs = _para_svc.list_for_unit(unit_id)

    if not paragraphs:
        raise ValidationError("Unit has no paragraphs")

    start_idx = max(0, min(start_idx, len(paragraphs) - 1))
    end_idx = max(start_idx, min(end_idx, len(paragraphs) - 1))

    # Build new full text: prefix paragraphs + new paragraphs + suffix paragraphs
    prefix_paras = paragraphs[:start_idx]
    suffix_paras = paragraphs[end_idx + 1:]

    parts = []
    if prefix_paras:
        parts.append("\n\n".join(p.text for p in prefix_paras))
    parts.append("\n\n".join(new_paragraph_texts))
    if suffix_paras:
        parts.append("\n\n".join(p.text for p in suffix_paras))

    new_full_text = "\n\n".join(p for p in parts if p)

    # Rebuild all paragraphs
    _para_svc.replace_full_text(unit_id, project_id, new_full_text)

    return len(new_paragraph_texts)


# ============================================================
# Auto-split: auto create chapters from a unit (simple version)
# ============================================================

def auto_split_unit(
    unit_id: str,
    book_id: str,
    *,
    target_chars: int = 3000,
    min_chars: int = 2000,
    max_chars: int = 4000,
    start_chapter_no: int = 1,
) -> list[dict]:
    """
    Auto-split a unit into chapters based on target word count.
    Uses paragraph boundaries as break points.

    This is a simpler version of unit_splitter.py that works with
    the paragraph system and creates proper mappings.
    """
    paragraphs = _para_svc.list_for_unit(unit_id)
    if not paragraphs:
        raise ValidationError("Unit has no paragraphs")

    # Build chapter specs by accumulating paragraphs
    specs = []
    current_start = 0
    current_chars = 0
    chapter_num = 0

    for i, para in enumerate(paragraphs):
        para_len = len(para.text)
        current_chars += para_len + 2  # +2 for \n\n

        # Check if we should break after this paragraph
        should_break = False
        if current_chars >= target_chars and i < len(paragraphs) - 1:
            # Near target, and not the last paragraph
            should_break = True
        elif current_chars >= max_chars:
            # Hit max, must break
            should_break = True
        elif i == len(paragraphs) - 1 and current_chars > min_chars:
            # Last paragraph and we have enough content
            should_break = True

        if should_break and current_chars >= min_chars:
            chapter_num += 1
            specs.append({
                "title": f"第{start_chapter_no + chapter_num - 1}章",
                "start_para_idx": current_start,
                "end_para_idx": i,
            })
            current_start = i + 1
            current_chars = 0

    # Handle remaining paragraphs
    if current_start < len(paragraphs):
        chapter_num += 1
        specs.append({
            "title": f"第{start_chapter_no + chapter_num - 1}章",
            "start_para_idx": current_start,
            "end_para_idx": len(paragraphs) - 1,
        })

    if not specs:
        # Unit too short, make one chapter
        specs = [{
            "title": f"第{start_chapter_no}章",
            "start_para_idx": 0,
            "end_para_idx": len(paragraphs) - 1,
        }]

    return map_unit_to_chapters(
        unit_id, specs,
        book_id=book_id,
        start_chapter_no=start_chapter_no,
    )


# ============================================================
# Rebuild chapters from unit (full refresh)
# ============================================================

def rebuild_chapters_from_unit(
    unit_id: str,
    book_id: str,
    *,
    target_chars: int = 3000,
    min_chars: int = 2000,
    max_chars: int = 4000,
) -> list[dict]:
    """
    Delete all chapters derived from a unit and recreate them.
    Useful when the unit structure changes significantly.

    Args:
        unit_id: Source unit ID
        book_id: Target book ID
        target_chars: Target word count per chapter
        min_chars: Minimum word count
        max_chars: Maximum word count
    """
    chapters = get_chapters_for_unit(unit_id)
    if chapters:
        for chap in chapters:
            try:
                _chap_svc.delete(chap["id"])
            except Exception:
                pass

    return auto_split_unit(
        unit_id, book_id,
        target_chars=target_chars,
        min_chars=min_chars,
        max_chars=max_chars,
    )


# ============================================================
# 记忆迁移 (设计文档§7)
# ============================================================

def migrate_memories(unit_id: str, chapter_ids: list[str]) -> dict:
    """迁移单元记忆到拆分后的章节.

    设计文档§7.2规则:
    - L1 世界规则/故事弧: 全量复制到每章
    - L2 承诺/伏笔: 根据文本位置精确分配
    - L3 RAG临时: 不迁移
    - L4 已遗忘: 不迁移
    - 单元专属记忆: 保留在单元上
    """
    from app.services import story_unit_service_v2 as unit_svc

    unit = unit_svc.get(unit_id)
    unit_memories = unit_svc.get_unit_memory(unit_id)

    results = {"migrated": 0, "skipped": 0, "errors": []}

    for chapter_id in chapter_ids:
        try:
            # L1: 世界规则 + 故事弧 (全量复制)
            l1_memories = [m for m in unit_memories if m.get("level") in ("l1", "world", "arc")]

            # L2: 承诺/伏笔 (根据文本位置分配)
            l2_memories = [m for m in unit_memories if m.get("level") in ("l2", "commitment", "hook")]

            # 合并需要迁移的记忆
            to_migrate = l1_memories + l2_memories

            if to_migrate:
                _store_chapter_memories(chapter_id, to_migrate)
                results["migrated"] += len(to_migrate)

        except Exception as e:
            results["errors"].append(f"{chapter_id}: {e}")

    return results


def _store_chapter_memories(chapter_id: str, memories: list[dict]) -> None:
    """存储章节记忆."""
    from app.db._impl import get_conn
    import json

    db = get_conn()
    for mem in memories:
        try:
            db.execute(
                """INSERT INTO agent_memory (id, chapter_id, level, content, source, created_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                (
                    f"mem_{chapter_id[:8]}_{mem.get('level', 'l1')}",
                    chapter_id,
                    mem.get("level", "l1"),
                    mem.get("content", ""),
                    mem.get("source", "unit_migration"),
                ),
            )
        except Exception:
            pass  # 忽略重复插入


def distribute_pressure_curve(unit_id: str, chapter_ids: list[str]) -> dict:
    """将单元压力曲线平均分配到拆分后的章节."""
    from app.services import story_unit_service_v2 as unit_svc
    from app.db._impl import get_conn
    import json

    unit = unit_svc.get(unit_id)
    results = {"distributed": 0, "errors": []}

    # 获取单元压力数据
    try:
        entry_world = json.loads(unit.entry_world or "{}")
        exit_world = json.loads(unit.exit_world or "{}")
        pressure = entry_world.get("pressure", {})
    except Exception:
        pressure = {}

    if not pressure:
        return results

    # 平均分配到每章
    per_chapter_pressure = {}
    for key, value in pressure.items():
        if isinstance(value, (int, float)):
            per_chapter_pressure[key] = value / max(len(chapter_ids), 1)

    # 写入每章
    db = get_conn()
    for chapter_id in chapter_ids:
        try:
            # 更新章节的世界状态
            row = db.execute(
                "SELECT world_state FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
            if row:
                world = json.loads(row["world_state"] or "{}")
                world.update(per_chapter_pressure)
                db.execute(
                    "UPDATE chapters SET world_state = ? WHERE id = ?",
                    (json.dumps(world), chapter_id),
                )
                results["distributed"] += 1
        except Exception as e:
            results["errors"].append(f"{chapter_id}: {e}")

    return results


def migrate_subtext_cards(unit_id: str, chapter_ids: list[str]) -> dict:
    """迁移潜文本卡到拆分后的章节."""
    from app.db._impl import get_conn

    results = {"migrated": 0, "errors": []}
    db = get_conn()

    # 获取单元级潜文本卡
    try:
        cards = db.execute(
            "SELECT * FROM scene_subtext_cards WHERE unit_id = ?",
            (unit_id,),
        ).fetchall()
    except Exception:
        cards = []

    if not cards:
        return results

    # 复制到每章 (单元级保留)
    for card in cards:
        for chapter_id in chapter_ids:
            try:
                db.execute(
                    """INSERT INTO scene_subtext_cards
                       (id, chapter_id, card_type, content, created_at)
                       VALUES (?, ?, ?, ?, datetime('now'))""",
                    (
                        f"sub_{chapter_id[:8]}_{card['card_type'][:8]}",
                        chapter_id,
                        card["card_type"],
                        card.get("content", ""),
                    ),
                )
                results["migrated"] += 1
            except Exception as e:
                results["errors"].append(f"{chapter_id}: {e}")

    return results
