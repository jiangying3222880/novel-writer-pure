"""
单元段落管理服务
- 正文切分为段落（每段稳定 UUID）
- 段落 CRUD
- 从段落组装全文
- 段落范围查询（拆章器用）
- 字符偏移量刷新

段落是单元与章节的桥梁：
- 单元正文 = 所有段落按 sort_order 拼接
- 章节正文 = 一部分段落按顺序拼接
- 钩子、记忆、一致性问题都挂在 paragraph_id 上
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.db.models import UnitParagraph
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_paragraph")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_paragraph(row) -> UnitParagraph:
    return UnitParagraph(
        id=row["id"],
        unit_id=row["unit_id"],
        project_id=row["project_id"],
        sort_order=row["sort_order"] or 0,
        text=row["text"] or "",
        char_start=row["char_start"] if row["char_start"] is not None else -1,
        char_end=row["char_end"] if row["char_end"] is not None else -1,
        paragraph_type=row["paragraph_type"] or "normal",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# ────────────────────── 文本切分 ──────────────────────

def split_into_paragraphs(text: str) -> list[str]:
    """
    把文本切分成段落。
    - 按空行切分（\n\n 或 \r\n\r\n）
    - 保留每段原始内容（包含行内换行）
    - 空段落过滤掉
    """
    if not text:
        return []
    # 统一换行符
    normalized = text.replace("\r\n", "\n")
    # 按双换行切分
    parts = normalized.split("\n\n")
    # 过滤空段，去首尾空白
    paragraphs = [p.strip("\n") for p in parts if p.strip()]
    return paragraphs


def classify_paragraph_type(text: str) -> str:
    """
    简单判断段落类型。
    - dialogue: 以引号开头的对话
    - description: 环境/外貌描写（启发式）
    - narration: 叙述
    - transition: 过渡段（时间/地点跳转）
    """
    stripped = text.strip()
    if not stripped:
        return "normal"

    # Dialogue detection: various quotation marks
    quote_chars = ('\u201c', '\u201d', '\u2018', '\u2019',
                   '\u300c', '\u300d', '\u300e', '\u300f',
                   '"', "'")
    if stripped[0] in quote_chars:
        return "dialogue"

    # 过渡段标志
    transition_markers = [
        "第二天", "三日后", "三个月后", "十年后", "转眼", "时光飞逝",
        "与此同时", "另一边", "与此同时",
        "画面一转", "镜头切到",
        "——", "---", "***",
    ]
    for marker in transition_markers:
        if stripped.startswith(marker) or stripped.startswith("　　" + marker):
            return "transition"

    # 环境描写启发式
    desc_words = ["天空", "阳光", "月光", "风", "雨", "雪", "街道", "房间", "大殿", "山脉"]
    desc_count = sum(1 for w in desc_words if w in stripped[:30])
    if desc_count >= 2 and not stripped.startswith("　　他") and not stripped.startswith("　　她"):
        return "description"

    return "narration"


# ────────────────────── 段落 CRUD ──────────────────────

def create_paragraph(
    unit_id: str,
    project_id: str,
    text: str,
    *,
    sort_order: Optional[int] = None,
    paragraph_type: str = "normal",
) -> UnitParagraph:
    """创建一个新段落"""
    if not unit_id:
        raise ValidationError("unit_id 必填")
    if not project_id:
        raise ValidationError("project_id 必填")
    if text is None:
        raise ValidationError("text 必填")

    if sort_order is None:
        sort_order = _next_sort_order(unit_id)

    pid = _new_id()
    now = _now()

    with _db_conn.transaction() as db:
        db.execute(
            """
            INSERT INTO unit_paragraphs
                (id, unit_id, project_id, sort_order, text,
                 paragraph_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, unit_id, project_id, sort_order, text,
             paragraph_type, now, now),
        )

    _logger.debug("创建段落: %s @ 单元 %s", pid, unit_id)
    return get_paragraph(pid)


def get_paragraph(paragraph_id: str) -> UnitParagraph:
    """获取单个段落."""
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT * FROM unit_paragraphs WHERE id = ?", (paragraph_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("UnitParagraph", paragraph_id)
    return _row_to_paragraph(row)


def list_for_unit(unit_id: str) -> list[UnitParagraph]:
    """列出单元所有段落，按 sort_order 升序."""
    if not unit_id:
        raise ValidationError("unit_id 必填")
    db = _db_conn.get_conn()
    rows = db.execute(
        "SELECT * FROM unit_paragraphs WHERE unit_id = ? ORDER BY sort_order ASC",
        (unit_id,),
    ).fetchall()
    return [_row_to_paragraph(r) for r in rows]


def get_range_by_chars(
    unit_id: str,
    char_start: int,
    char_end: int,
) -> list[UnitParagraph]:
    """
    根据字符范围获取段落。
    返回所有与 [char_start, char_end) 有交集的段落。
    """
    paragraphs = list_for_unit(unit_id)
    result = []
    for p in paragraphs:
        if p.char_start < 0 or p.char_end < 0:
            continue
        if p.char_end > char_start and p.char_start < char_end:
            result.append(p)
    return result


def update_paragraph(paragraph_id: str, *, text: Optional[str] = None,
                     paragraph_type: Optional[str] = None) -> UnitParagraph:
    """更新段落内容或类型.更新后需要手动刷新偏移量."""
    updates = {}
    if text is not None:
        updates["text"] = text
    if paragraph_type is not None:
        updates["paragraph_type"] = paragraph_type
    if not updates:
        return get_paragraph(paragraph_id)

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [paragraph_id]

    with _db_conn.transaction() as db:
        cur = db.execute(
            f"UPDATE unit_paragraphs SET {set_clause} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            raise NotFoundError("UnitParagraph", paragraph_id)

    return get_paragraph(paragraph_id)


def delete_paragraph(paragraph_id: str) -> bool:
    """删除单个段落.删除后建议重排序号."""
    with _db_conn.transaction() as db:
        cur = db.execute("DELETE FROM unit_paragraphs WHERE id = ?", (paragraph_id,))
        if cur.rowcount == 0:
            raise NotFoundError("UnitParagraph", paragraph_id)
    return True


def delete_by_unit(unit_id: str) -> int:
    """删除单元下所有段落."""
    with _db_conn.transaction() as db:
        cur = db.execute("DELETE FROM unit_paragraphs WHERE unit_id = ?", (unit_id,))
        return cur.rowcount


# ────────────────────── 排序管理 ──────────────────────

def _next_sort_order(unit_id: str) -> int:
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM unit_paragraphs WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    return (row["m"] or 0) + 10


def reorder_paragraphs(unit_id: str, ordered_ids: list[str]) -> bool:
    """
    重新排序段落。
    - ordered_ids: 按新顺序排列的段落 ID 列表
    - 自动从 10 开始以 10 为步长编号（预留插入空间）
    """
    if not unit_id:
        raise ValidationError("unit_id 必填")
    if not ordered_ids:
        return True

    with _db_conn.transaction() as db:
        for idx, pid in enumerate(ordered_ids):
            db.execute(
                "UPDATE unit_paragraphs SET sort_order = ?, updated_at = ? WHERE id = ? AND unit_id = ?",
                ((idx + 1) * 10, _now(), pid, unit_id),
            )

    return True


def insert_paragraph_at(unit_id: str, project_id: str, text: str,
                        index: int, paragraph_type: str = "normal") -> UnitParagraph:
    """
    在指定位置插入段落（0-based）。
    后面的段落自动后移。
    """
    paragraphs = list_for_unit(unit_id)
    ids = [p.id for p in paragraphs]
    new_para = create_paragraph(unit_id, project_id, text,
                                sort_order=0, paragraph_type=paragraph_type)
    index = max(0, min(index, len(ids)))
    ids.insert(index, new_para.id)
    reorder_paragraphs(unit_id, ids)
    return get_paragraph(new_para.id)


# ────────────────────── 全文组装 ──────────────────────

def assemble_full_text(unit_id: str) -> str:
    """把所有段落按顺序组装成完整文本，段间用空行分隔."""
    paragraphs = list_for_unit(unit_id)
    if not paragraphs:
        return ""
    return "\n\n".join(p.text for p in paragraphs)


def assemble_text_range(unit_id: str, start_index: int, end_index: int) -> str:
    """
    组装指定范围的段落文本。
    - start_index, end_index: 段落索引（0-based, 左闭右开）
    """
    paragraphs = list_for_unit(unit_id)
    selected = paragraphs[start_index:end_index]
    if not selected:
        return ""
    return "\n\n".join(p.text for p in selected)


# ────────────────────── 偏移量管理 ──────────────────────

def refresh_offsets(unit_id: str) -> int:
    """
    刷新所有段落的 char_start / char_end。
    基于段落顺序和段落内容计算。
    返回段落数量。
    """
    paragraphs = list_for_unit(unit_id)
    if not paragraphs:
        return 0

    current_offset = 0
    with _db_conn.transaction() as db:
        for i, p in enumerate(paragraphs):
            length = len(p.text)
            db.execute(
                "UPDATE unit_paragraphs SET char_start = ?, char_end = ?, updated_at = ? WHERE id = ?",
                (current_offset, current_offset + length, _now(), p.id),
            )
            current_offset += length
            # 段间空行
            if i < len(paragraphs) - 1:
                current_offset += 2  # \n\n

    _logger.debug("刷新段落偏移量: 单元 %s, %d 段", unit_id, len(paragraphs))
    return len(paragraphs)


# ────────────────────── 全文替换（批量重建段落） ──────────────────────

def replace_full_text(unit_id: str, project_id: str, full_text: str) -> list[UnitParagraph]:
    """
    用完整文本替换单元的所有段落。
    - 删除所有旧段落
    - 切分新文本为段落
    - 创建新段落（带新 ID，不回收旧 ID）
    - 刷新偏移量

    注意：旧段落上挂的钩子/记忆等需要调用方另行处理。
    """
    if not unit_id:
        raise ValidationError("unit_id 必填")

    # 切分新段落
    para_texts = split_into_paragraphs(full_text)

    with _db_conn.transaction() as db:
        # 删除旧段落
        db.execute("DELETE FROM unit_paragraphs WHERE unit_id = ?", (unit_id,))

        now = _now()
        # 插入新段落
        new_paragraphs = []
        for idx, text in enumerate(para_texts):
            pid = _new_id()
            ptype = classify_paragraph_type(text)
            db.execute(
                """
                INSERT INTO unit_paragraphs
                    (id, unit_id, project_id, sort_order, text,
                     paragraph_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, unit_id, project_id, (idx + 1) * 10, text,
                 ptype, now, now),
            )
            new_paragraphs.append(pid)

    # 刷新偏移量
    refresh_offsets(unit_id)

    _logger.info("重建单元段落: %s, %d 段", unit_id, len(para_texts))
    return [get_paragraph(pid) for pid in new_paragraphs]


def get_paragraph_count(unit_id: str) -> int:
    """获取单元段落数."""
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM unit_paragraphs WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    return row["cnt"] if row else 0
