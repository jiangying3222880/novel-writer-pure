"""
M11-B: 真实 LLM 客户端 (L2 业务包装层).

底层用 app/ai/providers (OpenAI 兼容 + Anthropic).
本层加:
  1. 实时事件发布 (router.used / router.failed / router.fallback)
  2. 计时 (duration_ms)
  3. 单次调用统计 (success/fail + cost 估算)
  4. 错误归一化 (统一 ValueError / RuntimeError + error 字符串)

为什么不在 L1 直接做?
- L1 保持纯净 (app/ai/ 不知道业务事件)
- L2 这层可选, 业务模块想直接调 L1 也行 (e.g. mock 测试)

用法:
    from app.services.router.real_client import RealLLMClient
    from app.ai.registry import get_registry
    cfg = get_registry().get_primary()
    client = RealLLMClient(cfg)
    result = client.chat([{"role": "user", "content": "hi"}])
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterator, List, Dict, Optional

from app.ai import providers as _ai_providers
from app.ai.registry import ModelConfig
from app.core.interfaces import LLMResult

_logger = logging.getLogger("NovelWriter.services.router.real_client")


class RealLLMClient:
    """L2 业务包装的真实 LLM 客户端.

    - 转发到 app.ai.providers.create_client() (OpenAI 兼容 / Anthropic)
    - 实时派发 router.used / router.failed 业务事件
    - 自动计时 + cost 计算
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._inner = _ai_providers.create_client(config)
        # 内部统计 (本实例)
        self.success_count = 0
        self.fail_count = 0
        self.total_cost = 0.0

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def _calc_cost(self, result: LLMResult) -> float:
        in_cost = result.input_tokens * self.config.input_price / 1_000_000
        out_cost = result.output_tokens * self.config.output_price / 1_000_000
        return round(in_cost + out_cost, 6)

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> LLMResult:
        """调真实 LLM, 计时 + 计费 + 派发 router.used/failed 业务事件."""
        t0 = time.time()
        try:
            result = self._inner.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                on_chunk=on_chunk,
                **kwargs,
            )
            result.cost = self._calc_cost(result)
            self.success_count += 1
            self.total_cost += result.cost
            # 派发 router.used (业务层订阅)
            try:
                from app.services.router.signals import ROUTER_USED
                from app.core.event_bus import get_bus
                get_bus().publish(
                    ROUTER_USED,
                    {
                        "model": result.model,
                        "provider": result.provider,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost": result.cost,
                        "duration_ms": int((time.time() - t0) * 1000),
                    },
                    source="router.real_client",
                )
            except Exception as e:  # noqa: BLE001
                _logger.debug("router.used 派发失败: %s", e)
            return result
        except Exception as e:  # noqa: BLE001
            self.fail_count += 1
            try:
                from app.services.router.signals import ROUTER_FAILED
                from app.core.event_bus import get_bus
                get_bus().publish(
                    ROUTER_FAILED,
                    {
                        "model": self.config.model_name,
                        "provider": self.config.provider,
                        "error": str(e)[:200],
                        "duration_ms": int((time.time() - t0) * 1000),
                    },
                    source="router.real_client",
                )
            except Exception as ee:  # noqa: BLE001
                _logger.debug("router.failed 派发失败: %s", ee)
            raise

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Iterator[tuple[str, str]]:
        """流式调真实 LLM，yield (type, text) 元组。

        type: "thinking" | "content"
        底层转发到 _inner.chat_stream()（OpenAI compat SSE / Anthropic event-stream）。
        """
        t0 = time.time()
        try:
            yield from self._inner.chat_stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            # 派发 router.used
            try:
                from app.services.router.signals import ROUTER_USED
                from app.core.event_bus import get_bus
                get_bus().publish(
                    ROUTER_USED,
                    {
                        "model": self.config.model_name,
                        "provider": self.config.provider,
                        "duration_ms": int((time.time() - t0) * 1000),
                        "stream": True,
                    },
                    source="router.real_client",
                )
            except Exception as e:
                _logger.debug("router.used 派发失败: %s", e)
        except Exception as e:
            self.fail_count += 1
            try:
                from app.services.router.signals import ROUTER_FAILED
                from app.core.event_bus import get_bus
                get_bus().publish(
                    ROUTER_FAILED,
                    {
                        "model": self.config.model_name,
                        "provider": self.config.provider,
                        "error": str(e)[:200],
                        "duration_ms": int((time.time() - t0) * 1000),
                    },
                    source="router.real_client",
                )
            except Exception as ee:
                _logger.debug("router.failed 派发失败: %s", ee)
            raise


def create_real_client(model_id: Optional[str] = None) -> RealLLMClient:
    """便利: 拿一个 model 的 RealLLMClient (默认 primary)."""
    from app.ai.registry import get_registry
    registry = get_registry()
    if model_id is None:
        cfg = registry.get_primary()
    else:
        cfg = registry.get(model_id)
    if cfg is None:
        raise RuntimeError(f"找不到模型: {model_id or '(primary)'}")
    return RealLLMClient(cfg)
