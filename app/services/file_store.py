"""
File storage layer - 简单的 JSON 文件读写。

v4.0-P7 简化: setting_service 全部走 SQLite，file_store 仅保留:
  - load_data / save_data / delete_data (简单单文件 JSON)
  - init_project_storage (建目录)
  - save_meta / load_meta (.meta.json)
  - _get_project_dir / _base_dir (路径工具)

不再支持目录模式 (SPLITTABLE_KEYS 已删除，所有数据在 SQLite)。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional


def _base_dir() -> Path:
    try:
        from app.app_paths import get_story_dir
        return get_story_dir()
    except Exception:
        return Path.home() / ".novel-writer-pure" / "story"


BASE_DIR = _base_dir()


def _get_project_dir(project_id: str) -> Path:
    d = _base_dir() / f"project_{project_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_data(project_id: str, key: str, data: Any) -> Path:
    """保存 JSON 文件到项目目录。"""
    fp = _get_project_dir(project_id) / f"{key}.json"
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


def load_data(project_id: str, key: str) -> Optional[Any]:
    """从项目目录读取 JSON 文件。找不到返回 None。"""
    fp = _get_project_dir(project_id) / f"{key}.json"
    if fp.exists():
        return json.loads(fp.read_text(encoding="utf-8"))
    return None


def delete_data(project_id: str, key: str) -> bool:
    """删除 JSON 文件。返回是否删除成功。"""
    fp = _get_project_dir(project_id) / f"{key}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False


def save_meta(project_id: str, meta: dict) -> Path:
    """保存 .meta.json。"""
    fp = _get_project_dir(project_id) / ".meta.json"
    fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


def load_meta(project_id: str) -> Optional[dict]:
    """读取 .meta.json。"""
    fp = _get_project_dir(project_id) / ".meta.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def init_project_storage(project_id: str) -> Path:
    """初始化项目存储目录。"""
    d = _get_project_dir(project_id)
    if not (d / ".meta.json").exists():
        save_meta(project_id, {"project_id": project_id, "version": "4.0"})
    return d
