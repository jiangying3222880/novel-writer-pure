"""
App-level settings service (Phase 3 M2).

全局 LLM 模型配置, 存到 %APPDATA%/NovelWriterPure/app_settings.json.
与 project 级 setting_service 区分:
  - setting_service: 项目级 (worldbuilding / characters / anti_rules 等)
  - app_setting_service: 全局, 跨项目复用 (LLM providers)

存储结构:
{
    "providers": [...],
    "active_provider": "deepseek-main"   # 或 null
    "kv": {                               # 通用 KV (B5 license / 后续全局设置)
        "license.key": "...",
        "license.status": "premium",
        ...
    }
}

设计:
  - 单文件 JSON, 不加锁 (单机桌面场景)
  - 写入用临时文件 + rename 避免半写
  - 读时容错: 文件不存在 / 损坏 -> 返回空结构
"""
from __future__ import annotations
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.app_paths import DATA_DIR
from app.services.exceptions import ValidationError

log = logging.getLogger(__name__)

SETTINGS_FILE = DATA_DIR / "app_settings.json"
VALID_PROVIDER_TYPES = {"openai_compat", "anthropic"}


# --------------------------------------------------------------------- #
# 内部: 文件 IO
# --------------------------------------------------------------------- #

def _empty() -> dict:
    return {"providers": [], "active_provider": None, "kv": {}}


def _load() -> dict:
    if not SETTINGS_FILE.exists():
        return _empty()
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"[app_settings] load failed: {e}, fallback to empty")
        return _empty()
    # 容错: 字段缺失
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("providers", [])
    data.setdefault("active_provider", None)
    data.setdefault("kv", {})
    if not isinstance(data["providers"], list):
        data["providers"] = []
    if not isinstance(data["kv"], dict):
        data["kv"] = {}
    return data


def _save(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件 + rename, 避免半写
    fd, tmp_path = tempfile.mkstemp(
        prefix="app_settings_", suffix=".json",
        dir=str(SETTINGS_FILE.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_FILE)
    except Exception:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise


# --------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------- #

def _validate_provider(p: dict, *, require_name: bool = True) -> None:
    from app.services.exceptions import ValidationError
    if require_name and not p.get("name"):
        raise ValidationError("provider.name is required")
    if "provider_type" in p and p["provider_type"] not in VALID_PROVIDER_TYPES:
        raise ValidationError(
            f"provider.provider_type must be one of {VALID_PROVIDER_TYPES}"
        )
    if "api_base" in p and not isinstance(p["api_base"], str):
        raise ValidationError("provider.api_base must be str")
    if "api_key" in p and not isinstance(p["api_key"], str):
        raise ValidationError("provider.api_key must be str")
    if "model" in p and not p["model"]:
        raise ValidationError("provider.model must be non-empty str")
    if "priority" in p and not isinstance(p["priority"], int):
        raise ValidationError("provider.priority must be int")
    if "max_tokens" in p and (not isinstance(p["max_tokens"], int) or p["max_tokens"] <= 0):
        raise ValidationError("provider.max_tokens must be positive int")
    if "temperature" in p and not (0.0 <= float(p["temperature"]) <= 2.0):
        raise ValidationError("provider.temperature must be in [0.0, 2.0]")


# --------------------------------------------------------------------- #
# 公共 API
# --------------------------------------------------------------------- #

def list_providers() -> list[dict]:
    """列出所有 provider (按 priority 升序)."""
    return sorted(_load()["providers"], key=lambda p: p.get("priority", 0))


def get_provider(name: str) -> dict:
    """取一个 provider. 不存在 -> NotFoundError."""
    from app.services.exceptions import NotFoundError
    for p in _load()["providers"]:
        if p.get("name") == name:
            return p
    raise NotFoundError("Provider", name)


def add_provider(provider: dict) -> dict:
    """新增. name 重复 -> ValidationError."""
    from app.services.exceptions import ValidationError
    _validate_provider(provider)
    data = _load()
    if any(p.get("name") == provider["name"] for p in data["providers"]):
        raise ValidationError(f"provider.name already exists: {provider['name']!r}")
    # 补默认字段
    full = {
        "name": provider["name"],
        "provider_type": provider.get("provider_type", "openai_compat"),
        "api_base": provider.get("api_base", ""),
        "api_key": provider.get("api_key", ""),
        "model": provider.get("model", ""),
        "max_tokens": provider.get("max_tokens", 4096),
        "temperature": provider.get("temperature", 0.7),
        "timeout": provider.get("timeout", 120.0),
        "priority": provider.get("priority", 0),
    }
    data["providers"].append(full)
    _save(data)
    return full


def update_provider(name: str, patch: dict) -> dict:
    """部分更新. 不允许改 name. 不存在 -> NotFoundError."""
    from app.services.exceptions import ValidationError
    if "name" in patch and patch["name"] != name:
        raise ValidationError("cannot rename provider (use delete + add)")
    _validate_provider(patch, require_name=False)
    data = _load()
    for i, p in enumerate(data["providers"]):
        if p.get("name") == name:
            p.update({k: v for k, v in patch.items() if k != "name"})
            data["providers"][i] = p
            _save(data)
            return p
    from app.services.exceptions import NotFoundError
    raise NotFoundError("Provider", name)


def delete_provider(name: str) -> None:
    """删除. 不存在 -> NotFoundError. 如果是 active 则清空 active."""
    data = _load()
    before = len(data["providers"])
    data["providers"] = [p for p in data["providers"] if p.get("name") != name]
    if len(data["providers"]) == before:
        from app.services.exceptions import NotFoundError
        raise NotFoundError("Provider", name)
    if data.get("active_provider") == name:
        data["active_provider"] = None
    _save(data)


def get_active_name() -> Optional[str]:
    return _load().get("active_provider")


def set_active(name: str) -> None:
    """设为 active. provider 不存在 -> NotFoundError."""
    # 触发 404
    get_provider(name)
    data = _load()
    data["active_provider"] = name
    _save(data)


def get_active() -> Optional[dict]:
    """取 active provider 的完整配置 (供 LLMClient 使用)."""
    name = get_active_name()
    if not name:
        return None
    try:
        return get_provider(name)
    except Exception:
        return None


def list_presets() -> list[str]:
    """列出可用的厂商预设名 (供 UI 下拉)."""
    from app.core.llm import PROVIDER_PRESETS
    return list(PROVIDER_PRESETS.keys())


# --------------------------------------------------------------------- #
# 通用 KV (供 B5 license / 其他全局配置使用)
# --------------------------------------------------------------------- #

def get(key: str, default: Any = None) -> Any:
    """取一个全局 KV. 不存在返回 default."""
    return _load().get("kv", {}).get(key, default)


def set(key: str, value: Any) -> None:
    """存一个全局 KV. value 必须 JSON 可序列化."""
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"value not JSON-serializable: {e}")
    data = _load()
    data.setdefault("kv", {})
    data["kv"][key] = value
    _save(data)


def delete(key: str) -> bool:
    """删一个全局 KV. 返回是否真的删了."""
    data = _load()
    kv = data.setdefault("kv", {})
    if key in kv:
        del kv[key]
        _save(data)
        return True
    return False


def all_kv() -> dict:
    """取所有 KV (只读副本, 供调试/迁移)."""
    return dict(_load().get("kv", {}))
