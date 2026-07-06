"""
Story Unit Service v2
- Unit CRUD with dual timeline (story_order + present_order)
- State machine: draft -> outlining -> writing -> completed -> split
- Entry/exit state management
- Cascade rules for delete/rewrite
- Integration with unit_paragraph_service

Source of truth: units + paragraphs. Chapters are views.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.db.models import StoryUnitV2, UnitBrief
from app.services import unit_paragraph_service as _para_svc
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.story_unit_v2")

VALID_STATUSES = {"draft", "outlining", "writing", "completed", "split"}
VALID_TYPES = {
    "battle", "romance", "reveal", "transition",
    "climax", "setup", "payoff", "filler", "other",
}
VALID_TRANSITIONS = {
    "direct", "time_jump", "pov_switch", "flashback",
    "parallel", "chekhov", "contrast", "suspense_front",
}
TRANSITION_LABELS = {
    "direct": "直接衔接",
    "time_jump": "时间跳接",
    "pov_switch": "视角切换",
    "flashback": "倒叙/回想",
    "parallel": "并行线",
    "chekhov": "伏笔衔接",
    "contrast": "反差衔接",
    "suspense_front": "悬念前置",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_unit(row) -> StoryUnitV2:
    return StoryUnitV2(
        id=row["id"],
        project_id=row["project_id"],
        book_id=row["book_id"] or "",
        unit_no=row["unit_no"] or 0,
        title=row["title"] or "",
        unit_type=row["unit_type"] or "other",
        story_order=row["story_order"] or 0,
        present_order=row["present_order"] or 0,
        status=row["status"] or "draft",
        synopsis=row["synopsis"] or "",
        draft=row["draft"] or "",
        word_count=row["word_count"] or 0,
        emotion_basis=row["emotion_basis"] or "",
        transition_type=row["transition_type"] or "direct",
        transition_text=row["transition_text"] or "",
        pov_character=row["pov_character"] or "",
        timeline_label=row["timeline_label"] or "现在",
        entry_characters=row["entry_characters"] or "",
        entry_world=row["entry_world"] or "",
        entry_commitments=row["entry_commitments"] or "",
        exit_characters=row["exit_characters"] or "",
        exit_world=row["exit_world"] or "",
        exit_commitments=row["exit_commitments"] or "",
        unit_memories=row["unit_memories"] or "",
        target_chars=row["target_chars"] or 5000,
        target_chapter_count=row["target_chapter_count"] or 0,
        current_step=row["current_step"] or 0,
        total_steps=row["total_steps"] or 0,
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _row_to_brief(row) -> UnitBrief:
    return UnitBrief(
        id=row["id"],
        unit_id=row["unit_id"],
        project_id=row["project_id"],
        brief=row["brief"] or "",
        core_events=row["core_events"] or "[]",
        emotion_arc=row["emotion_arc"] or "",
        cause_summary=row["cause_summary"] or "",
        effect_summary=row["effect_summary"] or "",
        hooks_planned_plant=row["hooks_planned_plant"] or "[]",
        hooks_planned_pay=row["hooks_planned_pay"] or "[]",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# ============================================================
# Unit CRUD
# ============================================================

def create(
    project_id: str,
    title: str,
    *,
    book_id: str = "",
    unit_type: str = "other",
    synopsis: str = "",
) -> StoryUnitV2:
    """Create a new story unit. Auto-appends to both timelines."""
    if not project_id:
        raise ValidationError("project_id required")
    if not title or not title.strip():
        raise ValidationError("title required")
    if unit_type not in VALID_TYPES:
        raise ValidationError(f"unit_type must be one of {VALID_TYPES}")

    unit_id = _new_id()
    now = _now()

    # Auto compute order values (append to end)
    db = _db_conn.get_conn()
    row = db.execute(
        """
        SELECT COALESCE(MAX(story_order), 0) AS ms,
               COALESCE(MAX(present_order), 0) AS mp
        FROM story_units WHERE project_id = ? AND book_id = ?
        """,
        (project_id, book_id),
    ).fetchone()
    next_story = (row["ms"] or 0) + 1
    next_present = (row["mp"] or 0) + 1

    # Compute unit_no
    row2 = db.execute(
        "SELECT COALESCE(MAX(unit_no), 0) AS mn FROM story_units WHERE project_id = ? AND book_id = ?",
        (project_id, book_id),
    ).fetchone()
    next_unit_no = (row2["mn"] or 0) + 1

    with _db_conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO story_units
                (id, project_id, book_id, unit_no, title, unit_type,
                 story_order, present_order, status, synopsis,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (unit_id, project_id, book_id, next_unit_no, title.strip(), unit_type,
             next_story, next_present, synopsis, now, now),
        )

    _logger.info("Created unit: %s (%s) @ project %s", title, unit_id, project_id)
    return get(unit_id)


def get(unit_id: str) -> StoryUnitV2:
    """Get a unit by ID."""
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT * FROM story_units WHERE id = ?", (unit_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("StoryUnit", unit_id)
    return _row_to_unit(row)


def list_for_project(
    project_id: str,
    *,
    book_id: str = "",
    order_by: str = "present",
) -> list[StoryUnitV2]:
    """
    List all units for a project.
    order_by: 'present' (default) or 'story'
    """
    if not project_id:
        raise ValidationError("project_id required")

    if order_by == "story":
        order_col = "story_order"
    else:
        order_col = "present_order"

    db = _db_conn.get_conn()
    if book_id:
        rows = db.execute(
            f"SELECT * FROM story_units WHERE project_id = ? AND book_id = ? ORDER BY {order_col} ASC",
            (project_id, book_id),
        ).fetchall()
    else:
        rows = db.execute(
            f"SELECT * FROM story_units WHERE project_id = ? ORDER BY {order_col} ASC",
            (project_id,),
        ).fetchall()
    return [_row_to_unit(r) for r in rows]


def update(unit_id: str, **fields) -> StoryUnitV2:
    """Update unit fields."""
    allowed = {
        "title", "unit_type", "status", "synopsis", "draft", "word_count",
        "book_id", "unit_no", "story_order", "present_order",
        "emotion_basis", "transition_type", "transition_text",
        "pov_character", "timeline_label",
        "entry_characters", "entry_world", "entry_commitments",
        "exit_characters", "exit_world", "exit_commitments",
        "unit_memories", "target_chars", "target_chapter_count",
        "current_step", "total_steps",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise ValidationError(f"status must be one of {VALID_STATUSES}")
    if "unit_type" in updates and updates["unit_type"] not in VALID_TYPES:
        raise ValidationError(f"unit_type must be one of {VALID_TYPES}")
    if "transition_type" in updates and updates["transition_type"] not in VALID_TRANSITIONS:
        raise ValidationError(f"transition_type must be one of {VALID_TRANSITIONS}")

    if not updates:
        return get(unit_id)

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [unit_id]

    with _db_conn.transaction() as tx:
        cur = tx.execute(
            f"UPDATE story_units SET {set_clause} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            raise NotFoundError("StoryUnit", unit_id)

    return get(unit_id)


# ============================================================
# Delete (with cascade options)
# ============================================================

class DeleteOption:
    DELETE_CHAPTERS = "delete_chapters"
    DETACH_CHAPTERS = "detach_chapters"
    CANCEL = "cancel"


def delete(unit_id: str, option: str = DeleteOption.DELETE_CHAPTERS) -> bool:
    """
    Delete a unit with cascade handling.

    Options:
    - DELETE_CHAPTERS: delete unit + all derived chapters (full cleanup)
    - DETACH_CHAPTERS: delete unit but keep chapters as independent (source_unit_id -> '')

    Always cleans up: unit_briefs, unit_writing_snapshots, unit_paragraphs,
    unit_causal_edges, unit_hook_map, and non-locked memories.
    """
    if option == DeleteOption.CANCEL:
        return False

    unit = get(unit_id)

    with _db_conn.transaction() as tx:
        # 1. Cascade delete unit-side data
        tx.execute("DELETE FROM unit_briefs WHERE unit_id = ?", (unit_id,))
        tx.execute("DELETE FROM unit_writing_snapshots WHERE unit_id = ?", (unit_id,))
        tx.execute("DELETE FROM unit_paragraphs WHERE unit_id = ?", (unit_id,))
        tx.execute(
            "DELETE FROM unit_causal_edges WHERE from_unit_id = ? OR to_unit_id = ?",
            (unit_id, unit_id),
        )
        tx.execute("DELETE FROM unit_hook_map WHERE unit_id = ?", (unit_id,))

        # 2. Handle memories: delete non-locked, detach locked ones
        tx.execute(
            "DELETE FROM agent_memories WHERE unit_id = ? AND manual_locked = 0",
            (unit_id,),
        )
        tx.execute(
            "UPDATE agent_memories SET unit_id = '' WHERE unit_id = ? AND manual_locked = 1",
            (unit_id,),
        )
        tx.execute(
            "DELETE FROM agent_memory WHERE unit_id = ? AND manual_locked = 0",
            (unit_id,),
        )
        tx.execute(
            "UPDATE agent_memory SET unit_id = '' WHERE unit_id = ? AND manual_locked = 1",
            (unit_id,),
        )

        # 3. Handle chapters
        if option == DeleteOption.DELETE_CHAPTERS:
            tx.execute(
                "DELETE FROM chapters WHERE source_unit_id = ?", (unit_id,)
            )
        elif option == DeleteOption.DETACH_CHAPTERS:
            tx.execute(
                "UPDATE chapters SET source_unit_id = '' WHERE source_unit_id = ?",
                (unit_id,),
            )

        # 4. Delete the unit itself
        cur = tx.execute("DELETE FROM story_units WHERE id = ?", (unit_id,))
        if cur.rowcount == 0:
            raise NotFoundError("StoryUnit", unit_id)

        # 5. Re-number unit_no for remaining units in the same book
        remaining = tx.execute(
            """
            SELECT id FROM story_units
            WHERE project_id = ? AND book_id = ?
            ORDER BY present_order ASC
            """,
            (unit.project_id, unit.book_id),
        ).fetchall()
        for idx, row in enumerate(remaining, start=1):
            tx.execute(
                "UPDATE story_units SET unit_no = ?, updated_at = ? WHERE id = ?",
                (idx, _now(), row["id"]),
            )

    _logger.info("Deleted unit: %s (option=%s)", unit_id, option)
    return True


# ============================================================
# Dual timeline ordering
# ============================================================

def reorder(
    project_id: str,
    ordered_ids: list[str],
    *,
    order_type: str = "present",
    book_id: str = "",
) -> bool:
    """
    Reorder units.
    order_type: 'present' (default) or 'story'
    Re-numbers starting from 1.
    """
    if not project_id:
        raise ValidationError("project_id required")
    if not ordered_ids:
        return True
    if order_type not in ("present", "story"):
        raise ValidationError("order_type must be 'present' or 'story'")

    col = "present_order" if order_type == "present" else "story_order"
    now = _now()

    with _db_conn.transaction() as tx:
        for idx, uid in enumerate(ordered_ids, start=1):
            tx.execute(
                f"UPDATE story_units SET {col} = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (idx, now, uid, project_id),
            )

        # If reordering present_order, also update unit_no
        if order_type == "present":
            for idx, uid in enumerate(ordered_ids, start=1):
                tx.execute(
                    "UPDATE story_units SET unit_no = ? WHERE id = ? AND project_id = ?",
                    (idx, uid, project_id),
                )

    _logger.info(
        "Reordered units: project=%s type=%s count=%d",
        project_id, order_type, len(ordered_ids),
    )
    return True


def move_unit(
    project_id: str,
    unit_id: str,
    new_index: int,
    *,
    order_type: str = "present",
    book_id: str = "",
) -> bool:
    """Move a single unit to new_index (0-based)."""
    units = list_for_project(project_id, book_id=book_id, order_by=order_type)
    ids = [u.id for u in units]
    if unit_id not in ids:
        raise NotFoundError("StoryUnit", unit_id)

    ids.remove(unit_id)
    new_index = max(0, min(new_index, len(ids)))
    ids.insert(new_index, unit_id)

    return reorder(project_id, ids, order_type=order_type, book_id=book_id)


def get_prev_unit(unit_id: str, order_type: str = "present") -> Optional[StoryUnitV2]:
    """Get the previous unit in timeline order."""
    unit = get(unit_id)
    units = list_for_project(unit.project_id, book_id=unit.book_id, order_by=order_type)
    ids = [u.id for u in units]
    idx = ids.index(unit_id) if unit_id in ids else -1
    if idx <= 0:
        return None
    return units[idx - 1]


def get_next_unit(unit_id: str, order_type: str = "present") -> Optional[StoryUnitV2]:
    """Get the next unit in timeline order."""
    unit = get(unit_id)
    units = list_for_project(unit.project_id, book_id=unit.book_id, order_by=order_type)
    ids = [u.id for u in units]
    idx = ids.index(unit_id) if unit_id in ids else -1
    if idx < 0 or idx >= len(units) - 1:
        return None
    return units[idx + 1]


# ============================================================
# State machine
# ============================================================

def transition_status(unit_id: str, new_status: str) -> StoryUnitV2:
    """Transition unit status (validates transitions)."""
    if new_status not in VALID_STATUSES:
        raise ValidationError(f"status must be one of {VALID_STATUSES}")

    unit = get(unit_id)
    return update(unit_id, status=new_status)


def start_outlining(unit_id: str) -> StoryUnitV2:
    return transition_status(unit_id, "outlining")


def start_writing(unit_id: str) -> StoryUnitV2:
    return transition_status(unit_id, "writing")


def mark_completed(unit_id: str) -> StoryUnitV2:
    return transition_status(unit_id, "completed")


def mark_split(unit_id: str) -> StoryUnitV2:
    return transition_status(unit_id, "split")


# ============================================================
# Unit brief (outline)
# ============================================================

def get_brief(unit_id: str) -> UnitBrief:
    """Get unit brief. Create empty one if not exists."""
    unit = get(unit_id)
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT * FROM unit_briefs WHERE unit_id = ?", (unit_id,)
    ).fetchone()

    if row:
        return _row_to_brief(row)

    # Auto-create
    brief_id = _new_id()
    now = _now()
    with _db_conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO unit_briefs
                (id, unit_id, project_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (brief_id, unit_id, unit.project_id, now, now),
        )

    return get_brief(unit_id)


def update_brief(unit_id: str, **fields) -> UnitBrief:
    """Update unit brief fields."""
    allowed = {
        "brief", "core_events", "emotion_arc",
        "cause_summary", "effect_summary",
        "hooks_planned_plant", "hooks_planned_pay",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_brief(unit_id)

    brief = get_brief(unit_id)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [brief.id]

    with _db_conn.transaction() as tx:
        tx.execute(f"UPDATE unit_briefs SET {set_clause} WHERE id = ?", values)

    return get_brief(unit_id)


# ============================================================
# Entry/exit state (JSON helpers)
# ============================================================

def _parse_json(text: str) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_json_list(text: str) -> list:
    if not text:
        return []
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_entry_characters(unit_id: str) -> dict:
    unit = get(unit_id)
    return _parse_json(unit.entry_characters)


def set_entry_characters(unit_id: str, characters: dict) -> StoryUnitV2:
    return update(unit_id, entry_characters=json.dumps(characters, ensure_ascii=False))


def get_exit_characters(unit_id: str) -> dict:
    unit = get(unit_id)
    return _parse_json(unit.exit_characters)


def set_exit_characters(unit_id: str, characters: dict) -> StoryUnitV2:
    return update(unit_id, exit_characters=json.dumps(characters, ensure_ascii=False))


def get_entry_world(unit_id: str) -> dict:
    unit = get(unit_id)
    return _parse_json(unit.entry_world)


def set_entry_world(unit_id: str, world: dict) -> StoryUnitV2:
    return update(unit_id, entry_world=json.dumps(world, ensure_ascii=False))


def get_exit_world(unit_id: str) -> dict:
    unit = get(unit_id)
    return _parse_json(unit.exit_world)


def set_exit_world(unit_id: str, world: dict) -> StoryUnitV2:
    return update(unit_id, exit_world=json.dumps(world, ensure_ascii=False))


def get_entry_commitments(unit_id: str) -> list:
    unit = get(unit_id)
    return _parse_json_list(unit.entry_commitments)


def set_entry_commitments(unit_id: str, commitments: list) -> StoryUnitV2:
    return update(unit_id, entry_commitments=json.dumps(commitments, ensure_ascii=False))


def get_exit_commitments(unit_id: str) -> list:
    unit = get(unit_id)
    return _parse_json_list(unit.exit_commitments)


def set_exit_commitments(unit_id: str, commitments: list) -> StoryUnitV2:
    return update(unit_id, exit_commitments=json.dumps(commitments, ensure_ascii=False))


def inherit_entry_from_prev(unit_id: str, order_type: str = "story") -> StoryUnitV2:
    """Inherit entry state from previous unit's exit state."""
    prev = get_prev_unit(unit_id, order_type=order_type)
    if not prev:
        raise ValidationError("No previous unit to inherit from")

    return update(
        unit_id,
        entry_characters=prev.exit_characters,
        entry_world=prev.exit_world,
        entry_commitments=prev.exit_commitments,
    )


# ============================================================
# Unit memories (unit-specific memory)
# ============================================================

def get_unit_memories(unit_id: str) -> list[dict]:
    unit = get(unit_id)
    return _parse_json_list(unit.unit_memories)


def add_unit_memory(unit_id: str, category: str, content: str) -> list[dict]:
    memories = get_unit_memories(unit_id)
    memories.append({
        "id": _new_id(),
        "category": category,
        "content": content,
        "created_at": _now(),
    })
    update(unit_id, unit_memories=json.dumps(memories, ensure_ascii=False))
    return memories


def remove_unit_memory(unit_id: str, memory_id: str) -> list[dict]:
    memories = get_unit_memories(unit_id)
    memories = [m for m in memories if m.get("id") != memory_id]
    update(unit_id, unit_memories=json.dumps(memories, ensure_ascii=False))
    return memories


# ============================================================
# Draft management (integrated with paragraphs)
# ============================================================

def get_draft(unit_id: str) -> str:
    """Get full draft text (assembled from paragraphs)."""
    return _para_svc.assemble_full_text(unit_id)


def save_draft(unit_id: str, draft_text: str) -> StoryUnitV2:
    """
    Save draft text. Rebuilds paragraphs from text.
    Also updates story_units.draft and word_count as cache.
    """
    unit = get(unit_id)
    _para_svc.replace_full_text(unit_id, unit.project_id, draft_text)
    word_count = len(draft_text)

    # Update the denormalized draft field for convenience
    return update(unit_id, draft=draft_text, word_count=word_count)


def get_paragraphs(unit_id: str) -> list:
    """Get all paragraphs for the unit."""
    return _para_svc.list_for_unit(unit_id)


# ============================================================
# Coherence checks
# ============================================================

def check_coherence(unit_id: str) -> dict:
    """
    Quick coherence check for a unit.
    Returns a dict with issues found.
    """
    unit = get(unit_id)
    brief = get_brief(unit_id)
    issues = []

    # Check cause/effect summary
    if not brief.cause_summary:
        issues.append({"level": "warning", "code": "no_cause", "msg": "Missing cause summary"})
    if not brief.effect_summary:
        issues.append({"level": "warning", "code": "no_effect", "msg": "Missing effect summary"})

    # Check flashback detection (present order before story order)
    prev_present = get_prev_unit(unit_id, order_type="present")
    prev_story = get_prev_unit(unit_id, order_type="story")
    if prev_present and prev_story and prev_present.id != prev_story.id:
        issues.append({
            "level": "info",
            "code": "non_linear",
            "msg": "Non-linear ordering detected (present order differs from story order)",
        })

    # Check entry state
    entry_chars = get_entry_characters(unit_id)
    if not entry_chars and unit.status in ("writing", "completed", "split"):
        issues.append({"level": "warning", "code": "no_entry_state", "msg": "No entry character state defined"})

    return {
        "unit_id": unit_id,
        "status": unit.status,
        "issues": issues,
        "is_ok": len([i for i in issues if i["level"] == "error"]) == 0,
    }
