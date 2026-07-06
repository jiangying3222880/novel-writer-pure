"""
模型注册表 (A3: 完整做)
3 层:
  1. 内置预置 (app/resources/seed_models.json, 可改不改)
  2. 用户 UI 配置 (DB model_configs 表, 4.0 持久化)
  3. 运行时单例 (内存里, 本类)
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from app.db import connection
from app.db.models import ModelConfig

_logger = logging.getLogger("NovelWriter.ai.registry")


# ────────────────────── Env Key 映射 (M11-B) ──────────────────────
# 真 key 走 OS env (或 .env + load_dotenv), 绝不进 git
# 优先级: env var (有值) > seed model.api_key (空) > 用户 DB 配置
_ENV_KEY_MAP: dict[str, str] = {
    "preset_nvidia_nim": "NVIDIA_API_KEY",
    "preset_xiaomi_16b": "XIAOMI_16B_API_KEY",
    "preset_xiaomi_2b":  "XIAOMI_2B_API_KEY",
    "preset_minimax":    "MINIMAX_API_KEY",
    "preset_deepseek":   "DEEPSEEK_API_KEY",
}


def inject_env_keys(reg: "ModelRegistry") -> int:
    """从环境变量注入 API key 到对应 model. 启动早期调一次.

    Returns: 实际注入的 key 数量.
    """
    import os as _os
    n = 0
    for model_id, env_name in _ENV_KEY_MAP.items():
        key = (_os.environ.get(env_name) or "").strip()
        if not key:
            continue
        cfg = reg.get(model_id)
        if cfg is None:
            # seed model 还没 init (init_defaults 未跑), 跳过
            continue
        if cfg.api_key == key:
            continue  # 已经是这个 key, noop
        cfg.api_key = key
        try:
            reg._upsert_db(cfg)
        except Exception as e:
            _logger.warning("env key 写 DB 失败 %s: %s (内存里已注入, 重启会再注入)", model_id, e)
        n += 1
        _logger.info("env 注入 API key: %s ← %s", model_id, env_name)
    return n


# ────────────────────── 内置预置 (A3 第 1 层) ──────────────────────
# 4.0 启动时初始化到 DB, 用户不可删
# 价格更新时间统一用 SETTINGS 里的 model.price_updated_at
SEED_MODELS_PATH = Path(__file__).resolve().parent.parent / "resources" / "seed_models.json"


def _load_seed_models() -> list[dict]:
    """从 seed_models.json 加载内置预置. 文件不存在/损坏 → 返回空列表 + 日志告警."""
    if not SEED_MODELS_PATH.exists():
        _logger.error(
            "seed_models.json 不存在: %s. 请重新安装或恢复内置预置文件.", SEED_MODELS_PATH
        )
        return []
    try:
        return json.loads(SEED_MODELS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _logger.error("seed_models.json 解析失败: %s", e)
        return []


_DEFAULT_MODELS: Optional[list[dict]] = None


def get_default_models() -> list[dict]:
    """懒加载内置预置模型列表 (首次调用时加载, 缓存)."""
    global _DEFAULT_MODELS
    if _DEFAULT_MODELS is None:
        _DEFAULT_MODELS = _load_seed_models()
    return _DEFAULT_MODELS


class ModelRegistry:
    """模型注册表运行时实例。"""

    def __init__(self):
        self._models: dict[str, ModelConfig] = {}

    def init_defaults(self) -> None:
        """把内置预置写入 DB (幂等)。"""
        conn = connection.get_conn()
        seed_models = get_default_models()
        for m in seed_models:
            row = conn.execute(
                "SELECT id FROM model_configs WHERE id = ?", (m["id"],)
            ).fetchone()
            if row:
                continue
            config = ModelConfig(
                id=m["id"],
                provider=m["provider"],
                model_name=m["model_name"],
                base_url=m.get("base_url", ""),
                api_key=m.get("api_key", ""),
                role=m.get("role", "primary"),
                rpm_limit=m.get("rpm_limit", 60),
                tpm_limit=m.get("tpm_limit", 90000),
                input_price=m.get("input_price", 0.0),
                output_price=m.get("output_price", 0.0),
                max_tokens=m.get("max_tokens", 4096),
                supports_streaming=m.get("supports_streaming", True),
                supports_thinking=m.get("supports_thinking", False),
                built_in=True,
            )
            self._upsert_db(config)
        _logger.info("初始化 %d 个内置预置模型", len(seed_models))

    def reload(self) -> None:
        """从 DB 加载到内存。"""
        conn = connection.get_conn()
        rows = conn.execute("SELECT * FROM model_configs").fetchall()
        self._models = {r["id"]: ModelConfig(**dict(r)) for r in rows}
        _logger.info("从 DB 加载 %d 个模型", len(self._models))

    def _upsert_db(self, config: ModelConfig) -> None:
        conn = connection.get_conn()
        d = asdict(config)
        cols = list(d.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = tuple(d[c] for c in cols)
        conn.execute(
            f"INSERT OR REPLACE INTO model_configs ({col_names}) VALUES ({placeholders})",
            values,
        )

    def save(self, config: ModelConfig) -> None:
        self._upsert_db(config)
        self._models[config.id] = config

    def get(self, model_id: str) -> Optional[ModelConfig]:
        return self._models.get(model_id)

    def get_primary(self) -> Optional[ModelConfig]:
        """返回主模型 — 优先选择已配置 API Key 的。

        选择顺序 (越靠前优先级越高):
          1. app_setting_service 的 active provider (用户在UI设为active的)
          2. role=="primary" 且 api_key 非空的内置模型
          3. role=="primary" 的任意一个 (供 UI 展示)
        """
        # 1) 优先: active provider (用户在 UI 上设为 active 的)
        try:
            from app.services import app_setting_service
            active = app_setting_service.get_active()
            if active and active.get("api_key"):
                return ModelConfig(
                    id=f"active_{active['name']}",
                    provider=active.get("provider_type", "openai_compat"),
                    model_name=active.get("model", ""),
                    base_url=active.get("api_base", ""),
                    api_key=active.get("api_key", ""),
                    role="primary",
                    max_tokens=active.get("max_tokens", 4096),
                )
        except Exception as e:
            _logger.debug("读取 active provider 失败, 回退到内置 primary: %s", e)

        # 2) 内置: role=="primary" 且有 api_key
        primaries = [m for m in self._models.values() if m.role == "primary"]
        if not primaries:
            return None
        for m in primaries:
            if m.api_key and m.api_key.strip():
                return m
        # 3) 都没有 key → 返回第一个
        return primaries[0]

    def get_fallback(self) -> Optional[ModelConfig]:
        for m in self._models.values():
            if m.role == "fallback":
                return m
        return None

    def list_all(self) -> list[ModelConfig]:
        return list(self._models.values())

    def list_enabled(self) -> list[ModelConfig]:
        return [m for m in self._models.values() if m.api_key]    # 有 key 才视为启用


# 全局单例
_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def reset_registry() -> None:
    """重置 (测试用)。"""
    global _registry
    _registry = None
