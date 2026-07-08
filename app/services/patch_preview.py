"""
增量补丁预览服务 - 展示AI生成的增量变更，支持人工预览

"数控机床"而非"香肠生产线"的核心体现：
- 不直接改写源文件
- 先输出补丁预览，让作者确认
- 作者确认后，只替换指定内容
"""
from __future__ import annotations

import difflib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.patch_preview")


@dataclass
class PatchChange:
    """单个变更项"""
    id: str
    patch_id: str
    unit_id: str
    paragraph_index: int
    change_type: str  # "add" / "delete" / "modify"
    old_content: str  # 原内容（delete/modify时有值）
    new_content: str  # 新内容（add/modify时有值）
    similarity: float  # 0-1，相似度（modify时有值）


@dataclass
class PatchPreview:
    """补丁预览"""
    id: str
    project_id: str
    unit_id: str
    description: str  # 补丁描述（如"修改配角名字"）
    changes: list[PatchChange] = field(default_factory=list)
    estimated_api_cost: float = 0.0  # 预估API费用
    estimated_time_seconds: float = 0.0  # 预估时间
    status: str = "pending"  # pending / applied / rejected
    created_at: str = ""
    applied_at: Optional[str] = None


def generate_patch(
    project_id: str,
    unit_id: str,
    old_content: str,
    new_content: str,
    description: str = "",
) -> PatchPreview:
    """
    生成补丁预览

    Args:
        project_id: 项目ID
        unit_id: 单元ID
        old_content: 原内容
        new_content: 新内容
        description: 补丁描述

    Returns:
        PatchPreview: 补丁预览
    """
    patch_id = str(uuid.uuid4())
    changes = _diff_contents(patch_id, unit_id, old_content, new_content)

    preview = PatchPreview(
        id=patch_id,
        project_id=project_id,
        unit_id=unit_id,
        description=description or "自动检测的变更",
        changes=changes,
        estimated_api_cost=len(changes) * 0.01,  # 预估每段0.01元
        estimated_time_seconds=len(changes) * 2.0,  # 预估每段2秒
        status="pending",
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    _save_to_db(preview)
    _logger.info(f"Patch generated: {patch_id} with {len(changes)} changes")
    return preview


def get_patch(patch_id: str) -> PatchPreview | None:
    """
    获取补丁预览

    Args:
        patch_id: 补丁ID

    Returns:
        PatchPreview | None: 补丁预览
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM patch_previews WHERE id = ?", (patch_id,)
    ).fetchone()

    if not row:
        return None

    preview = _row_to_preview(row)
    preview.changes = _get_changes(patch_id)
    return preview


def get_patches(
    project_id: str,
    unit_id: str | None = None,
    status: str | None = None,
) -> list[PatchPreview]:
    """
    获取补丁列表

    Args:
        project_id: 项目ID
        unit_id: 可选，按单元ID过滤
        status: 可选，按状态过滤

    Returns:
        list[PatchPreview]: 补丁列表
    """
    conn = get_conn()
    query = "SELECT * FROM patch_previews WHERE project_id = ?"
    params: list = [project_id]

    if unit_id:
        query += " AND unit_id = ?"
        params.append(unit_id)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()

    previews = []
    for row in rows:
        preview = _row_to_preview(row)
        preview.changes = _get_changes(preview.id)
        previews.append(preview)

    return previews


def apply_patch(
    patch_id: str,
    confirmed_change_ids: list[str] | None = None,
) -> int:
    """
    应用补丁

    Args:
        patch_id: 补丁ID
        confirmed_change_ids: 确认应用的变更ID列表，None表示全部应用

    Returns:
        int: 实际应用的变更数
    """
    preview = get_patch(patch_id)
    if not preview:
        return 0

    changes = preview.changes
    if confirmed_change_ids:
        changes = [c for c in changes if c.id in confirmed_change_ids]

    # TODO: 实际应用变更到内容
    # 这里只是记录状态，实际内容更新由调用方处理

    # 更新状态
    conn = get_conn()
    conn.execute(
        """UPDATE patch_previews
           SET status = 'applied', applied_at = ?
           WHERE id = ?""",
        (datetime.now().isoformat(timespec="seconds"), patch_id),
    )
    conn.commit()

    _logger.info(f"Patch applied: {patch_id}, {len(changes)} changes")
    return len(changes)


def reject_patch(patch_id: str) -> bool:
    """
    拒绝补丁

    Args:
        patch_id: 补丁ID

    Returns:
        bool: 是否成功
    """
    conn = get_conn()
    conn.execute(
        "UPDATE patch_previews SET status = 'rejected' WHERE id = ?",
        (patch_id,),
    )
    conn.commit()

    _logger.info(f"Patch rejected: {patch_id}")
    return True


def preview_as_text(patch_id: str) -> str:
    """
    将补丁预览格式化为文本

    Args:
        patch_id: 补丁ID

    Returns:
        str: 格式化的补丁预览文本
    """
    preview = get_patch(patch_id)
    if not preview:
        return "补丁不存在"

    lines = [
        f"=== 补丁预览 ===",
        f"ID: {preview.id}",
        f"描述: {preview.description}",
        f"变更数: {len(preview.changes)}",
        f"预估费用: ¥{preview.estimated_api_cost:.2f}",
        f"预估时间: {preview.estimated_time_seconds:.1f}秒",
        "",
    ]

    for i, change in enumerate(preview.changes, 1):
        lines.append(f"--- 变更 {i} ({change.change_type}) ---")
        if change.change_type == "delete":
            lines.append(f"删除: {change.old_content[:100]}...")
        elif change.change_type == "add":
            lines.append(f"新增: {change.new_content[:100]}...")
        elif change.change_type == "modify":
            lines.append(f"原文: {change.old_content[:100]}...")
            lines.append(f"改为: {change.new_content[:100]}...")
            lines.append(f"相似度: {change.similarity:.2%}")
        lines.append("")

    return "\n".join(lines)


# --- 内部函数 ---

def _diff_contents(
    patch_id: str,
    unit_id: str,
    old_content: str,
    new_content: str,
) -> list[PatchChange]:
    """对比新旧内容，生成变更列表"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    changes = []
    paragraph_index = 0

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            paragraph_index += (i2 - i1)
            continue

        if op == "delete":
            for idx in range(i1, i2):
                change = PatchChange(
                    id=str(uuid.uuid4()),
                    patch_id=patch_id,
                    unit_id=unit_id,
                    paragraph_index=paragraph_index,
                    change_type="delete",
                    old_content=old_lines[idx].rstrip(),
                    new_content="",
                    similarity=0.0,
                )
                changes.append(change)
                paragraph_index += 1

        elif op == "insert":
            for idx in range(j1, j2):
                change = PatchChange(
                    id=str(uuid.uuid4()),
                    patch_id=patch_id,
                    unit_id=unit_id,
                    paragraph_index=paragraph_index,
                    change_type="add",
                    old_content="",
                    new_content=new_lines[idx].rstrip(),
                    similarity=0.0,
                )
                changes.append(change)

        elif op == "replace":
            old_chunk = "".join(old_lines[i1:i2])
            new_chunk = "".join(new_lines[j1:j2])
            similarity = difflib.SequenceMatcher(None, old_chunk, new_chunk).ratio()

            change = PatchChange(
                id=str(uuid.uuid4()),
                patch_id=patch_id,
                unit_id=unit_id,
                paragraph_index=paragraph_index,
                change_type="modify",
                old_content=old_chunk.rstrip(),
                new_content=new_chunk.rstrip(),
                similarity=similarity,
            )
            changes.append(change)
            paragraph_index += (i2 - i1)

    return changes


def _save_to_db(preview: PatchPreview) -> None:
    """保存补丁预览到数据库"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO patch_previews
           (id, project_id, unit_id, description, estimated_api_cost,
            estimated_time_seconds, status, created_at, applied_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            preview.id,
            preview.project_id,
            preview.unit_id,
            preview.description,
            preview.estimated_api_cost,
            preview.estimated_time_seconds,
            preview.status,
            preview.created_at,
            preview.applied_at,
        ),
    )

    # 保存变更列表
    for change in preview.changes:
        conn.execute(
            """INSERT INTO patch_changes
               (id, patch_id, unit_id, paragraph_index, change_type,
                old_content, new_content, similarity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                change.id,
                change.patch_id,
                change.unit_id,
                change.paragraph_index,
                change.change_type,
                change.old_content,
                change.new_content,
                change.similarity,
            ),
        )

    conn.commit()


def _get_changes(patch_id: str) -> list[PatchChange]:
    """获取补丁的变更列表"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM patch_changes WHERE patch_id = ? ORDER BY paragraph_index",
        (patch_id,),
    ).fetchall()

    return [
        PatchChange(
            id=row[0],
            patch_id=row[1],
            unit_id=row[2],
            paragraph_index=row[3],
            change_type=row[4],
            old_content=row[5],
            new_content=row[6],
            similarity=row[7],
        )
        for row in rows
    ]


def _row_to_preview(row) -> PatchPreview:
    """将数据库行转换为PatchPreview"""
    return PatchPreview(
        id=row[0],
        project_id=row[1],
        unit_id=row[2],
        description=row[3],
        estimated_api_cost=row[4],
        estimated_time_seconds=row[5],
        status=row[6],
        created_at=row[7],
        applied_at=row[8],
    )
