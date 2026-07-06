"""
Book (volume) service - CRUD on books belonging to a project.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError
from app.services import project_service


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create(project_id: str, volume_no: int, title: Optional[str] = None,
           synopsis: Optional[str] = None, target_chapters: int = 100) -> dict:
    """Create a new book in a project. Validates project exists."""
    # Will raise NotFoundError if project missing
    project_service.get(project_id)
    book_id = str(uuid.uuid4())
    now = _now()
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO books
               (id, project_id, volume_no, title, synopsis, target_chapters, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (book_id, project_id, volume_no, title, synopsis, target_chapters, now),
        )
    return get(book_id)


def list_for_project(project_id: str) -> dict:
    """List all books in a project, ordered by volume_no."""
    project_service.get(project_id)  # 404 guard
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM books WHERE project_id = ? ORDER BY volume_no",
            (project_id,),
        ).fetchall()
    return {"books": [dict(r) for r in rows], "total": len(rows)}


def get(book_id: str) -> dict:
    """Fetch one book. Raises NotFoundError if missing."""
    with _db_conn.connection() as db:
        row = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        raise NotFoundError("Book", book_id)
    return dict(row)


def update(book_id: str, **fields) -> dict:
    """Update a subset of: volume_no, title, synopsis, target_chapters."""
    allowed = {"volume_no", "title", "synopsis", "target_chapters"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get(book_id)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [book_id]
    with _db_conn.transaction() as db:
        cur = db.execute(f"UPDATE books SET {set_clause} WHERE id = ?", values)
        if cur.rowcount == 0:
            raise NotFoundError("Book", book_id)
    return get(book_id)


def delete(book_id: str) -> None:
    """Delete a book (cascades to chapters)."""
    with _db_conn.transaction() as db:
        cur = db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Book", book_id)
