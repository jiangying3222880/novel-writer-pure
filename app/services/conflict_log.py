"""
冲突日志服务 - 记录因果冲突，支持人工干预

"Guidance 而非 Constraint" 的具体落地：
- 冲突发生时，不自动改文本，而是写日志告诉作者
- 作者可以事后追溯："为什么 AI 把我精心设计的反派改成了这样？"
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.conflict_log")


@dataclass
class ConflictEntry:
    """冲突日志条目"""
    id: str
    project_id: str
    unit_id: str
    conflict_type: str  # "causal" / "hook" / "timeline" / "character" / "world"
    description: str  # 自然语言描述冲突内容
    source_a: str  # 冲突来源A
    source_b: str  # 冲突来源B
    resolution: str  # "pending" / "override_a" / "override_b" / "merge" / "manual"
    resolution_note: str  # 解决说明
    confidence: float  # 系统对此次仲裁的置信度 0-1
    affected_paragraphs: list[str]  # 影响的段落ID列表
    created_at: str
    resolved_at: Optional[str] = None


def log_conflict(
    project_id: str,
    unit_id: str,
    conflict_type: str,
    description: str,
    source_a: str,
    source_b: str,
    resolution: str = "pending",
    resolution_note: str = "",
    confidence: float = 0.5,
    affected_paragraphs: list[str] | None = None,
) -> ConflictEntry:
    """
    记录一次冲突

    Args:
        project_id: 项目ID
        unit_id: 单元ID
        conflict_type: 冲突类型 (causal/hook/timeline/character/world)
        description: 冲突描述（自然语言）
        source_a: 冲突来源A
        source_b: 冲突来源B
        resolution: 解决方式
        resolution_note: 解决说明
        confidence: 置信度 0-1
        affected_paragraphs: 影响的段落ID列表

    Returns:
        ConflictEntry: 创建的冲突条目
    """
    entry = ConflictEntry(
        id=str(uuid.uuid4()),
        project_id=project_id,
        unit_id=unit_id,
        conflict_type=conflict_type,
        description=description,
        source_a=source_a,
        source_b=source_b,
        resolution=resolution,
        resolution_note=resolution_note,
        confidence=confidence,
        affected_paragraphs=affected_paragraphs or [],
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    _save_to_db(entry)
    _logger.info(f"Conflict logged: {entry.id} ({entry.conflict_type}) for unit {unit_id}")
    return entry


def get_conflicts(
    project_id: str,
    unit_id: str | None = None,
    conflict_type: str | None = None,
    resolution: str | None = None,
) -> list[ConflictEntry]:
    """
    获取冲突列表

    Args:
        project_id: 项目ID
        unit_id: 可选，按单元ID过滤
        conflict_type: 可选，按冲突类型过滤
        resolution: 可选，按解决状态过滤

    Returns:
        list[ConflictEntry]: 冲突条目列表
    """
    conn = get_conn()
    query = "SELECT * FROM conflict_logs WHERE project_id = ?"
    params: list = [project_id]

    if unit_id:
        query += " AND unit_id = ?"
        params.append(unit_id)
    if conflict_type:
        query += " AND conflict_type = ?"
        params.append(conflict_type)
    if resolution:
        query += " AND resolution = ?"
        params.append(resolution)

    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()

    return [_row_to_entry(row) for row in rows]


def get_conflict(conflict_id: str) -> ConflictEntry | None:
    """
    获取单个冲突条目

    Args:
        conflict_id: 冲突ID

    Returns:
        ConflictEntry | None: 冲突条目，不存在返回None
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM conflict_logs WHERE id = ?", (conflict_id,)
    ).fetchone()
    return _row_to_entry(row) if row else None


def resolve_conflict(
    conflict_id: str,
    resolution: str,
    resolution_note: str = "",
) -> ConflictEntry | None:
    """
    标记冲突已解决

    Args:
        conflict_id: 冲突ID
        resolution: 解决方式 (override_a/override_b/merge/manual)
        resolution_note: 解决说明

    Returns:
        ConflictEntry | None: 更新后的冲突条目
    """
    conn = get_conn()
    conn.execute(
        """UPDATE conflict_logs
           SET resolution = ?, resolution_note = ?, resolved_at = ?
           WHERE id = ?""",
        (resolution, resolution_note, datetime.now().isoformat(timespec="seconds"), conflict_id),
    )
    conn.commit()

    _logger.info(f"Conflict resolved: {conflict_id} -> {resolution}")
    return get_conflict(conflict_id)


def get_pending_conflicts(project_id: str) -> list[ConflictEntry]:
    """
    获取待解决的冲突

    Args:
        project_id: 项目ID

    Returns:
        list[ConflictEntry]: 待解决的冲突列表
    """
    return get_conflicts(project_id, resolution="pending")


def get_conflict_stats(project_id: str) -> dict:
    """
    获取冲突统计

    Args:
        project_id: 项目ID

    Returns:
        dict: 统计信息 {total, pending, resolved, by_type: {...}}
    """
    conn = get_conn()

    total = conn.execute(
        "SELECT COUNT(*) FROM conflict_logs WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]

    pending = conn.execute(
        "SELECT COUNT(*) FROM conflict_logs WHERE project_id = ? AND resolution = 'pending'",
        (project_id,),
    ).fetchone()[0]

    by_type = {}
    rows = conn.execute(
        """SELECT conflict_type, COUNT(*) as cnt
           FROM conflict_logs WHERE project_id = ?
           GROUP BY conflict_type""",
        (project_id,),
    ).fetchall()
    for row in rows:
        by_type[row[0]] = row[1]

    return {
        "total": total,
        "pending": pending,
        "resolved": total - pending,
        "by_type": by_type,
    }


# --- 内部函数 ---

def _save_to_db(entry: ConflictEntry) -> None:
    """保存冲突条目到数据库"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO conflict_logs
           (id, project_id, unit_id, conflict_type, description,
            source_a, source_b, resolution, resolution_note,
            confidence, affected_paragraphs, created_at, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.id,
            entry.project_id,
            entry.unit_id,
            entry.conflict_type,
            entry.description,
            entry.source_a,
            entry.source_b,
            entry.resolution,
            entry.resolution_note,
            entry.confidence,
            json.dumps(entry.affected_paragraphs, ensure_ascii=False),
            entry.created_at,
            entry.resolved_at,
        ),
    )
    conn.commit()


def _row_to_entry(row) -> ConflictEntry:
    """将数据库行转换为ConflictEntry"""
    return ConflictEntry(
        id=row[0],
        project_id=row[1],
        unit_id=row[2],
        conflict_type=row[3],
        description=row[4],
        source_a=row[5],
        source_b=row[6],
        resolution=row[7],
        resolution_note=row[8],
        confidence=row[9],
        affected_paragraphs=json.loads(row[10]) if row[10] else [],
        created_at=row[11],
        resolved_at=row[12],
    )
