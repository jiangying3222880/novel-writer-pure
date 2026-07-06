"""
Project Type Detection — 新/老项目双模式

设计文档§9:
- 新项目: 有 story_units (非 virtual), 默认单元视图
- 老项目: 有 chapters 但无 story_units, 默认章节视图
- 老项目升级: 可切换单元视图, 每章包虚拟单元
"""
from __future__ import annotations
import logging

_logger = logging.getLogger("NovelWriter.services.project_type")


def detect_project_type(project_id: str) -> str:
    """检测项目类型.

    Returns:
        "new" - 有 story_units (非 virtual), 使用单元模式
        "old" - 只有 chapters, 使用章节模式
        "mixed" - 有 story_units 也有 old chapters (升级中)
    """
    from app.db._impl import get_conn
    db = get_conn()

    # 检查是否有 story_units
    row = db.execute(
        """SELECT COUNT(*) as cnt FROM story_units
           WHERE project_id = ? AND unit_type != 'virtual'""",
        (project_id,),
    ).fetchone()
    unit_count = row["cnt"] if row else 0

    # 检查是否有 chapters
    row = db.execute(
        """SELECT COUNT(*) as cnt FROM chapters ch
           JOIN books b ON ch.book_id = b.id
           WHERE b.project_id = ?""",
        (project_id,),
    ).fetchone()
    chapter_count = row["cnt"] if row else 0

    if unit_count > 0 and chapter_count > 0:
        return "mixed"
    elif unit_count > 0:
        return "new"
    else:
        return "old"


def get_default_view(project_id: str) -> str:
    """获取项目默认视图.

    Returns:
        "unit" - 单元视图
        "chapter" - 章节视图
    """
    project_type = detect_project_type(project_id)
    if project_type == "old":
        return "chapter"
    return "unit"


def should_prompt_upgrade(project_id: str) -> bool:
    """是否提示老项目升级到单元模式."""
    project_type = detect_project_type(project_id)
    return project_type == "old"


def upgrade_old_project(project_id: str) -> dict:
    """将老项目升级为单元模式.

    自动包装所有 Chapter 为 Virtual Unit.
    """
    from app.services import virtual_unit_adapter

    project_type = detect_project_type(project_id)
    if project_type != "old":
        return {"ok": False, "reason": f"项目类型为 {project_type}, 无需升级"}

    try:
        count = virtual_unit_adapter.auto_wrap_all_chapters(project_id)
        _logger.info("项目 %s 升级完成, 包装 %d 个 Virtual Unit", project_id, count)
        return {"ok": True, "wrapped_count": count}
    except Exception as e:
        _logger.error("项目 %s 升级失败: %s", project_id, e)
        return {"ok": False, "error": str(e)}


def get_project_mode_info(project_id: str) -> dict:
    """获取项目模式详细信息."""
    project_type = detect_project_type(project_id)
    default_view = get_default_view(project_id)

    from app.db._impl import get_conn
    db = get_conn()

    # 统计
    unit_count = db.execute(
        "SELECT COUNT(*) as cnt FROM story_units WHERE project_id = ?",
        (project_id,),
    ).fetchone()["cnt"]

    real_unit_count = db.execute(
        "SELECT COUNT(*) as cnt FROM story_units WHERE project_id = ? AND unit_type != 'virtual'",
        (project_id,),
    ).fetchone()["cnt"]

    virtual_unit_count = db.execute(
        "SELECT COUNT(*) as cnt FROM story_units WHERE project_id = ? AND unit_type = 'virtual'",
        (project_id,),
    ).fetchone()["cnt"]

    chapter_count = db.execute(
        """SELECT COUNT(*) as cnt FROM chapters ch
           JOIN books b ON ch.book_id = b.id
           WHERE b.project_id = ?""",
        (project_id,),
    ).fetchone()["cnt"]

    return {
        "project_type": project_type,
        "default_view": default_view,
        "unit_count": unit_count,
        "real_unit_count": real_unit_count,
        "virtual_unit_count": virtual_unit_count,
        "chapter_count": chapter_count,
        "can_upgrade": project_type == "old",
    }
