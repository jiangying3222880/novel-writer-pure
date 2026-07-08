"""
Story Recipe管理服务

提供一键创建不同创作模式的方案。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn, transaction

_logger = logging.getLogger("NovelWriter.services.story_recipe")


@dataclass
class StoryRecipe:
    """Story Recipe"""
    id: str
    name: str
    display_name: str
    description: str = ""
    genre: str = ""
    config: dict = None
    is_builtin: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if self.config is None:
            self.config = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_all() -> list[StoryRecipe]:
    """获取所有Recipe"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM story_recipes ORDER BY is_builtin DESC, name"
    ).fetchall()

    return [_row_to_recipe(row) for row in rows]


def get(recipe_id: str) -> StoryRecipe | None:
    """获取单个Recipe"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM story_recipes WHERE id = ?", (recipe_id,)
    ).fetchone()

    return _row_to_recipe(row) if row else None


def get_by_name(name: str) -> StoryRecipe | None:
    """按名称获取Recipe"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM story_recipes WHERE name = ?", (name,)
    ).fetchone()

    return _row_to_recipe(row) if row else None


def get_by_genre(genre: str) -> list[StoryRecipe]:
    """按题材获取Recipe"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM story_recipes WHERE genre = ? ORDER BY is_builtin DESC",
        (genre,),
    ).fetchall()

    return [_row_to_recipe(row) for row in rows]


def create(
    name: str,
    display_name: str,
    *,
    description: str = "",
    genre: str = "",
    config: dict | None = None,
) -> StoryRecipe:
    """创建Recipe"""
    recipe_id = str(uuid.uuid4())
    now = _now()

    with transaction() as conn:
        conn.execute(
            """INSERT INTO story_recipes
               (id, name, display_name, description, genre, config, is_builtin, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recipe_id, name, display_name, description, genre,
                json.dumps(config or {}, ensure_ascii=False),
                0, now, now,
            ),
        )

    _logger.info(f"StoryRecipe created: {recipe_id} ({name})")
    return get(recipe_id)


def update(recipe_id: str, **fields) -> StoryRecipe | None:
    """更新Recipe"""
    allowed_fields = {"name", "display_name", "description", "genre", "config"}
    updates = {k: v for k, v in fields.items() if k in allowed_fields}

    if not updates:
        return get(recipe_id)

    if "config" in updates and isinstance(updates["config"], dict):
        updates["config"] = json.dumps(updates["config"], ensure_ascii=False)

    updates["updated_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [recipe_id]

    with transaction() as conn:
        conn.execute(
            f"UPDATE story_recipes SET {set_clause} WHERE id = ?",
            values,
        )

    return get(recipe_id)


def delete(recipe_id: str) -> bool:
    """删除Recipe（仅允许删除非内置）"""
    recipe = get(recipe_id)
    if not recipe or recipe.is_builtin:
        return False

    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM story_recipes WHERE id = ?", (recipe_id,)
        )
    return cursor.rowcount > 0


def apply_recipe_to_project(recipe_id: str, project_id: str) -> dict:
    """
    将Recipe应用到项目

    Args:
        recipe_id: Recipe ID
        project_id: 项目ID

    Returns:
        dict: 应用结果
    """
    recipe = get(recipe_id)
    if not recipe:
        return {"success": False, "error": "Recipe不存在"}

    config = recipe.config
    applied = []

    # 1. 设置项目题材
    if recipe.genre:
        from app.services import project_service
        project_service.update(project_id, genre=recipe.genre)
        applied.append(f"题材: {recipe.genre}")

    # 2. 应用Capability配置
    if "capabilities" in config:
        from app.knowledge.capability import get_for_agent
        # 记录配置，实际应用在Agent执行时
        applied.append(f"Capabilities: {config['capabilities']}")

    # 3. 应用Unit Pool配置
    if "unit_pool" in config:
        applied.append(f"Unit Pool: {config['unit_pool']}")

    _logger.info(f"Recipe {recipe.name} applied to project {project_id}")
    return {"success": True, "applied": applied}


# --- 内部函数 ---

def _row_to_recipe(row) -> StoryRecipe:
    """将数据库行转换为StoryRecipe"""
    return StoryRecipe(
        id=row[0],
        name=row[1],
        display_name=row[2],
        description=row[3] or "",
        genre=row[4] or "",
        config=json.loads(row[5]) if row[5] else {},
        is_builtin=bool(row[6]),
        created_at=row[7] or "",
        updated_at=row[8] or "",
    )
