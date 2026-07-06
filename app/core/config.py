"""
配置管理 (B 拍板: Settings 从 DB + 默认 合并)
- 启动时 load(): DB 的 app_settings 表覆盖 DEFAULT_SETTINGS
- 4.0 任何模块 get(key) 即可, 不直接 import 硬编码值
- 改 1 处配置 → UI / 改 1 行 / 重启即生效 (无需改代码)

修复 6 个硬编码 (§6 待优化清单):
- 🔴 DEFAULT_MODELS / 价格 → seed_models.json + app_settings
- 🟡 MAX_RETRIES / RETRY_DELAYS → settings.engine.*
- 🟡 log retention / maxBytes → settings.log.*
- 🟡 plugins_dir → settings.plugins.dir
- 🟡 DB 隔离级别 / journal → settings.db.*
"""
from __future__ import annotations
import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from app.core.constants import DEFAULT_SETTINGS, DirName
from app.db import connection

_logger = logging.getLogger("NovelWriter.config")

_lock = threading.Lock()
_settings: dict[str, Any] = {}
_loaded = False


# ────────────────────── 加载 / 保存 ──────────────────────

def load() -> dict:
    """
    加载设置: DEFAULT_SETTINGS 合并 app_settings 表。
    启动时调一次。
    """
    global _settings, _loaded
    with _lock:
        if _loaded:
            return _settings
        # 1) 复制默认值
        _settings = dict(DEFAULT_SETTINGS)
        # 2) 覆盖 DB 存的
        try:
            conn = connection.get_conn()
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            for r in rows:
                key = r["key"]
                raw = r["value"]
                if not raw:
                    continue
                # 尝试反序列化
                try:
                    value = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    value = raw
                _settings[key] = value
            _logger.info("加载设置: %d 项 (DB 覆盖 %d)",
                         len(_settings), len(rows))
        except Exception as e:
            _logger.warning("加载 app_settings 失败: %s (用默认)", e)
        _loaded = True
        return _settings


def get(key: str, default: Any = None) -> Any:
    """获取设置。key 不存在 → 走 DEFAULT_SETTINGS 兜底, 再走 default 参数."""
    if not _loaded:
        load()
    if key in _settings:
        return _settings[key]
    # 内存里被 delete() 弹掉了 → 用 DEFAULT_SETTINGS 兜底
    if key in DEFAULT_SETTINGS:
        return DEFAULT_SETTINGS[key]
    return default


def set(key: str, value: Any, persist: bool = True) -> None:
    """
    设置值 (内存 + 可选 DB 持久化)。
    persist=True 写到 app_settings 表, 重启不丢。
    """
    global _settings
    if not _loaded:
        load()
    with _lock:
        _settings[key] = value
        if persist:
            try:
                conn = connection.get_conn()
                raw = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                    (key, raw),
                )
            except Exception as e:
                _logger.exception("保存设置失败 %s: %s", key, e)


def delete(key: str) -> None:
    """删除 (恢复默认)。"""
    global _settings
    if not _loaded:
        load()
    with _lock:
        _settings.pop(key, None)
        try:
            conn = connection.get_conn()
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        except Exception as e:
            _logger.exception("删除设置失败 %s: %s", key, e)


def reset_all() -> None:
    """重置所有 (恢复默认)。"""
    global _settings, _loaded
    with _lock:
        _settings = dict(DEFAULT_SETTINGS)
        try:
            conn = connection.get_conn()
            conn.execute("DELETE FROM app_settings")
        except Exception:
            pass
        _loaded = True


def all_keys() -> list[str]:
    if not _loaded:
        load()
    return sorted(_settings.keys())


# ────────────────────── 启动校验 ──────────────────────

def validate() -> list[str]:
    """
    校验关键配置。
    返回错误列表 (空 = 通过)。
    启动时调, 有错打 WARN 但不阻止启动。
    """
    errors = []
    # 引擎
    if not isinstance(get("engine.max_retries"), int) or get("engine.max_retries") < 1:
        errors.append(f"engine.max_retries 应为正整数: {get('engine.max_retries')}")
    delays = get("engine.retry_delays")
    if not isinstance(delays, list) or not all(isinstance(x, (int, float)) for x in delays):
        errors.append(f"engine.retry_delays 应为数字列表: {delays}")
    if get("engine.max_retries") - 1 > len(delays or []):
        errors.append(
            f"engine.retry_delays 长度 ({len(delays)}) < max_retries-1 "
            f"({get('engine.max_retries')-1})"
        )
    # 日志
    if not isinstance(get("log.retention_days"), int) or get("log.retention_days") < 1:
        errors.append(f"log.retention_days 应为正整数: {get('log.retention_days')}")
    if not isinstance(get("log.max_bytes"), int) or get("log.max_bytes") < 1024:
        errors.append(f"log.max_bytes 应 ≥ 1024: {get('log.max_bytes')}")
    # 题材
    if get("genre.max_primary") != 1:
        errors.append(f"genre.max_primary 应为 1: {get('genre.max_primary')}")
    if get("genre.max_aux") < 0 or get("genre.max_aux") > 10:
        errors.append(f"genre.max_aux 应在 0-10: {get('genre.max_aux')}")
    # DB
    jm = get("db.journal_mode")
    if jm not in ("WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"):
        errors.append(f"db.journal_mode 非法: {jm!r}")
    # UI
    if get("ui.theme") not in ("light", "dark"):
        errors.append(f"ui.theme 应为 light / dark: {get('ui.theme')!r}")
    scale = get("ui.scale")
    if not isinstance(scale, (int, float)) or not (0.5 <= float(scale) <= 3.0):
        errors.append(f"ui.scale 应在 0.5-3.0: {scale!r}")
    if errors:
        for e in errors:
            _logger.warning("配置校验: %s", e)
    else:
        _logger.info("配置校验: 全部通过 (%d 项)", len(_settings))
    return errors


# ────────────────────── 便捷访问器 (类型安全) ──────────────────────
# 4.0 各模块用这些函数, 避免到处 get("xxx")

def get_engine_max_retries() -> int:
    return int(get("engine.max_retries"))


def get_engine_retry_delays() -> list[int]:
    return [int(x) for x in get("engine.retry_delays")]


def get_log_retention_days() -> int:
    return int(get("log.retention_days"))


def get_log_max_bytes() -> int:
    return int(get("log.max_bytes"))


def get_db_journal_mode() -> str:
    return str(get("db.journal_mode", "WAL"))


def get_db_isolation_level() -> Optional[str]:
    """None = autocommit (4.0 现状)。"""
    val = get("db.isolation_level")
    return val if val else None


def get_subtext_default_mode() -> str:
    return str(get("subtext.default_mode"))


def get_max_primary_genres() -> int:
    return int(get("genre.max_primary"))


def get_max_aux_genres() -> int:
    return int(get("genre.max_aux"))


def get_ui_scale() -> float:
    return float(get("ui.scale"))


def get_ui_font_size() -> int:
    return int(get("ui.font_size"))


def get_ui_theme() -> str:
    return str(get("ui.theme"))
