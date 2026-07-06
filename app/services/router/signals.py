"""
M11-B: Router 业务级事件信号层.

L1 app/ai/fallback.py 已经 publish 了 MODEL_USED / MODEL_FAILED / MODEL_FALLBACK.
本模块把这些低层事件聚合 / 重命名成业务级 router.* 事件, 让 dashboard / 缓存策略
等业务模块从 L2 拿数据, 不直接订阅 L1.

事件清单 (跟 app.core.event_bus.Events 区分, 业务级):
  ROUTER_USED       一次 LLM 调用完成 (含 tokens + 费用 + model)
  ROUTER_FAILED     一次调用失败 (含 model + error)
  ROUTER_FALLBACK   主模型失败, 降级到备
  ROUTER_CACHE_HIT  cache 命中 (from_cache=True)
  ROUTER_CACHE_MISS cache miss
  ROUTER_STRATEGY_CHANGED 用户切策略 (single/parallel/cache_first)

L1 → L2 适配:
  L1 publish("model.used", data) → 我们的 _relay 收 → publish("router.used", data)
  默认自动启动 (业务模块直接 import 就行)
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from app.core.event_bus import get_bus, Events

_logger = logging.getLogger("NovelWriter.services.router.signals")

# 业务级事件名 (跟 L1 区分, UI 订阅这个)
ROUTER_USED = "router.used"
ROUTER_FAILED = "router.failed"
ROUTER_FALLBACK = "router.fallback"
ROUTER_CACHE_HIT = "router.cache_hit"
ROUTER_CACHE_MISS = "router.cache_miss"
ROUTER_STRATEGY_CHANGED = "router.strategy_changed"


_relay_started = False
_relay_lock = threading.Lock()


def _on_l1_model_used(event) -> None:
    """L1 model.used → 业务 router.used + router.cache_hit (如适用)."""
    data = event.data or {}
    if data.get("from_cache"):
        get_bus().publish(ROUTER_CACHE_HIT, data, source="router.signals")
    else:
        get_bus().publish(ROUTER_USED, data, source="router.signals")


def _on_l1_model_failed(event) -> None:
    """L1 model.failed → 业务 router.failed."""
    get_bus().publish(ROUTER_FAILED, event.data or {}, source="router.signals")


def _on_l1_model_fallback(event) -> None:
    """L1 model.fallback → 业务 router.fallback."""
    get_bus().publish(ROUTER_FALLBACK, event.data or {}, source="router.signals")


def install_relay() -> None:
    """启动 L1 → L2 事件桥接 (幂等, 可多次调).

    业务模块启动时调一次即可. 后续 router_status_bar / dashboard / 缓存策略
    都直接订阅 ROUTER_USED / ROUTER_CACHE_HIT 即可.
    """
    global _relay_started
    with _relay_lock:
        if _relay_started:
            return
        bus = get_bus()
        bus.subscribe(Events.MODEL_USED, _on_l1_model_used)
        bus.subscribe(Events.MODEL_FAILED, _on_l1_model_failed)
        bus.subscribe(Events.MODEL_FALLBACK, _on_l1_model_fallback)
        _relay_started = True
        _logger.info("router L1→L2 signal relay 已启动 (3 个桥接)")


def publish_strategy_changed(strategy: str, project_id: Optional[str] = None) -> int:
    """业务层调: 用户切了路由策略."""
    return get_bus().publish(
        ROUTER_STRATEGY_CHANGED,
        {"strategy": strategy, "project_id": project_id or ""},
        source="router.signals",
    )


def publish_cache_miss(key: str) -> int:
    """业务层调: cache miss."""
    return get_bus().publish(ROUTER_CACHE_MISS, {"key": key}, source="router.signals")
