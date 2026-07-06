"""
app/ai/router.py - M9-A: LLM 调度路由器接口 + 骨架实现.

设计目标 (M9-A1 接口定义):
1. 统一入口 `LLMRouter.route()` 替代 AIEngine.chat 调度
2. 三大策略可插拔:
   - 单一 (默认): 走 primary, 失败走 fallback chain
   - 并行 (parallel): N 个模型同时跑, 选最佳
   - 缓存 (cache): 命中即返, 0 token
3. 三个子组件:
   - LLMCache: prompt -> LLMResult 缓存 (内存 LRU + 磁盘 sqlite 二级)
   - LLMFallbackChain: 主备链 (复用 AIEngine._chat_with_retry 逻辑)
   - LLMParallelRunner: 并行调用, 选最佳 (默认按 token 成本最低)
4. 不破坏分层: 在 L1 (app/ai/) 内部, 业务层 (services) 仍调 AIEngine
   AIEngine 内部用 LLMRouter 重组 (M9-A3+ 改写)

接口 = Protocol, 实现 = dataclass, 注入式 (可替换 mock)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, Callable, List, Dict, Any

from app.ai.registry import ModelConfig
from app.core.interfaces import LLMResult

_logger = logging.getLogger("NovelWriter.ai.router")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RouteRequest:
    """一次 LLM 调用的完整描述."""
    messages: List[Dict[str, str]]
    task: str = "write"
    temperature: float = 0.7
    max_tokens: int = 4096
    project_id: Optional[str] = None
    chapter_id: Optional[str] = None
    # 路由策略: "single" | "parallel" | "cache_first"
    strategy: str = "single"
    # 并行模式: 跑几个模型
    parallel_n: int = 3
    # 是否写 usage_records
    record_usage: bool = True
    # 流式回调
    on_chunk: Optional[Callable[[str], None]] = None

    def cache_key(self) -> str:
        """生成 cache key (含 messages 内容 + 关键参数)."""
        payload = {
            "messages": self.messages,
            "task": self.task,
            "temperature": round(self.temperature, 2),
            "max_tokens": self.max_tokens,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class RouteResult:
    """router 返回的元信息 (含 cache/fallback 标签, 便于审计)."""
    result: LLMResult
    from_cache: bool = False
    strategy_used: str = "single"            # 实际用的策略
    models_tried: List[str] = field(default_factory=list)   # 试过的 model_id
    fallback_count: int = 0                  # 降级次数
    parallel_results: List[LLMResult] = field(default_factory=list)  # 并行的所有结果


# ============================================================
# 接口 (Protocol)
# ============================================================

class LLMCache(Protocol):
    """LLM 响应缓存."""
    def get(self, key: str) -> Optional[LLMResult]:
        """命中即返回 LLMResult, miss 返回 None."""
        ...

    def put(self, key: str, result: LLMResult) -> None:
        """存一条 cache 记录."""
        ...


class LLMFallbackChain(Protocol):
    """模型 fallback 链 (主备)."""
    def execute(
        self,
        models: List[ModelConfig],
        request: RouteRequest,
    ) -> Optional[LLMResult]:
        """
        依次试 models, 第一个成功的返回.
        都失败 → 返回 None.
        """
        ...


class LLMParallelRunner(Protocol):
    """并行多模型调度."""
    def execute(
        self,
        models: List[ModelConfig],
        request: RouteRequest,
    ) -> List[LLMResult]:
        """
        同时调 N 个模型, 返回所有结果 (含失败的占位).
        不做选择 — 选择交给 LLMRouter.
        """
        ...


# ============================================================
# 默认实现占位 (M9-A2/A3/A4 落实)
# ============================================================
# A2: InMemoryLRUCache / TieredCache 已迁到 app/ai/cache.py
from app.ai.cache import InMemoryLRUCache, TieredCache, DiskSqliteCache  # noqa: F401


class _FallbackChainPlaceholder:
    """A4 占位: 实际 SequentialFallbackChain 在 app/ai/fallback.py."""
    pass


# A4: SequentialFallbackChain 落实
from app.ai.fallback import SequentialFallbackChain  # noqa: F401, E402


# A3: ThreadedParallelRunner 落实
from app.ai.parallel import ThreadedParallelRunner, pick_best  # noqa: F401, E402


# ============================================================
# Router 主类
# ============================================================

class LLMRouter:
    """
    M9-A LLM 调度路由器 (顶层入口).

    调用顺序 (strategy):
      single:        cache.get → primary → fallback chain
      parallel:      并行 N 个模型 → 选最佳
      cache_first:   cache.get → (miss 时) primary

    选最佳 (parallel 模式):
      默认: cost 最低 (省 token)
      后续可加: critic 评分, latency, user preference
    """

    def __init__(
        self,
        cache: Optional[LLMCache] = None,
        fallback: Optional[LLMFallbackChain] = None,
        parallel: Optional[LLMParallelRunner] = None,
    ) -> None:
        # A2: 默认走 TieredCache (L1 内存 + L2 磁盘)
        #     L1 给 fast path, L2 跨会话复用
        if cache is None:
            from app.app_paths import get_data_dir
            from app.core import config as _cfg
            # 优先级: env var (smoke 用) > config > 默认
            import os as _os
            cache_dir_str = _os.environ.get("NW_AI_CACHE_DIR") or _cfg.get("ai.cache_dir") or str(get_data_dir() / "cache" / "llm")
            cache_dir = Path(cache_dir_str)
            disk = DiskSqliteCache(cache_dir / "llm_cache.db")
            l1_size_str = _os.environ.get("NW_AI_CACHE_L1_SIZE") or str(_cfg.get("ai.cache_l1_size", 256))
            cache = TieredCache(
                mem_cache=InMemoryLRUCache(max_size=int(l1_size_str)),
                disk_cache=disk,
            )
        self.cache = cache
        self.fallback = fallback or SequentialFallbackChain()
        self.parallel = parallel or ThreadedParallelRunner()

    def route(self, request: RouteRequest) -> RouteResult:
        """统一入口."""
        t0 = time.time()
        # 1) cache 命中 (single / cache_first 策略)
        if request.strategy in ("single", "cache_first"):
            cached = self.cache.get(request.cache_key())
            if cached is not None:
                _logger.info("cache HIT (%s)", request.cache_key()[:8])
                return RouteResult(
                    result=cached,
                    from_cache=True,
                    strategy_used="cache",
                    models_tried=[],
                )

        # 2) parallel 策略: 拿 N 个 primary 备选, 并行跑, 选 best
        if request.strategy == "parallel":
            return self._route_parallel(request, t0)

        # 3) single / cache_first 策略: 走 SequentialFallbackChain (A4 落实)
        #    A4 之前: 走 _delegate_to_ai_engine 保持原行为
        from app.ai.registry import get_registry
        registry = get_registry()
        primary = registry.get_primary()
        fallback_model = registry.get_fallback() if request.strategy == "single" else None
        chain: List[ModelConfig] = []
        if primary is not None:
            chain.append(primary)
        if fallback_model is not None and fallback_model.id != primary.id:
            chain.append(fallback_model)
        if not chain:
            raise RuntimeError("LLMRouter.route: 无可用模型 (未配置 primary)")

        result = self.fallback.execute(chain, request)
        if result is None:
            raise RuntimeError("LLMRouter.route: fallback chain 全部失败")

        # 4) 写 cache (single / cache_first 策略)
        if request.strategy in ("single", "cache_first"):
            self.cache.put(request.cache_key(), result)

        return RouteResult(
            result=result,
            from_cache=False,
            strategy_used=request.strategy,
            models_tried=[result.model] if result.model else [],
            fallback_count=max(0, len(chain) - 1) if primary and result.model != primary.model_name else 0,
        )

    def _route_parallel(self, request: RouteRequest, t0: float) -> RouteResult:
        """A3 落实: parallel 策略 — N 个 primary 模型并行, 选 cost 最低."""
        from app.ai.registry import get_registry
        registry = get_registry()
        # 拿 N 个备选模型 (primary + role="backup" 的前 N-1 个)
        all_models = registry.list_all() or []
        if not all_models:
            raise RuntimeError("LLMRouter._route_parallel: 无可用模型")
        # 简单选: role=primary 优先, 然后取前 N 个
        primary = next((m for m in all_models if m.role == "primary"), all_models[0])
        candidates = [primary]
        for m in all_models:
            if m.id != primary.id and len(candidates) < request.parallel_n:
                candidates.append(m)

        parallel_results: List[LLMResult] = self.parallel.execute(
            candidates, request,
            per_call_timeout_sec=float(60.0),
        )
        best = pick_best(parallel_results, criterion="cost")
        if best is None:
            raise RuntimeError("LLMRouter._route_parallel: 全部模型都失败")

        # 写 cache (best 结果)
        self.cache.put(request.cache_key(), best)

        duration = int((time.time() - t0) * 1000)
        return RouteResult(
            result=best,
            from_cache=False,
            strategy_used="parallel",
            models_tried=[r.model for r in parallel_results],
            parallel_results=parallel_results,
        )

    def _delegate_to_ai_engine(self, request: RouteRequest) -> Optional[LLMResult]:
        """A1 阶段: 走 AIEngine.chat 保持原行为. A4 阶段会替换成 fallback chain / parallel."""
        try:
            from app.ai.engine import AIEngine
            engine = AIEngine()
            return engine.chat(
                request.messages,
                task=request.task,
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                on_chunk=request.on_chunk,
                use_fallback=True,
            )
        except Exception as e:
            _logger.warning("AIEngine 失败: %s", e)
            return None


# ============================================================
# 全局单例
# ============================================================

_router_singleton: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """拿全局 router 单例."""
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = LLMRouter()
    return _router_singleton
