"""
app/ai/fallback.py - M9-A4: LLM 顺序 fallback 链 (主备降级).

从 AIEngine._chat_with_retry 迁移过来, 让 router 接管降级逻辑.

设计:
- 给定 models 列表 (primary → fallback1 → fallback2 → ...), 顺序试
- 每个 model 重试 N 次 (max_retries), 每次失败 sleep delay
- 都失败 → 返回 None
- 成功 → 返回 LLMResult, caller 写 usage
- 副作用: 派发 Events.MODEL_USED / MODEL_FAILED / MODEL_FALLBACK

为什么不并发?
- parallel 是 A3 的活 (N 模型同时跑, 选 best)
- fallback 是顺序降级 (A 模型挂了, 切 B; B 也挂了, 切 C)
- 两者不冲突, 互为补充
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import List, Optional

from app.ai import providers as _ai_providers
from app.ai.registry import ModelConfig
from app.core import config as _app_config
from app.core.event_bus import publish, Events
from app.core.interfaces import LLMResult
from app.db import connection
from app.db.models import UsageRecord
from app.ai.router import RouteRequest

_logger = logging.getLogger("NovelWriter.ai.fallback")


class SequentialFallbackChain:
    """A4: 顺序主备降级, 复用 AIEngine._chat_with_retry 逻辑."""

    def __init__(self) -> None:
        # 配置从 app config 读 (避免硬编码)
        pass

    def _max_retries(self) -> int:
        return _app_config.get_engine_max_retries()

    def _retry_delays(self) -> List[int]:
        return _app_config.get_engine_retry_delays()

    def _calc_cost(self, config: ModelConfig, result: LLMResult) -> float:
        in_cost = result.input_tokens * config.input_price / 1_000_000
        out_cost = result.output_tokens * config.output_price / 1_000_000
        return round(in_cost + out_cost, 6)

    def _record_usage(
        self,
        config: ModelConfig,
        result: LLMResult,
        task: str,
        project_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        success: bool = True,
        error_msg: str = "",
    ) -> None:
        """写 usage_records (从 AIEngine 搬过来, 简化: schema 当前无 success/error_msg 列)."""
        try:
            conn = connection.get_conn()
            if project_id is not None:
                row = conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
                if not row:
                    project_id = None
            if chapter_id is not None:
                row = conn.execute("SELECT 1 FROM chapters WHERE id=?", (chapter_id,)).fetchone()
                if not row:
                    chapter_id = None
            rec = UsageRecord(
                id=uuid.uuid4().hex[:8],
                project_id=project_id,
                chapter_id=chapter_id,
                provider=config.provider,
                model=config.model_name,
                step=task,
                tokens_in=result.input_tokens,
                tokens_out=result.output_tokens,
                cost=self._calc_cost(config, result) if success else 0.0,
            )
            conn.execute(
                "INSERT INTO usage_records "
                "(id, project_id, chapter_id, provider, model, step, "
                " tokens_in, tokens_out, cost, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    rec.id, rec.project_id, rec.chapter_id, rec.provider, rec.model, rec.step,
                    rec.tokens_in, rec.tokens_out, rec.cost,
                ),
            )
            conn.commit()
            if not success:
                _logger.warning("model %s 失败: %s", config.id, error_msg[:200])
        except Exception as e:
            _logger.warning("record_usage 失败: %s", e)

    def _try_chat(
        self,
        config: ModelConfig,
        request: RouteRequest,
    ) -> LLMResult:
        """单次调用一个模型 (从 AIEngine._try_chat 搬)."""
        client = _ai_providers.create_client(config)
        result = client.chat(
            request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
            on_chunk=request.on_chunk,
        )
        result.cost = self._calc_cost(config, result)
        return result

    def execute(
        self,
        models: List[ModelConfig],
        request: RouteRequest,
    ) -> Optional[LLMResult]:
        """
        顺序试 models, 第一个成功的返回.
        都失败 → 返回 None.
        行为等价 AIEngine._chat_with_retry 但接受 RouteRequest.
        """
        if not models:
            return None
        max_retries = self._max_retries()
        delays = self._retry_delays()
        last_error = ""
        for idx, config in enumerate(models):
            for attempt in range(max_retries):
                try:
                    result = self._try_chat(config, request)
                    # 成功
                    self._record_usage(
                        config, result, request.task,
                        project_id=request.project_id, chapter_id=request.chapter_id,
                    )
                    publish(Events.MODEL_USED, result.to_dict())
                    return result
                except Exception as e:
                    last_error = str(e)
                    _logger.warning("模型 %s 第 %d 次失败: %s", config.id, attempt + 1, e)
                    publish(Events.MODEL_FAILED, {"model": config.id, "error": last_error})
                    if attempt < max_retries - 1 and attempt < len(delays):
                        time.sleep(delays[attempt])
            # 这个 model 重试 N 次都失败, 派发 fallback 事件
            if idx < len(models) - 1:
                _logger.warning("降级: %s → %s", config.id, models[idx + 1].id)
                publish(Events.MODEL_FALLBACK, {
                    "from": config.id, "to": models[idx + 1].id,
                })
        # 全部失败, 记录 usage
        if models:
            self._record_usage(
                models[-1],
                LLMResult(model=models[-1].model_name, provider=models[-1].provider),
                request.task,
                project_id=request.project_id, chapter_id=request.chapter_id,
                success=False, error_msg=last_error,
            )
        return None
