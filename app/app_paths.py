"""
Application path constants and helpers.

Convention (matches the original backend/storage/file_store.py so user data
is not orphaned during the FastAPI → PySide6 migration):

  STORY_DIR:      %USERPROFILE%/.novel-writer-pure/story    (project JSON files)
  DATA_DB_DIR:    %APPDATA%/NovelWriterPure/data            (sqlite + lancedb)
  LOG_DIR:        %APPDATA%/NovelWriterPure/logs            (runtime logs)
  BACKUP_DIR:     %APPDATA%/NovelWriterPure/backups         (zipped snapshots)

可自定义目录 (P0-新): 用户可在设置 → 存储 中改 STORY_DIR / DATA_DIR
  - 存储到 app_settings.json 的 kv: storage.story_dir / storage.data_dir
  - 默认 None -> 用模块常量
  - 在 app/main.py 启动早期读出来 apply, 业务代码用 get_story_dir()/get_data_dir()
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------
# Story files (project JSON) - same location as before the refactor
# ------------------------------------------------------------------
STORY_DIR_DEFAULT = Path.home() / ".novel-writer-pure" / "story"
STORY_DIR_DEFAULT.mkdir(parents=True, exist_ok=True)
# 向后兼容: 老代码引用 STORY_DIR 不报错
STORY_DIR = STORY_DIR_DEFAULT

# ------------------------------------------------------------------
# Per-user writable app data (sqlite, logs, backups)
# ------------------------------------------------------------------
if sys.platform == "win32":
    _appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
elif sys.platform == "darwin":
    _appdata = Path.home() / "Library" / "Application Support"
else:
    _appdata = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DATA_DIR_DEFAULT = _appdata / "NovelWriterPure"

DATA_DB_DIR_DEFAULT = DATA_DIR_DEFAULT / "data"
LOG_DIR_DEFAULT = DATA_DIR_DEFAULT / "logs"
BACKUP_DIR_DEFAULT = DATA_DIR_DEFAULT / "backups"

# 向后兼容
DATA_DIR = DATA_DIR_DEFAULT
DATA_DB_DIR = DATA_DB_DIR_DEFAULT
LOG_DIR = LOG_DIR_DEFAULT
BACKUP_DIR = BACKUP_DIR_DEFAULT

for _p in (DATA_DIR, DATA_DB_DIR, LOG_DIR, BACKUP_DIR):
    _p.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# 可自定义目录 override (用户在设置里改)
# ------------------------------------------------------------------
_STORY_DIR_OVERRIDE: Optional[Path] = None
_DATA_DIR_OVERRIDE: Optional[Path] = None


def _expand(path: Optional[str | Path]) -> Optional[Path]:
    if path is None or path == "":
        return None
    p = Path(os.path.expandvars(os.path.expanduser(str(path))))
    try:
        p = p.resolve()
    except OSError:
        # 路径不存在/无法 resolve 时, 不强行 resolve
        p = Path(os.path.abspath(str(p)))
    return p


def set_story_dir_override(path: Optional[str | Path]) -> None:
    """设置项目目录 override. None = 用默认."""
    global _STORY_DIR_OVERRIDE
    _STORY_DIR_OVERRIDE = _expand(path)


def set_data_dir_override(path: Optional[str | Path]) -> None:
    """设置数据目录 override. None = 用默认."""
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = _expand(path)


def get_story_dir() -> Path:
    """拿项目目录 (override 优先, 自动 mkdir)."""
    p = _STORY_DIR_OVERRIDE if _STORY_DIR_OVERRIDE else STORY_DIR_DEFAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_dir() -> Path:
    """拿数据目录 (override 优先, 自动 mkdir)."""
    p = _DATA_DIR_OVERRIDE if _DATA_DIR_OVERRIDE else DATA_DIR_DEFAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_db_dir() -> Path:
    p = get_data_dir() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_dir() -> Path:
    p = get_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_backup_dir() -> Path:
    p = get_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_signals_dir() -> Path:
    """edit_signals 目录 (跟数据目录同根)."""
    p = get_data_dir().parent / "signals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_signals_projects_dir() -> Path:
    p = get_signals_dir() / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sqlite_path() -> Path:
    """Path to the SQLite database file."""
    return get_data_db_dir() / "novel_writer.db"


# ------------------------------------------------------------------
# 启动早期 apply override (从 app_settings.json 读出来)
# ------------------------------------------------------------------
def apply_storage_overrides_from_settings() -> None:
    """从 app_settings.json 读 storage.* key, apply 成 override.
    只在 app 启动早期调一次 (在 service init 之前).
    """
    try:
        from app.services.app_setting_service import get
        s = get("storage.story_dir")
        d = get("storage.data_dir")
        if s:
            set_story_dir_override(s)
        if d:
            set_data_dir_override(d)
    except Exception:
        # DB 未初始化等: 静默走默认
        pass


# ------------------------------------------------------------------
# 迁移工具: 把旧目录下的项目数据复制到新目录
# ------------------------------------------------------------------
def migrate_story_dir(new_path: str | Path) -> dict:
    """把 STORY_DIR_DEFAULT 的内容复制到 new_path.

    Returns: {"copied": int, "skipped": int, "errors": list[str]}
    """
    import shutil
    new = _expand(new_path)
    if new is None:
        raise ValueError("new_path 不能为空")
    new.mkdir(parents=True, exist_ok=True)
    src = STORY_DIR_DEFAULT
    if src.resolve() == new.resolve():
        return {"copied": 0, "skipped": 0, "errors": ["源和目标相同"]}
    copied = 0
    skipped = 0
    errors: list[str] = []
    if not src.exists():
        return {"copied": 0, "skipped": 0, "errors": []}
    for child in src.iterdir():
        dst = new / child.name
        try:
            if dst.exists():
                skipped += 1
                continue
            if child.is_dir():
                shutil.copytree(child, dst)
            else:
                shutil.copy2(child, dst)
            copied += 1
        except Exception as e:
            errors.append(f"{child.name}: {e}")
    return {"copied": copied, "skipped": skipped, "errors": errors}
