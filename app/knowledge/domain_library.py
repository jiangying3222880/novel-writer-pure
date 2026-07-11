"""
Domain Library — 知识包系统

按领域/题材组织知识文档，提供领域级别的知识检索。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.knowledge.domain_library")


@dataclass
class DomainPack:
    """领域知识包."""
    id: str
    name: str
    description: str = ""
    genre: str = ""
    tags: list[str] = field(default_factory=list)
    doc_count: int = 0
    created_at: str = ""


# 预定义领域
PRESET_DOMAINS = [
    {"name": "修仙", "genre": "仙侠", "description": "修仙体系、境界、功法、宗门知识"},
    {"name": "都市", "genre": "都市", "description": "现代都市生活、职场、情感知识"},
    {"name": "玄幻", "genre": "玄幻", "description": "玄幻世界观、力量体系、种族设定"},
    {"name": "悬疑", "genre": "悬疑", "description": "推理技巧、线索布局、反转设计"},
    {"name": "言情", "genre": "言情", "description": "情感描写、关系发展、CP设计"},
    {"name": "历史", "genre": "历史", "description": "历史事件、人物、制度、文化"},
    {"name": "科幻", "genre": "科幻", "description": "科技设定、世界观、硬科幻知识"},
]


def list_domains(project_id: str = "") -> list[DomainPack]:
    """列出所有领域知识包."""
    conn = get_conn()
    if project_id:
        rows = conn.execute(
            "SELECT * FROM knowledge_local WHERE category = 'domain' ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM knowledge_builtin WHERE category = 'domain' ORDER BY name"
        ).fetchall()

    packs = []
    for r in rows:
        packs.append(DomainPack(
            id=r.get("id", ""),
            name=r.get("name", ""),
            description=r.get("description", ""),
            genre=r.get("genre", ""),
            tags=json.loads(r.get("tags", "[]")) if r.get("tags") else [],
        ))
    return packs


def get_domain_content(domain_name: str, *, source: str = "builtin") -> str:
    """获取领域知识包的内容."""
    conn = get_conn()
    table = "knowledge_builtin" if source == "builtin" else "knowledge_local"
    row = conn.execute(
        f"SELECT content FROM {table} WHERE name = ? AND category = 'domain'",
        (domain_name,),
    ).fetchone()
    return row["content"] if row else ""


def search_by_domain(
    query: str,
    *,
    genre: str = "",
    limit: int = 5,
) -> list[dict]:
    """按领域搜索知识文档."""
    conn = get_conn()
    results = []

    for table in ("knowledge_builtin", "knowledge_local"):
        rows = conn.execute(
            f"""SELECT name, category, content, genre
                FROM {table}
                WHERE (name LIKE ? OR content LIKE ?)
                {"AND genre = ?" if genre else ""}
                LIMIT ?""",
            (f"%{query}%", f"%{query}%", genre, limit) if genre
            else (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "name": r["name"],
                "category": r["category"],
                "genre": r["genre"] or "",
                "snippet": (r["content"] or "")[:200],
            })

    return results[:limit]
