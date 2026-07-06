"""
Unit Hook Service - 单元钩子/伏笔服务
基于段落 ID 锚点的钩子管理

核心设计:
- 钩子不再用字符偏移量锚定，改用段落 ID 锚定
- 每个钩子事件（plant/payoff/reminder 都是独立记录
- 支持手动锁定的钩子不会被自动生成覆盖
- 支持钩子生命周期：planned -> planted -> active -> fulfilled/abandoned
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.db.models import UnitHookMapV2 as UnitHook
from app.services.exceptions import NotFoundError, ValidationError
from app.services import unit_paragraph_service as _para_svc

_logger = logging.getLogger("NovelWriter.services.unit_hook")

VALID_HOOK_TYPES = {"plant", "payoff", "reminder", "active"}
VALID_HOOK_STATUSES = {"planned", "planted", "active", "fulfilled", "abandoned"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_hook(row) -> UnitHook:
    return UnitHook(
        id=row["id"],
        unit_id=row["unit_id"],
        project_id=row["project_id"],
        hook_id=row["hook_id"] or "",
        hook_type=row["hook_type"] or "plant",
        paragraph_id=row["paragraph_id"] or "",
        step_no=row["step_no"] or 0,
        description=row["description"] or "",
        manual_locked=bool(row["manual_locked"] or 0),
        created_at=row["created_at"] or "",
    )


# ============================================================
# Hook CRUD
# ============================================================

def add_hook(
    unit_id: str,
    hook_type: str,
    description: str,
    *,
    hook_id: str = "",
    paragraph_id: str = "",
    step_no: int = 0,
    manual_locked: bool = False,
) -> UnitHook:
    """
    Add a hook anchor to a unit.

    Args:
        unit_id: The unit this hook belongs to
        hook_type: plant / payoff / reminder / active
        description: Hook description
        hook_id: Shared hook ID (for matching plant/payoff pairs)
        paragraph_id: Paragraph anchor (stable UUID, not char offset)
        step_no: Writing step when this hook appears
        manual_locked: If True, won't be overwritten by auto-generation
    """
    if hook_type not in VALID_HOOK_TYPES:
        raise ValidationError(f"hook_type must be one of {VALID_HOOK_TYPES}")
    if not description or not description.strip():
        raise ValidationError("description required")

    # Validate unit exists
    from app.services import story_unit_service_v2 as _unit_svc
    unit = _unit_svc.get(unit_id)

    record_id = _new_id()
    shared_hook_id = hook_id or _new_id()
    now = _now()

    with _db_conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO unit_hook_map
                (id, unit_id, project_id, hook_id, hook_type,
                 paragraph_id, step_no, description, manual_locked, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, unit_id, unit.project_id, shared_hook_id, hook_type,
             paragraph_id, step_no, description.strip(),
             1 if manual_locked else 0, now),
        )

    _logger.info(
        "Added hook: type=%s unit=%s desc=%.30s",
        hook_type, unit_id, description,
    )
    return get(record_id)


def get(hook_record_id: str) -> UnitHook:
    """Get a hook record by ID."""
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT * FROM unit_hook_map WHERE id = ?", (hook_record_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("UnitHook", hook_record_id)
    return _row_to_hook(row)


def list_for_unit(unit_id: str) -> list[UnitHook]:
    """List all hooks for a unit, ordered by step_no then paragraph position."""
    db = _db_conn.get_conn()
    rows = db.execute(
        """
        SELECT uh.* FROM unit_hook_map uh
        WHERE uh.unit_id = ?
        ORDER BY uh.step_no ASC, uh.id ASC
        """,
        (unit_id,),
    ).fetchall()
    return [_row_to_hook(r) for r in rows]


def list_for_project(project_id: str, *, hook_type: str = "", hook_id: str = "") -> list[UnitHook]:
    """List hooks across all units for a project."""
    db = _db_conn.get_conn()
    query = "SELECT * FROM unit_hook_map WHERE project_id = ?"
    params = [project_id]
    if hook_type:
        query += " AND hook_type = ?"
        params.append(hook_type)
    if hook_id:
        query += " AND hook_id = ?"
        params.append(hook_id)
    query += " ORDER BY unit_id, step_no"
    rows = db.execute(query, params).fetchall()
    return [_row_to_hook(r) for r in rows]


def update(hook_id: str, *, description: Optional[str] = None,
           hook_type: Optional[str] = None,
           paragraph_id: Optional[str] = None,
           manual_locked: Optional[bool] = None) -> UnitHook:
    """Update a hook record."""
    hook = get(hook_id)
    updates = {}
    if description is not None:
        if not description.strip():
            raise ValidationError("description cannot be empty")
        updates["description"] = description.strip()
    if hook_type is not None:
        if hook_type not in VALID_HOOK_TYPES:
            raise ValidationError(f"hook_type must be one of {VALID_HOOK_TYPES}")
        updates["hook_type"] = hook_type
    if paragraph_id is not None:
        updates["paragraph_id"] = paragraph_id
    if manual_locked is not None:
        updates["manual_locked"] = 1 if manual_locked else 0

    if not updates:
        return hook

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [hook_id]

    with _db_conn.transaction() as tx:
        tx.execute(f"UPDATE unit_hook_map SET {set_clause} WHERE id = ?", values)

    return get(hook_id)


def remove(hook_id: str) -> bool:
    """Delete a hook record."""
    hook = get(hook_id)
    with _db_conn.transaction() as tx:
        tx.execute("DELETE FROM unit_hook_map WHERE id = ?", (hook_id,))
    _logger.info("Removed hook: %s", hook_id)
    return True


def clear_auto_hooks(unit_id: str) -> int:
    """
    Delete all non-manually-locked hooks for a unit.
    Called before re-generating hooks to avoid duplicates.
    Returns count of deleted hooks.
    """
    with _db_conn.transaction() as tx:
        cur = tx.execute(
            "DELETE FROM unit_hook_map WHERE unit_id = ? AND manual_locked = 0",
            (unit_id,),
        )
        count = cur.rowcount
    _logger.info("Cleared %d auto hooks for unit %s", count, unit_id)
    return count


# ============================================================
# Hook pair management (plant <-> payoff)
# ============================================================

def get_hook_pairs(unit_id: str) -> list[dict]:
    """
    Get all hooks in a unit, grouped by shared hook_id, showing plant/payoff pairs.

    Returns list of dicts:
    {
        "hook_id": "...",
        "description": "...",
        "plants": [UnitHook...],  # plant events
        "payoffs": [UnitHook...], # payoff events
        "status": "planted" / "active" / "fulfilled",
    }
    """
    hooks = list_for_unit(unit_id)
    by_hook_id: dict[str, dict] = {}

    for h in hooks:
        if h.hook_id not in by_hook_id:
            by_hook_id[h.hook_id] = {
                "hook_id": h.hook_id,
                "description": h.description,
                "plants": [],
                "payoffs": [],
                "reminders": [],
            }
        entry = by_hook_id[h.hook_id]
        if h.hook_type == "plant":
            entry["plants"].append(h)
            if h.description and not entry["description"]:
                entry["description"] = h.description
        elif h.hook_type == "payoff":
            entry["payoffs"].append(h)
        elif h.hook_type == "reminder":
            entry["reminders"].append(h)

    # Determine status
    result = []
    for hook_id, data in by_hook_id.items():
        if data["payoffs"]:
            data["status"] = "fulfilled"
        elif data["plants"] and data["reminders"]:
            data["status"] = "active"
        elif data["plants"]:
            data["status"] = "planted"
        else:
            data["status"] = "planned"
        result.append(data)

    return result


def find_unfulfilled_hooks(project_id: str, up_to_unit_id: str = "") -> list[dict]:
    """
    Find all hooks that have been planted but not yet paid off,
    up to (and not including) a given unit.

    Useful for context building: what active hooks are still unresolved?
    """
    all_hooks = list_for_project(project_id)

    # Group by hook_id
    by_hook_id: dict[str, dict] = {}
    for h in all_hooks:
        if h.hook_id not in by_hook_id:
            by_hook_id[h.hook_id] = {"plants": [], "payoffs": []}
        if h.hook_type == "plant":
            by_hook_id[h.hook_id]["plants"].append(h)
        elif h.hook_type == "payoff":
            by_hook_id[h.hook_id]["payoffs"].append(h)

    # Find unfulfilled (has plant, no payoff)
    unfulfilled = []
    for hook_id, data in by_hook_id.items():
        if data["plants"] and not data["payoffs"]:
            plant = data["plants"][0]
            unfulfilled.append({
                "hook_id": hook_id,
                "description": plant.description,
                "plant_unit_id": plant.unit_id,
                "plant_step": plant.step_no,
                "paragraph_id": plant.paragraph_id,
            })

    return unfulfilled


# ============================================================
# Paragraph anchor helpers
# ============================================================

def get_hooks_in_paragraph(paragraph_id: str) -> list[UnitHook]:
    """Get all hooks anchored to a specific paragraph."""
    db = _db_conn.get_conn()
    rows = db.execute(
        "SELECT * FROM unit_hook_map WHERE paragraph_id = ? ORDER BY step_no",
        (paragraph_id,),
    ).fetchall()
    return [_row_to_hook(r) for r in rows]


def reanchor_hooks_after_paragraph_split(
    unit_id: str,
    old_paragraph_id: str,
    new_paragraph_ids: list[str],
) -> int:
    """
    When a paragraph is split into multiple, re-anchor hooks.
    Strategy: move all hooks from old paragraph to the first new paragraph.

    Returns count of reanchored hooks.
    """
    if not new_paragraph_ids:
        return 0
    target_id = new_paragraph_ids[0]
    with _db_conn.transaction() as tx:
        cur = tx.execute(
            "UPDATE unit_hook_map SET paragraph_id = ? WHERE paragraph_id = ? AND unit_id = ?",
            (target_id, old_paragraph_id, unit_id),
        )
        count = cur.rowcount
    _logger.info(
        "Reanchored %d hooks: %s -> %s",
        count, old_paragraph_id[:8], target_id[:8],
    )
    return count


# ============================================================
# Stats
# ============================================================

def get_hook_stats(unit_id: str) -> dict:
    """Get hook statistics for a unit."""
    hooks = list_for_unit(unit_id)
    plants = [h for h in hooks if h.hook_type == "plant"]
    payoffs = [h for h in hooks if h.hook_type == "payoff"]
    reminders = [h for h in hooks if h.hook_type == "reminder"]
    locked = [h for h in hooks if h.manual_locked]

    return {
        "total": len(hooks),
        "plants": len(plants),
        "payoffs": len(payoffs),
        "reminders": len(reminders),
        "manual_locked": len(locked),
        "pairs": len(get_hook_pairs(unit_id)),
    }


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回 unit 内未兑现钩子的 Guide 列表 (供 collect_guides 接入).

    Guide 语义:
      - priority: 高 = 越该处理 (未兑现 + 接近回报期)
      - confidence: 高 = 数据可靠 (基于 step_no + plant 时间)
      - scope: Unit (钩子是 unit 级事件)
      - advice: "单元内 N 个钩子未兑现, 建议处理其中 M 个"
      - evidence_ids: 钩子 ID 列表, 可追溯到具体段落
      - possible_actions: 提供 "延后 / 立即兑现 / 放弃" 多选
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT

    try:
        hooks = list_for_unit(unit_id)
    except Exception:
        return []
    unfulfilled_plants = [
        h for h in hooks
        if h.hook_type == "plant" and not _has_payoff(hooks, h.hook_id)
    ]

    if not unfulfilled_plants:
        return []

    evidence = [h.id for h in unfulfilled_plants[:10]]
    advice = (
        f"单元内有 {len(unfulfilled_plants)} 个未兑现的伏笔钩子。"
        f"如果节奏合适, 建议在当前或下个 unit 兑现其中部分。"
    )
    if len(unfulfilled_plants) >= 3:
        advice += "钩子密度较高, AI 写作时需注意不要新增更多 plant。"

    possible_actions = [
        Action(label="当前 unit 兑现", description="立即回收部分伏笔, 缓解读者期待",
               estimated_impact={"units_affected": 1}),
        Action(label="下个 unit 兑现", description="延后到下个 unit, 留出当前 unit 推进剧情",
               estimated_impact={"units_affected": 1}),
        Action(label="延后 N 个 unit", description="再等几个 unit, 等故事铺垫更充分",
               estimated_impact={"units_affected": "n"}),
        Action(label="放弃", description="某些伏笔已无意义, 直接 abandon",
               estimated_impact={"units_affected": 0}),
    ]

    return [Guide(
        source="hook",
        priority=min(0.9, 0.4 + 0.1 * len(unfulfilled_plants)),
        confidence=0.9,
        scope=GUIDE_SCOPE_UNIT,
        advice=advice,
        reason=f"基于单元内 {len(hooks)} 个钩子事件, 其中 {len(unfulfilled_plants)} 个 plant 还未兑现",
        evidence_ids=evidence,
        possible_actions=possible_actions,
        context={
            "total_hooks": len(hooks),
            "unfulfilled_plants": len(unfulfilled_plants),
            "manual_locked_count": sum(1 for h in hooks if h.manual_locked),
        },
    )]


def _has_payoff(hooks: list, hook_id: str) -> bool:
    """检查某个 hook_id 是否已被兑现."""
    if not hook_id:
        return False
    return any(h.hook_type == "payoff" and h.hook_id == hook_id for h in hooks)
