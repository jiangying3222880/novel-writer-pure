"""
实体重塑 (Phase 3 M3).

实体重塑 = 改 entity_name 索引 + (可选) 改 chapter.draft 正文里的字面提及.

设计原则:
  - 索引是"事实": entity_appearances 表里 entity_name 是查询入口, 必须改一致
  - 正文是"作品": chapter.draft 是创作产物, 重塑不应自动改, 由用户决定
  - 故 reshape_entity 默认只改索引; 若要改正文, 用户走:
      1) batch_regenerator (重生成整章)
      2) 段落重写 (单段)
      3) scanner.find_mentions() 先看哪些段需要改

M3-B: 搬到 app/services/writing/ 下, 原 app.core 留 re-export shim.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Optional

from app.services import project_service, chapter_service
from app.core.exceptions import NotFoundError, ValidationError, ServiceError

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 列出实体
# --------------------------------------------------------------------- #

def list_entities_summary(project_id: str) -> list[dict]:
    """聚合 entity_appearances, 返回 [{entity_type, entity_name,
    chapter_count, appearance_count}, ...] 按出现次数降序.

    Raises NotFoundError if project not exists.
    """
    # 404 guard: project 存在性 (通过注入的 ProjectReader)
    project_service.get(project_id)

    apps = chapter_service.list_entity_appearances_for_project(project_id)
    agg: dict[tuple[str, str], dict] = {}
    for a in apps.get("appearances", []):
        key = (a["entity_type"], a["entity_name"])
        if key not in agg:
            agg[key] = {
                "entity_type": a["entity_type"],
                "entity_name": a["entity_name"],
                "chapter_count": 0,
                "appearance_count": 0,
                "_seen_chapters": set(),
            }
        entry = agg[key]
        entry["appearance_count"] += 1
        if a["chapter_id"] not in entry["_seen_chapters"]:
            entry["_seen_chapters"].add(a["chapter_id"])
            entry["chapter_count"] += 1
    # 拆 set 出去
    result: list[dict] = []
    for v in agg.values():
        v.pop("_seen_chapters", None)
        result.append(v)
    result.sort(key=lambda x: (-x["appearance_count"], x["entity_name"]))
    return result


# --------------------------------------------------------------------- #
# 重塑 entity_name
# --------------------------------------------------------------------- #

def reshape_entity(
    project_id: str,
    old_name: str,
    new_name: str,
    *,
    dry_run: bool = False,
) -> dict:
    """重塑 entity 名字: 更新 entity_appearances 表中所有匹配行.

    Returns:
        {
            "old_name": str,
            "new_name": str,
            "will_update" / "updated": int,  # 影响行数
            "affected_chapters": [chapter_id, ...],
        }

    Raises:
        ValidationError: new_name == old_name / new_name 为空
        NotFoundError:   project 或 old_name 不存在
    """
    if not old_name or not new_name:
        raise ValidationError("old_name 和 new_name 都必须非空")
    if old_name == new_name:
        raise ValidationError("新名字与旧名字相同")

    project_service.get(project_id)  # 404 guard

    apps = chapter_service.list_entity_appearances_for_project(
        project_id, entity_name=old_name,
    )
    matched = apps.get("appearances", [])
    if not matched:
        raise NotFoundError(f"Entity {old_name!r} in project {project_id}", "")

    affected_chapters = sorted({a["chapter_id"] for a in matched})
    if dry_run:
        return {
            "old_name": old_name,
            "new_name": new_name,
            "will_update": len(matched),
            "affected_chapters": affected_chapters,
        }

    # 真改: 走 service 层
    updated = 0
    for a in matched:
        try:
            # entity_appearances 没有专门的 update service, 走 L2 services.db
            from app.db import _impl as _db_conn
            with _db_conn.transaction() as db:
                db.execute(
                    "UPDATE entity_appearances SET entity_name = ? "
                    "WHERE id = ?",
                    (new_name, a["id"]),
                )
            updated += 1
        except Exception as e:
            log.warning(f"[reshape_entity] failed on {a['id']}: {e}")
    log.info(f"[reshape_entity] {old_name!r} -> {new_name!r}: {updated} rows")
    return {
        "old_name": old_name,
        "new_name": new_name,
        "updated": updated,
        "affected_chapters": affected_chapters,
    }
