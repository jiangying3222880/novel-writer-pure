"""
Chapter service - chapter CRUD + brief + L1-L4 memory.

This is the largest service because the chapter table also stores the
draft/final/critique/checkpoint text and a chapter_briefs row summarises
each chapter.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError, ValidationError
from app.services import book_service

VALID_STATUSES = {"draft", "generated", "critiqued", "persisted", "reviewed"}
VALID_TIERS = {"L1", "L2", "L3", "L4"}
# Phase 3 M0 additions
VALID_DRAFT_SOURCES = {"agent", "user", "paragraph_rewrite", "merge"}
VALID_CHANGE_TYPES = {"regen", "paragraph_rewrite", "manual_edit", "entity_reshape"}
VALID_SCOPES = {"chapter", "paragraph"}
VALID_ENTITY_TYPES = {"character", "location", "item", "faction"}


def _now() -> str:
    # Millisecond precision so two back-to-back writes (e.g. add_change_log
    # twice in a test) get distinct timestamps and ORDER BY DESC is stable.
    # Schema defaults use datetime('now', 'localtime') which is second-level;
    # service code always passes `now` explicitly, so precision is consistent.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


# --------------------------------------------------------------------- #
# Chapter CRUD
# --------------------------------------------------------------------- #

def create(book_id: str, chapter_no: int,
           title: Optional[str] = None,
           scene_context: Optional[str] = None,
           status: str = "draft",
           source_unit_id: Optional[str] = None,
           split_version: int = 0,
           is_current_version: int = 1) -> dict:
    """Create a new chapter in a book."""
    book_service.get(book_id)  # 404 guard
    if status not in VALID_STATUSES:
        raise ValidationError(f"status must be one of {VALID_STATUSES}")
    chapter_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO chapters
               (id, book_id, chapter_no, status, title, scene_context,
                source_unit_id, split_version, is_current_version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chapter_id, book_id, chapter_no, status, title, scene_context,
             source_unit_id or "", split_version, is_current_version,
             now, now),
        )
    return get(chapter_id)


def list_for_book(book_id: str) -> dict:
    """List chapters in a book ordered by chapter_no."""
    book_service.get(book_id)  # 404 guard
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_no",
            (book_id,),
        ).fetchall()
    return {"chapters": [dict(r) for r in rows], "total": len(rows)}


def get(chapter_id: str) -> dict:
    """Fetch a single chapter. Raises NotFoundError."""
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    if not row:
        raise NotFoundError("Chapter", chapter_id)
    return dict(row)


def update(chapter_id: str, **fields) -> dict:
    """Update any subset of chapter fields."""
    allowed = {
        "chapter_no", "title", "scene_context", "status",
        "draft", "final", "critique", "checkpoint",
        "word_count", "review_flag",
        "source_unit_id", "split_version", "is_current_version",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise ValidationError(f"status must be one of {VALID_STATUSES}")
    if not updates:
        return get(chapter_id)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [chapter_id]
    with _db_conn.transaction() as db:
        cur = db.execute(
            f"UPDATE chapters SET {set_clause} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            raise NotFoundError("Chapter", chapter_id)
    return get(chapter_id)


def delete(chapter_id: str) -> None:
    """Delete a chapter (cascades to brief + memory + subtext)."""
    with _db_conn.transaction() as db:
        cur = db.execute("DELETE FROM chapters WHERE id = ?", (chapter_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Chapter", chapter_id)


# --------------------------------------------------------------------- #
# Chapter brief (大纲)
# --------------------------------------------------------------------- #

def get_brief(chapter_id: str) -> dict:
    """Get the brief for a chapter. Raises NotFoundError if either the
    chapter or its brief is missing."""
    get(chapter_id)  # 404 guard
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapter_briefs WHERE chapter_id = ?", (chapter_id,)
        ).fetchone()
    if not row:
        raise NotFoundError("Brief for chapter", chapter_id)
    return dict(row)


def upsert_brief(chapter_id: str, **fields) -> dict:
    """Create or update the brief row for a chapter."""
    get(chapter_id)  # 404 guard
    allowed = {"brief", "core_events", "emotion_arc", "volume_no"}
    payload = {k: v for k, v in fields.items() if k in allowed}
    with _db_conn.connection() as db:
        existing = db.execute(
            "SELECT * FROM chapter_briefs WHERE chapter_id = ?", (chapter_id,)
        ).fetchone()
    if existing:
        if payload:
            set_clause = ", ".join(f"{k} = ?" for k in payload)
            values = list(payload.values()) + [existing["id"]]
            with _db_conn.transaction() as db:
                db.execute(
                    f"UPDATE chapter_briefs SET {set_clause} WHERE id = ?", values
                )
        return get_brief(chapter_id)
    else:
        brief_id = str(uuid.uuid4())
        now = _now()
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO chapter_briefs
                   (id, chapter_id, brief, core_events, emotion_arc, volume_no, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (brief_id, chapter_id,
                 payload.get("brief"),
                 payload.get("core_events"),
                 payload.get("emotion_arc"),
                 payload.get("volume_no"),
                 now),
            )
        return get_brief(chapter_id)


# --------------------------------------------------------------------- #
# Agent memory (L1-L4)
# --------------------------------------------------------------------- #

def list_memory(chapter_id: str, tier: Optional[str] = None) -> dict:
    """List memory entries for a chapter, optionally filtered by tier."""
    get(chapter_id)  # 404 guard
    if tier is not None and tier not in VALID_TIERS:
        raise ValidationError(f"tier must be one of {VALID_TIERS}")
    with _db_conn.connection() as db:
        if tier:
            rows = db.execute(
                "SELECT * FROM agent_memory WHERE chapter_id = ? AND tier = ? "
                "ORDER BY created_at",
                (chapter_id, tier),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM agent_memory WHERE chapter_id = ? "
                "ORDER BY tier, created_at",
                (chapter_id,),
            ).fetchall()
    return {"memories": [dict(r) for r in rows], "total": len(rows)}


def add_memory(chapter_id: str, tier: str, content: str,
               entity_type: Optional[str] = None,
               entity_name: Optional[str] = None,
               token_count: int = 0) -> dict:
    """Add an L1-L4 memory entry for a chapter."""
    get(chapter_id)  # 404 guard
    if tier not in VALID_TIERS:
        raise ValidationError(f"tier must be one of {VALID_TIERS}")
    mem_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO agent_memory
               (id, chapter_id, tier, entity_type, entity_name,
                content, token_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem_id, chapter_id, tier, entity_type, entity_name,
             content, token_count, now, now),
        )
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM agent_memory WHERE id = ?", (mem_id,)
        ).fetchone()
    return dict(row)


# --------------------------------------------------------------------- #
# Chapter drafts (Phase 3 M0: 多版本快照 / 段落重写 / 重生成)
# --------------------------------------------------------------------- #

def create_draft(chapter_id: str, content: str, source: str,
                 parent_draft_id: Optional[str] = None) -> dict:
    """Create a new draft. version_no auto-assigned as MAX+1.

    Raises NotFoundError if chapter_id doesn't exist.
    Raises ValidationError if source is invalid or parent_draft_id
    is set but doesn't belong to the same chapter.
    """
    get(chapter_id)  # 404 guard
    if source not in VALID_DRAFT_SOURCES:
        raise ValidationError(f"source must be one of {VALID_DRAFT_SOURCES}")
    if parent_draft_id is not None:
        parent = get_draft(parent_draft_id)
        if parent["chapter_id"] != chapter_id:
            raise ValidationError(
                "parent_draft_id belongs to a different chapter"
            )
    draft_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        max_row = db.execute(
            "SELECT COALESCE(MAX(version_no), 0) FROM chapter_drafts "
            "WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()
        new_version = max_row[0] + 1
        db.execute(
            """INSERT INTO chapter_drafts
               (id, chapter_id, version_no, content, source,
                parent_draft_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (draft_id, chapter_id, new_version, content, source,
             parent_draft_id, now),
        )
    return get_draft(draft_id)


def list_drafts(chapter_id: str) -> dict:
    """List all drafts for a chapter, ordered by version_no ascending."""
    get(chapter_id)  # 404 guard
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM chapter_drafts WHERE chapter_id = ? "
            "ORDER BY version_no",
            (chapter_id,),
        ).fetchall()
    return {"drafts": [dict(r) for r in rows], "total": len(rows)}


def get_draft(draft_id: str) -> dict:
    """Fetch a single draft. Raises NotFoundError."""
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapter_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
    if not row:
        raise NotFoundError("Draft", draft_id)
    return dict(row)


def get_current_draft(chapter_id: str) -> Optional[dict]:
    """Return the chapter's current_draft_id row, or None if not set."""
    with _db_conn.connection() as db:
        row = db.execute(
            """SELECT d.* FROM chapter_drafts d
               JOIN chapters c ON c.current_draft_id = d.id
               WHERE c.id = ?""",
            (chapter_id,),
        ).fetchone()
    return dict(row) if row else None


def set_current_draft(chapter_id: str, draft_id: str) -> dict:
    """Point the chapter's current_draft_id at the given draft.

    Use this for both "set initial current" and "rollback". Caller is
    responsible for writing a chapter_change_log entry separately.
    """
    get(chapter_id)  # 404 guard
    get_draft(draft_id)  # 404 guard
    now = _now()
    with _db_conn.transaction() as db:
        cur = db.execute(
            "UPDATE chapters SET current_draft_id = ?, updated_at = ? "
            "WHERE id = ?",
            (draft_id, now, chapter_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Chapter", chapter_id)
    return get_draft(draft_id)


# --------------------------------------------------------------------- #
# Change log (Phase 3 M0: 审计/回溯)
# --------------------------------------------------------------------- #

def add_change_log(chapter_id: str, change_type: str, scope: str,
                   target_draft_id: Optional[str] = None,
                   note: Optional[str] = None) -> dict:
    """Record a change. Note: doesn't mutate chapters; pure audit log."""
    get(chapter_id)  # 404 guard
    if change_type not in VALID_CHANGE_TYPES:
        raise ValidationError(f"change_type must be one of {VALID_CHANGE_TYPES}")
    if scope not in VALID_SCOPES:
        raise ValidationError(f"scope must be one of {VALID_SCOPES}")
    if target_draft_id is not None:
        target = get_draft(target_draft_id)
        if target["chapter_id"] != chapter_id:
            raise ValidationError(
                "target_draft_id belongs to a different chapter"
            )
    log_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO chapter_change_log
               (id, chapter_id, change_type, scope, target_draft_id, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (log_id, chapter_id, change_type, scope, target_draft_id, note, now),
        )
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM chapter_change_log WHERE id = ?", (log_id,)
        ).fetchone()
    return dict(row)


def list_change_log(chapter_id: str,
                    change_type: Optional[str] = None) -> dict:
    """List change log entries for a chapter, newest first.

    Optionally filtered by change_type ('regen' / 'paragraph_rewrite' / ...).
    """
    get(chapter_id)  # 404 guard
    if change_type is not None and change_type not in VALID_CHANGE_TYPES:
        raise ValidationError(f"change_type must be one of {VALID_CHANGE_TYPES}")
    with _db_conn.connection() as db:
        if change_type:
            rows = db.execute(
                "SELECT * FROM chapter_change_log WHERE chapter_id = ? "
                "AND change_type = ? ORDER BY created_at DESC",
                (chapter_id, change_type),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM chapter_change_log WHERE chapter_id = ? "
                "ORDER BY created_at DESC",
                (chapter_id,),
            ).fetchall()
    return {"logs": [dict(r) for r in rows], "total": len(rows)}


# --------------------------------------------------------------------- #
# Entity appearances (Phase 3 M0: 实体重塑 / 扫前后)
# --------------------------------------------------------------------- #

def _verify_chapter_belongs_to_project(chapter_id: str, project_id: str) -> None:
    """Raise ValidationError if chapter isn't in the given project."""
    with _db_conn.connection() as db:
        row = db.execute(
            """SELECT b.project_id FROM chapters c
               JOIN books b ON c.book_id = b.id
               WHERE c.id = ?""",
            (chapter_id,),
        ).fetchone()
    if not row:
        raise NotFoundError("Chapter", chapter_id)
    if row["project_id"] != project_id:
        raise ValidationError(
            f"chapter {chapter_id} does not belong to project {project_id}"
        )


def add_entity_appearance(project_id: str, entity_type: str, entity_name: str,
                          chapter_id: str, draft_id: Optional[str] = None,
                          paragraph_index: Optional[int] = None) -> dict:
    """Record that an entity appears in a chapter (optionally at a paragraph)."""
    get(chapter_id)  # 404 guard
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValidationError(f"entity_type must be one of {VALID_ENTITY_TYPES}")
    if draft_id is not None:
        d = get_draft(draft_id)
        if d["chapter_id"] != chapter_id:
            raise ValidationError(
                "draft_id belongs to a different chapter"
            )
    _verify_chapter_belongs_to_project(chapter_id, project_id)
    appearance_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO entity_appearances
               (id, project_id, entity_type, entity_name, chapter_id,
                draft_id, paragraph_index, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (appearance_id, project_id, entity_type, entity_name, chapter_id,
             draft_id, paragraph_index, now),
        )
    with _db_conn.connection() as db:
        row = db.execute(
            "SELECT * FROM entity_appearances WHERE id = ?", (appearance_id,)
        ).fetchone()
    return dict(row)


def list_entity_appearances_for_project(
    project_id: str, entity_name: Optional[str] = None
) -> dict:
    """List all appearances in a project, optionally filtered by entity_name.

    If entity_name is set, returns appearances of that one entity across
    the whole project (used by 实体重塑 to find all affected chapters).
    """
    with _db_conn.connection() as db:
        if entity_name:
            rows = db.execute(
                "SELECT * FROM entity_appearances WHERE project_id = ? "
                "AND entity_name = ? "
                "ORDER BY created_at",
                (project_id, entity_name),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM entity_appearances WHERE project_id = ? "
                "ORDER BY entity_name, created_at",
                (project_id,),
            ).fetchall()
    return {"appearances": [dict(r) for r in rows], "total": len(rows)}


def list_entity_appearances_for_chapter(chapter_id: str) -> dict:
    """List all entity appearances in a chapter, ordered by entity_name."""
    get(chapter_id)  # 404 guard
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM entity_appearances WHERE chapter_id = ? "
            "ORDER BY entity_name",
            (chapter_id,),
        ).fetchall()
    return {"appearances": [dict(r) for r in rows], "total": len(rows)}
