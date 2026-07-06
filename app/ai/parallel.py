"""
app/ai/parallel.py - M9-A3: LLM 并行多模型调度.

设计:
- N 个模型同时调, 谁先返回就收集 (不阻塞等待)
- 单个失败 → 占位 LLMResult (content="", finish_reason="error"), 不中断
- 选 best: 默认 cost 最低 (省 token)
- 线程池: ThreadPoolExecutor(max_workers=N) 避免开 N 个线程
- 超时: 每个调用有 max_seconds 超时, 防止某个慢模型拖累整个流程

不做的事:
- 不做 fallback (A4 走 SequentialFallbackChain)
- 不做 cache (cache 在 LLMRouter 层做)
- 不做 critic 评分 (后续可加, M9-A 范围外)
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import List, Optional, Callable

from app.ai.registry import ModelConfig
from app.ai import providers as _ai_providers
from app.core.interfaces import LLMResult
from app.ai.router import RouteRequest

_logger = logging.getLogger("NovelWriter.ai.parallel")


# ============================================================
# 单模型调用 (包装 AIEngine._try_chat, 避免循环 import)
# ============================================================

def _call_one(
    config: ModelConfig,
    messages: list,
    temperature: float,
    max_tokens: int,
) -> LLMResult:
    """单次调用一个模型, 失败抛异常 (caller 兜底)."""
    client = _ai_providers.create_client(config)
    return client.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        on_chunk=None,
    )


# ============================================================
# 错误占位
# ============================================================

def _error_result(config: ModelConfig, error: str, duration_ms: int = 0) -> LLMResult:
    """并行模式下, 单个模型失败时的占位 LLMResult."""
    return LLMResult(
        content="",
        model=config.model_name,
        provider=config.provider,
        input_tokens=0,
        output_tokens=0,
        cost=0.0,
        duration_ms=duration_ms,
        finish_reason=f"error: {error[:50]}",
    )


# ============================================================
# 并行 runner
# ============================================================

class ThreadedParallelRunner:
    """M9-A3: N 模型并行, 默认 cost 最低胜出."""

    def execute(
        self,
        models: List[ModelConfig],
        request: RouteRequest,
        *,
        max_workers: int = 4,
        per_call_timeout_sec: float = 60.0,
    ) -> List[LLMResult]:
        """
        同时调 N 个模型, 收集所有结果.
        - 单失败不中断, 失败位置用 _error_result 占位
        - 返回 list[LLMResult] 顺序与 models 一致
        """
        if not models:
            return []

        n = len(models)
        workers = min(n, max_workers)
        results: List[Optional[LLMResult]] = [None] * n  # 保持顺序

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llm-par") as ex:
            future_to_idx: dict[Future, int] = {}
            for i, cfg in enumerate(models):
                fut = ex.submit(
                    _call_one,
                    cfg,
                    request.messages,
                    request.temperature,
                    request.max_tokens,
                )
                future_to_idx[fut] = i

            for fut in as_completed(future_to_idx, timeout=per_call_timeout_sec * n + 5):
                idx = future_to_idx[fut]
                cfg = models[idx]
                try:
                    res = fut.result(timeout=per_call_timeout_sec)
                    results[idx] = res
                    _logger.info("parallel[%d] %s 成功 (cost=%.6f, %dms)",
                                 idx, cfg.model_name, res.cost, res.duration_ms)
                except Exception as e:
                    dur = int((time.time() - t0) * 1000)
                    _logger.warning("parallel[%d] %s 失败: %s", idx, cfg.model_name, e)
                    results[idx] = _error_result(cfg, str(e), duration_ms=dur)

        # 兜底: 极个别情况 None (e.g. as_completed 超时)
        for i, r in enumerate(results):
            if r is None:
                results[i] = _error_result(models[i], "timeout or no result")

        total_ms = int((time.time() - t0) * 1000)
        _logger.info("parallel 完成 %d 个模型, 耗时 %dms", n, total_ms)
        return list(results)  # type: ignore[arg-type]


# ============================================================
# 选 best
# ============================================================

def pick_best(
    results: List[LLMResult],
    *,
    criterion: str = "cost",
) -> Optional[LLMResult]:
    """
    从并行结果中选最佳. 默认按 cost 最低.
    criterion:
      - "cost": cost 最低 (省 token)
      - "tokens": total_tokens 最低 (省配额)
      - "first": 第一个成功的 (最快)
    失败 (finish_reason=error:*) 的不参与选择.
    """
    if not results:
        return None
    candidates = [r for r in results if not r.finish_reason.startswith("error")]
    if not candidates:
        # 都失败 → 返回第一个 (含错误信息)
        return results[0]
    if criterion == "first":
        return candidates[0]
    if criterion == "cost":
        return min(candidates, key=lambda r: (r.cost, r.duration_ms))
    if criterion == "tokens":
        return min(candidates, key=lambda r: r.total_tokens)
    # 未知 criterion → 兜底按 cost
    return min(candidates, key=lambda r: (r.cost, r.duration_ms))
