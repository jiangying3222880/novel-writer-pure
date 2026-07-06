"""
厂商客户端 (A5: 简化做 2 类)
1. OpenAI 兼容 (gpt / deepseek / 智谱 / 通义 / 文心 / kimi...)
2. Anthropic (claude)

A5.1: 流式输出 + 思考模式 (Claude 3.7+)
"""
from __future__ import annotations
import json
import logging
import time
from typing import Iterator, Optional, Callable

import httpx

from app.ai.registry import ModelConfig
from app.core.interfaces import LLMResult

_logger = logging.getLogger("NovelWriter.ai.providers")

# 共享 httpx 客户端 (连接池复用, 减少握手开销)
_http_client: Optional[httpx.Client] = None


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0),
            follow_redirects=True,
        )
    return _http_client


# ────────────────────── OpenAI 兼容 ──────────────────────

class OpenAICompatClient:
    """OpenAI 格式的客户端 (90% 国产模型都走这个)。"""
    provider = "openai_compat"

    def __init__(self, config: ModelConfig):
        self.config = config
        self.base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = config.api_key
        self.model_name = config.model_name
        self.max_tokens = config.max_tokens

    def _build_url(self, path: str = "/chat/completions") -> str:
        return f"{self.base_url}{path}"

    def _build_payload(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict:
        return {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, self.max_tokens),
            "stream": stream,
        }

    def _parse_response(self, data: dict, start: float) -> LLMResult:
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content", "")
        usage = data.get("usage", {})
        return LLMResult(
            content=content,
            model=self.model_name,
            provider=self.provider,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            duration_ms=int((time.time() - start) * 1000),
            finish_reason=choice.get("finish_reason", ""),
            raw=data,
        )

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
        if not self.api_key:
            raise ValueError(f"未配置 API key: {self.config.id}")
        url = self._build_url()
        payload = self._build_payload(messages, temperature, max_tokens, stream)
        start = time.time()
        try:
            resp = _get_http_client().post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            err_body = e.response.text[:200]
            raise RuntimeError(f"HTTP {e.response.status_code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}") from e
        return self._parse_response(data, start)

    def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Iterator[tuple[str, str]]:
        """流式 SSE 调用，yield (type, text) 元组。

        type 取值:
          - "thinking": 模型思考过程 (reasoning_content / DeepSeek-R1 等)
          - "content":  正式回复文本

        用法:
            for typ, text in client.chat_stream(messages):
                if typ == "thinking":
                    on_thinking(text)
                else:
                    on_chunk(text)
        """
        if not self.api_key:
            raise ValueError(f"未配置 API key: {self.config.id}")
        url = self._build_url()
        payload = self._build_payload(messages, temperature, max_tokens, stream=True)
        from app.ai.registry import get_registry
        cfg = get_registry().get(self.config.id) if get_registry() else None
        supports_thinking = cfg.supports_thinking if cfg else False
        try:
            with _get_http_client().stream(
                "POST", url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = (obj.get("choices", [{}])[0].get("delta", {}) or {})
                    # — 思考过程 —
                    reasoning = delta.get("reasoning_content", "") or delta.get("reasoning", "")
                    if reasoning:
                        yield ("thinking", reasoning)
                    # — 正文 —
                    chunk = delta.get("content", "")
                    if chunk:
                        yield ("content", chunk)
        except httpx.HTTPStatusError as e:
            err_body = e.response.text[:200]
            raise RuntimeError(f"HTTP {e.response.status_code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 流式调用失败: {e}") from e


# ────────────────────── Anthropic ──────────────────────

class AnthropicClient:
    """Anthropic 格式 (Claude 3.x)。"""
    provider = "anthropic"

    def __init__(self, config: ModelConfig):
        self.config = config
        self.base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = config.api_key
        self.model_name = config.model_name
        self.max_tokens = config.max_tokens

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
        if not self.api_key:
            raise ValueError(f"未配置 API key: {self.config.id}")
        # 转换 messages 格式: system 单独, user/assistant 列表
        system_parts = []
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                chat_msgs.append(m)

        payload = {
            "model": self.model_name,
            "max_tokens": min(max_tokens, self.max_tokens),
            "temperature": temperature,
            "system": "\n\n".join(system_parts) if system_parts else None,
            "messages": chat_msgs,
        }
        if kwargs.get("thinking"):
            payload["thinking"] = {"type": "enabled", "budget_tokens": 5000}

        url = f"{self.base_url}/v1/messages"
        start = time.time()
        try:
            resp = _get_http_client().post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            err_body = e.response.text[:200]
            raise RuntimeError(f"HTTP {e.response.status_code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}") from e

        # 解析 Anthropic 格式
        content_parts = data.get("content", [])
        text = ""
        thinking = ""
        for p in content_parts:
            if p.get("type") == "text":
                text += p.get("text", "")
            elif p.get("type") == "thinking":
                thinking += p.get("thinking", "")
        usage = data.get("usage", {})
        return LLMResult(
            content=text,
            model=self.model_name,
            provider=self.provider,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            duration_ms=int((time.time() - start) * 1000),
            finish_reason=data.get("stop_reason", ""),
            thinking=thinking,
            raw=data,
        )

    def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Iterator[tuple[str, str]]:
        """Anthropic 流式 event-stream，yield (type, text) 元组。

        type 取值:
          - "thinking": 思考过程 (thinking_delta)
          - "content":  正式回复文本 (text_delta)
        """
        if not self.api_key:
            raise ValueError(f"未配置 API key: {self.config.id}")
        system_parts = []
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                chat_msgs.append(m)
        payload: dict = {
            "model": self.model_name,
            "max_tokens": min(max_tokens, self.max_tokens),
            "temperature": temperature,
            "messages": chat_msgs,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if kwargs.get("thinking"):
            payload["thinking"] = {"type": "enabled", "budget_tokens": 5000}
        url = f"{self.base_url}/v1/messages"
        try:
            with _get_http_client().stream(
                "POST", url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "accept": "text/event-stream",
                },
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str:
                        continue
                    try:
                        obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    ev_type = obj.get("type", "")
                    if ev_type != "content_block_delta":
                        continue
                    delta = obj.get("delta", {}) or {}
                    delta_type = delta.get("type", "")
                    if delta_type == "thinking_delta":
                        text = delta.get("thinking", "")
                        if text:
                            yield ("thinking", text)
                    elif delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield ("content", text)
        except httpx.HTTPStatusError as e:
            err_body = e.response.text[:200]
            raise RuntimeError(f"HTTP {e.response.status_code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 流式调用失败: {e}") from e


# ────────────────────── 工厂 ──────────────────────

def create_client(config: ModelConfig):
    """根据 provider 字段创建对应客户端。"""
    if config.provider == "openai_compat":
        return OpenAICompatClient(config)
    elif config.provider == "anthropic":
        return AnthropicClient(config)
    else:
        raise ValueError(f"不支持的 provider: {config.provider}")


