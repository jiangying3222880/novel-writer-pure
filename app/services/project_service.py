"""
Project service - project CRUD.

A "project" represents a single novel. Each project owns zero or more
books (volumes), which in turn own chapters.

V4.0-P2-新: structure.json 字段全部迁到 projects 表，取消双写。
旧项目启动时自动从 structure.json 迁移到 SQLite。
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError
from app.services.file_store import init_project_storage


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_structure_file(project_id: str) -> dict:
    """读 structure.json (仅迁移/导出用，主流程不调用)。"""
    from app.services.file_store import _get_project_dir
    p = _get_project_dir(project_id) / "structure.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_structure_file(project_id: str, structure: dict) -> Path:
    """写 structure.json (仅导出/兼容用，主流程不调用)。"""
    from app.services.file_store import _get_project_dir
    p = _get_project_dir(project_id) / "structure.json"
    p.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def create(name: str, book_title: Optional[str] = None,
           genre: Optional[str] = None, platform: Optional[str] = None,
           word_target: int = 200000,
           volumes: int = 1,
           chapters_per_volume: int = 100,
           words_per_chapter: int = 2000,
           total_chapters: Optional[int] = None,
           sub_genres: Optional[list] = None,
           author: Optional[str] = None,
           create_books: bool = False,
           recipe_id: Optional[str] = None) -> dict:
    """Create a new project. Returns the new row as a dict."""
    project_id = str(uuid.uuid4())
    now = _now()
    if total_chapters is None:
        total_chapters = volumes * chapters_per_volume
    total_words = total_chapters * words_per_chapter
    sub_genres_json = json.dumps(list(sub_genres) if sub_genres else [], ensure_ascii=False)

    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO projects
               (id, name, book_title, author, genre, platform, word_target,
                sub_genres, volumes, chapters_per_volume, words_per_chapter,
                total_chapters, total_words, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, name, book_title, author, genre, platform, word_target,
             sub_genres_json, volumes, chapters_per_volume, words_per_chapter,
             total_chapters, total_words, now, now),
        )

    init_project_storage(project_id)

    # v4.2新增: 应用Story Recipe
    if recipe_id:
        try:
            from app.services.story_recipe import apply_recipe_to_project
            apply_result = apply_recipe_to_project(recipe_id, project_id)
            if apply_result.get("success"):
                _logger.info(f"Recipe {recipe_id} applied to project {project_id}")
        except Exception as e:
            _logger.warning(f"Recipe应用失败: {e}")

    if create_books and volumes > 0:
        from app.services import book_service
        for v_no in range(1, volumes + 1):
            vol_title = f"第 {v_no} 卷"
            if book_title:
                vol_title = f"{book_title} (第 {v_no} 卷)"
            book_service.create(
                project_id=project_id,
                volume_no=v_no,
                title=vol_title,
                synopsis=None,
                target_chapters=chapters_per_volume,
            )

    new_proj = get(project_id)
    _publish("project.created", project_id, new_proj)
    return new_proj


def list_all() -> dict:
    """List all projects, newest first."""
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    projects = [_row_to_dict(r) for r in rows]
    return {"projects": projects, "total": len(projects)}


def get(project_id: str) -> dict:
    """Fetch a single project. Raises NotFoundError if missing."""
    with _db_conn.connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise NotFoundError("Project", project_id)
    return _row_to_dict(row)


def update(project_id: str, **fields) -> dict:
    """Update a subset of fields.

    Recognised keys:
      - name, book_title, author, genre, platform, word_target
      - sub_genres
    """
    sql_allowed = {
        "name", "book_title", "author", "genre", "platform", "word_target",
        "sub_genres",
    }
    sql_updates = {}
    for k, v in fields.items():
        if k not in sql_allowed or v is None:
            continue
        if k == "sub_genres":
            sql_updates["sub_genres"] = json.dumps(list(v or []), ensure_ascii=False)
        else:
            sql_updates[k] = v

    if sql_updates:
        sql_updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in sql_updates)
        values = list(sql_updates.values()) + [project_id]
        with _db_conn.transaction() as db:
            cur = db.execute(
                f"UPDATE projects SET {set_clause} WHERE id = ?", values
            )
            if cur.rowcount == 0:
                raise NotFoundError("Project", project_id)

    updated = get(project_id)
    _publish("project.updated", project_id, updated)
    return updated


def _row_to_dict(row) -> dict:
    """把 SQLite Row 转成 dict，sub_genres 从 JSON 字符串解析成 list。"""
    d = dict(row)
    if "sub_genres" in d and d["sub_genres"]:
        try:
            d["sub_genres"] = json.loads(d["sub_genres"])
        except Exception:
            d["sub_genres"] = []
    else:
        d["sub_genres"] = []
    return d


def migrate_structure_json(project_id: str) -> bool:
    """把旧项目的 structure.json 迁到 SQLite。返回 True = 执行了迁移。"""
    struct = _read_structure_file(project_id)
    if not struct:
        return False

    with _db_conn.connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        return False

    current = _row_to_dict(row)
    updates = {}

    for key in ("sub_genres", "volumes", "chapters_per_volume",
                "words_per_chapter", "total_chapters", "total_words", "author"):
        if key in struct and struct[key] is not None:
            if current.get(key) in (None, [], 0, ""):
                updates[key] = struct[key]

    if not updates:
        return False

    sql_updates = {}
    for k, v in updates.items():
        if k == "sub_genres":
            sql_updates[k] = json.dumps(list(v or []), ensure_ascii=False)
        else:
            sql_updates[k] = v
    sql_updates["updated_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in sql_updates)
    values = list(sql_updates.values()) + [project_id]
    with _db_conn.transaction() as db:
        db.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)

    return True


def migrate_all_structure_json() -> dict:
    """扫描所有项目，把有 structure.json 的都迁到 SQLite。

    Returns: {"migrated": int, "total": int, "errors": list}
    """
    from app.services.file_store import _base_dir
    base = _base_dir()
    migrated = 0
    errors = []
    total = 0

    if not base.exists():
        return {"migrated": 0, "total": 0, "errors": []}

    for child in base.iterdir():
        if not child.is_dir() or not child.name.startswith("project_"):
            continue
        project_id = child.name[len("project_"):]
        total += 1
        try:
            if migrate_structure_json(project_id):
                migrated += 1
        except Exception as e:
            errors.append(f"{project_id}: {e}")

    return {"migrated": migrated, "total": total, "errors": errors}


def _publish(event: str, pid: str, project: Optional[dict] = None) -> None:
    """通知订阅者 (best-effort)。"""
    try:
        from app.services import project_event_bus
        project_event_bus.publish(event, pid, project)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("publish %s %s failed: %s", event, pid, e)


def delete(project_id: str) -> None:
    """Delete a project and all its books/chapters (cascade)."""
    with _db_conn.transaction() as db:
        cur = db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Project", project_id)
    _publish("project.deleted", project_id, None)
