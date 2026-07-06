"""
AI Mock 客户端 (用于离线测试 / 无网环境 / CI 加速)
- 不连外网, 直接返回 mock 响应
- 模拟 LLMResult 结构 (input_tokens / output_tokens / cost / duration_ms)
- 兼容 OpenAI 兼容协议, 模仿 (system, user) → assistant 流程
- 通过 NW_AI_MOCK=1 环境变量启用
- 通过 monkeypatch `app.ai.providers.create_client` 接入

使用方式:
  1. 启动时: from app.ai import mock; mock.install()  # 全局替换 create_client
  2. 测试时:  设 NW_AI_MOCK=1 环境变量
  3. 在 engine._do_write / _do_evaluate 里: 检测 NW_AI_MOCK → 调 mock_client.chat()
"""
from __future__ import annotations
import logging
import os
import time
from typing import Optional, Callable

from app.ai.registry import ModelConfig
from app.core.interfaces import LLMResult

_logger = logging.getLogger("NovelWriter.ai.mock")


# 多种任务 → 不同 mock 内容
_MOCK_TEMPLATES = {
    "write": (
        "门开了.\n\n"
        "他没回头, 但能感觉到身后的空气在动.\n\n"
        "那脚步声很轻, 但每一下都像踩在他脊椎上.\n\n"
        "灯还亮着.\n\n"
        "他终于转过身, 看见了她.\n\n"
        "他应该说话的, 但喉咙像被什么堵住了.\n\n"
        "她先开了口, 声音很平: '你瘦了.'\n\n"
        "他想说点什么, 但最后只点了点头.\n\n"
        "窗外的风把门又吹开了一条缝, 冷空气顺着那条缝钻进来.\n\n"
        "他没去关门."
    ),
    "evaluate": (
        '{"score": 78, '
        '"axes": {"plot": 13, "character": 12, "writing": 16, "rhythm": 13, "style": 12, "foreshadow": 12}, '
        '"summary": "mock 评估: 节奏稳, 角色有层次, 结尾有悬念. 建议加强对话驱动.", '
        '"issues": []}'
    ),
    "default": (
        "这是一段 mock 响应.\n\n"
        "AI 引擎在 mock 模式下不会真正调用 LLM.\n\n"
        "可以通过 NW_AI_MOCK=0 关闭此模式."
    ),
}


class MockClient:
    """Mock 客户端. 实现 create_client() 工厂返回的对象协议.

    - provider = "mock"
    - model_name = config.model_name
    - chat() 返回 LLMResult 含 content / usage / cost / duration_ms
    """
    provider = "mock"

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model_name = config.model_name
        self.max_tokens = config.max_tokens

    def _match_task(self, messages: list[dict]) -> str:
        """从 messages 推断任务类型 (write / evaluate / default)."""
        text = " ".join((m.get("content") or "") for m in messages).lower()
        if any(k in text for k in ["评估", "评分", "evaluate", "critic", "score"]):
            return "evaluate"
        if any(k in text for k in ["写作", "写", "write", "writer", "章节", "chapter"]):
            return "write"
        return "default"

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> LLMResult:
        # 模拟"思考"延迟 (但不要太久, smoke 会卡)
        time.sleep(0.05)
        task = self._match_task(messages)
        content = _MOCK_TEMPLATES.get(task, _MOCK_TEMPLATES["default"])
        # 推流 (不管 stream 参数, 都在有 on_chunk 时推一遍, 给 UI 流式显示)
        if on_chunk:
            for paragraph in content.split("\n\n"):
                if paragraph:
                    on_chunk(paragraph + "\n\n")
        # 算 input_tokens
        text_in = " ".join((m.get("content") or "") for m in messages)
        input_tokens = max(1, len(text_in) // 4)
        output_tokens = max(1, len(content) // 4)
        # 算 cost
        cost = (
            input_tokens * self.config.input_price / 1_000_000
            + output_tokens * self.config.output_price / 1_000_000
        )
        return LLMResult(
            content=content,
            model=self.model_name,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=round(cost, 6),
            duration_ms=50,
            finish_reason="stop",
            thinking="(mock 模式, 无思考过程)",
            raw={"mock": True, "task": task},
        )


# 工厂: 替换 app.ai.providers.create_client
_original_create_client = None
_installed = False


def install() -> None:
    """全局安装 mock 客户端. 把 app.ai.providers.create_client 替换为 mock 工厂."""
    global _original_create_client, _installed
    if _installed:
        return
    import app.ai.providers as _p
    _original_create_client = _p.create_client
    _p.create_client = _mock_create_client
    _installed = True
    _logger.info("[mock] install OK, 所有 LLM 调用将走 mock")


def uninstall() -> None:
    """还原. 撤销 mock, 恢复真 client."""
    global _original_create_client, _installed
    if not _installed or _original_create_client is None:
        return
    import app.ai.providers as _p
    _p.create_client = _original_create_client
    _original_create_client = None
    _installed = False
    _logger.info("[mock] uninstall OK, 恢复真 client")


def is_installed() -> bool:
    return _installed


def is_env_enabled() -> bool:
    """检测 NW_AI_MOCK 环境变量."""
    return os.environ.get("NW_AI_MOCK", "0") == "1"


def auto_install_if_env() -> None:
    """如果 NW_AI_MOCK=1, 自动安装 mock. 给 smoke / CLI 入口用."""
    if is_env_enabled():
        install()


def _mock_create_client(config: ModelConfig):
    return MockClient(config)
