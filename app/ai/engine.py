"""
AI 引擎 (A2: 简化做 - 重试+降级+统计)
- 自动重试 3 次 (同一模型)
- 失败降级 (primary → fallback)
- 用量统计 (写 usage_records 表)
"""
from __future__ import annotations
import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Callable

from app.ai.registry import get_registry, ModelConfig
from app.ai import providers as _ai_providers
from app.ai.utils import StreamAssembler
from app.core import config as _app_config
from app.core.event_bus import publish, Events
from app.core.interfaces import LLMResult
from app.db import connection
from app.db.models import UsageRecord

_logger = logging.getLogger("NovelWriter.ai.engine")


class AIEngine:
    """
    4.0 AI 引擎 (单例)。
    - chat(): 入口, 自动重试+降级
    - 记录 usage_records
    - 派发 Events.MODEL_USED / MODEL_FAILED / MODEL_FALLBACK
    """

    def __init__(self):
        self._registry = get_registry()

    # 重试参数从 config 读 (避免硬编码 3 / [2, 4, 8])
    def _max_retries(self) -> int:
        return _app_config.get_engine_max_retries()

    def _retry_delays(self) -> list[int]:
        return _app_config.get_engine_retry_delays()

    def _calc_cost(self, config: ModelConfig, result: LLMResult) -> float:
        """计算费用 (USD)。"""
        in_cost = result.input_tokens * config.input_price / 1_000_000
        out_cost = result.output_tokens * config.output_price / 1_000_000
        return round(in_cost + out_cost, 6)

    def _record_usage(
        self,
        config: ModelConfig,
        result: LLMResult,
        step: str,
        project_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        success: bool = True,
        error_msg: str = "",
    ) -> None:
        """写 usage_records。"""
        try:
            conn = connection.get_conn()
            # 检查 project_id / chapter_id 存在性 (FK), 不存在则置 None
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
                step=step,
                tokens_in=result.input_tokens,
                tokens_out=result.output_tokens,
                cost=result.cost,
                duration_ms=result.duration_ms,
            )
            cols = [f.name for f in UsageRecord.__dataclass_fields__.values()]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            values = tuple(getattr(rec, c) for c in cols)
            conn.execute(
                f"INSERT INTO usage_records ({col_names}) VALUES ({placeholders})",
                values,
            )
        except Exception as e:
            _logger.exception("写 usage_records 失败: %s", e)

    def _try_chat(
        self,
        config: ModelConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        on_chunk: Optional[Callable[[str], None]],
    ) -> LLMResult:
        """单次调用 (不重试)。"""
        client = _ai_providers.create_client(config)
        result = client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            on_chunk=on_chunk,
        )
        result.cost = self._calc_cost(config, result)
        return result

    def chat(
        self,
        messages: list[dict],
        *,
        task: str = "write",
        project_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        on_chunk: Optional[Callable[[str], None]] = None,
        use_fallback: bool = True,
    ) -> LLMResult:
        """
        4.0 AI 引擎主入口。
        - 自动重试 3 次
        - 失败降级 (primary → fallback)
        - 写 usage_records
        - 派发事件
        """
        # Mock 模式 (NW_AI_MOCK=1): 直接用 mock 工厂, 跳过主备检查
        try:
            from app.ai import mock as _mock_mod
            if _mock_mod.is_installed():
                # 构造一个临时的"primary"配置用于 mock (无 api_key 也能跑)
                from dataclasses import replace as _dc_replace
                from app.db.models import ModelConfig as _MC
                mock_config = _MC(
                    id="nw_mock",
                    provider="mock",
                    model_name="nw-mock",
                    base_url="",
                    api_key="mock-key-not-checked",
                    role="primary",
                    input_price=0.0,
                    output_price=0.0,
                )
                result = self._chat_with_retry(
                    mock_config, messages, temperature, max_tokens, on_chunk,
                    task=task, project_id=project_id, chapter_id=chapter_id,
                )
                if result is not None:
                    return result
                raise RuntimeError("mock 模式: 调用失败")
        except ImportError:
            pass

        primary = self._registry.get_primary()
        fallback = self._registry.get_fallback() if use_fallback else None

        if primary is None:
            raise RuntimeError("未配置主力模型 (在 模型配置 里设置)")

        # 1) 先试 primary
        result = self._chat_with_retry(
            primary, messages, temperature, max_tokens, on_chunk,
            task=task, project_id=project_id, chapter_id=chapter_id,
        )
        if result is not None:
            return result

        # 2) 降级到 fallback
        if fallback is not None and fallback.id != primary.id:
            _logger.warning("降级到备用模型: %s", fallback.model_name)
            publish(Events.MODEL_FALLBACK, {"from": primary.id, "to": fallback.id})
            result = self._chat_with_retry(
                fallback, messages, temperature, max_tokens, on_chunk,
                task=task, project_id=project_id, chapter_id=chapter_id,
            )
            if result is not None:
                return result

        raise RuntimeError("AI 引擎: 主备模型都失败")

    def _chat_with_retry(
        self,
        config: ModelConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        on_chunk: Optional[Callable],
        *,
        task: str,
        project_id: Optional[str],
        chapter_id: Optional[str],
    ) -> Optional[LLMResult]:
        """单模型重试 N 次 (N 从 config 读)."""
        max_retries = self._max_retries()
        delays = self._retry_delays()
        # 防御: delays 至少 max_retries-1 个, 不足时用最后一个
        for attempt in range(max_retries):
            try:
                result = self._try_chat(
                    config, messages, temperature, max_tokens, on_chunk,
                )
                # 成功
                self._record_usage(
                    config, result, task,
                    project_id=project_id, chapter_id=chapter_id,
                )
                publish(Events.MODEL_USED, result.to_dict())
                return result
            except Exception as e:
                _logger.warning("模型 %s 第 %d 次失败: %s", config.id, attempt + 1, e)
                publish(Events.MODEL_FAILED, {"model": config.id, "error": str(e)})
                if attempt < max_retries - 1 and attempt < len(delays):
                    time.sleep(delays[attempt])
                else:
                    # 最后一次失败, 记录
                    self._record_usage(
                        config, LLMResult(
                            model=config.model_name,
                            provider=config.provider,
                        ),
                        task,
                        project_id=project_id, chapter_id=chapter_id,
                        success=False,
                        error_msg=str(e),
                    )
                    return None
        return None


# 全局单例
_engine: Optional[AIEngine] = None


def get_engine() -> AIEngine:
    global _engine
    if _engine is None:
        _engine = AIEngine()
    return _engine
