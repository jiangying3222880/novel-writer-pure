"""
Setting service - 项目级 key-value 配置 (v4.0-P6 精简版)

所有 key 走 SQLite `project_settings` 表:
  - hooks / voice_profiles / foreshadowing / notes
  - anti_rules / style_fingerprint
  - worldbuilding / characters (自由 JSON, 不再分文件)
  - plot_outline / chapter_outline / volume_outline

JSON 文件仅作 fallback (旧数据迁移前可读, 新数据不再写)
"""
from __future__ import annotations
import json
import logging
from typing import Any

from app.services import project_service
from app.db._impl import transaction
from app.services.file_store import init_project_storage, load_data

RECOGNISED_KEYS = {
    "worldbuilding",
    "characters",
    "hooks",
    "voice_profiles",
    "anti_rules",
    "style_fingerprint",
    "plot_outline",
    "chapter_outline",
    "volume_outline",
    "foreshadowing",
    "notes",
    "creation_conversation",
}


def _check_project(project_id: str) -> None:
    project_service.get(project_id)  # 404 guard
    init_project_storage(project_id)


def _db_get(project_id: str, key: str) -> Any | None:
    """从 SQLite 读 project_settings."""
    with transaction() as db:
        row = db.execute(
            "SELECT data FROM project_settings WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                return row[0]
        return None


def _db_set(project_id: str, key: str, data: Any) -> None:
    """写 SQLite project_settings."""
    data_json = json.dumps(data, ensure_ascii=False) if data is not None else None
    with transaction() as db:
        db.execute(
            """INSERT OR REPLACE INTO project_settings
               (project_id, key, data, updated_at)
               VALUES (?, ?, ?, strftime('%s', 'now'))""",
            (project_id, key, data_json),
        )


def get_setting(project_id: str, key: str) -> dict:
    """读配置。返回 {project_id, key, data}。

    v4.0-P6: 所有 key 优先从 SQLite 读，fallback JSON (旧数据迁移前)。
    """
    if key not in RECOGNISED_KEYS:
        from app.services.exceptions import ValidationError
        raise ValidationError(f"Unknown setting key: {key!r}")
    _check_project(project_id)

    # 先查 SQLite
    data = _db_get(project_id, key)
    if data is None:
        # fallback: 从 JSON 读（旧数据迁移前）
        try:
            data = load_data(project_id, key)
        except Exception:
            data = None

    return {"project_id": project_id, "key": key, "data": data}


def set_setting(project_id: str, key: str, data: Any) -> dict:
    """写配置。

    v4.0-P6: 所有 key 直接写 SQLite，不再写 JSON。
    """
    if key not in RECOGNISED_KEYS:
        from app.services.exceptions import ValidationError
        raise ValidationError(f"Unknown setting key: {key!r}")
    _check_project(project_id)

    _db_set(project_id, key, data)
    return {"project_id": project_id, "key": key, "data": data}


def migrate_json_to_sqlite(project_id: str, keys: list[str] | None = None) -> dict:
    """迁移指定 key 的 JSON 数据到 SQLite。

    Args:
        project_id: 项目 ID
        keys: 要迁移的 key 列表，默认所有 RECOGNISED_KEYS

    Returns:
        {"migrated": int, "keys": list[str]}
    """
    keys = keys or list(RECOGNISED_KEYS)
    migrated = 0
    migrated_keys: list[str] = []

    for key in keys:
        if key not in RECOGNISED_KEYS:
            continue
        # 先查 SQLite，已有数据则跳过
        existing = _db_get(project_id, key)
        if existing is not None:
            continue
        # 从 JSON 读
        try:
            data = load_data(project_id, key)
            if data is not None:
                _db_set(project_id, key, data)
                migrated += 1
                migrated_keys.append(key)
                log.debug("[setting] migrated %s for project %s", key, project_id)
        except Exception as e:
            log.warning("[setting] migrate %s failed for project %s: %s", key, project_id, e)

    return {"migrated": migrated, "keys": migrated_keys}


def migrate_all_projects() -> dict:
    """迁移所有项目的 SQLITE_KEYS 到 SQLite。

    在 main.py 启动时调用。
    """
    from app.services import project_service
    projects = project_service.list_all()
    total = 0
    migrated = 0
    for p in projects:
        pid = p.get("id")
        if not pid:
            continue
        total += 1
        res = migrate_json_to_sqlite(pid)
        migrated += res["migrated"]
    log.info("[setting] migrated %d/%d projects' JSON settings to SQLite", migrated, total)
    return {"total": total, "migrated": migrated}