"""
LLM Client (Phase 3 M2).

同步 LLM 客户端, PySide6 主线程用 QThread 包装流式.
- 协议: OpenAI 兼容 (覆盖 ~80% 厂商) + Anthropic Messages
- 27 厂商预设 (从 2.0 继承, 见 _archived/.../ai_client.py)
- Fallback 链: 按 priority 顺序自动切换

设计原则:
  - 不引入 asyncio (与 v4 同步 + QThread 模型一致)
  - 单 LLMClient 复用 httpx.Client (避免每调用建连接)
  - 流式用 httpx.stream + SSE chunk 解析
  - 失败 fallback: 第一个 provider 抛异常时试下一个
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterator, Optional

import httpx

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Enums & dataclasses
# --------------------------------------------------------------------- #

class ProviderType(str, Enum):
    """协议分支. 一个 provider_type 对应一套请求格式."""
    OPENAI_COMPAT = "openai_compat"  # OpenAI / DeepSeek / Moonshot / 智谱 / Ollama / 阿里通义 / 自定义
    ANTHROPIC = "anthropic"          # Anthropic Messages API


@dataclass
class ProviderConfig:
    """单个 LLM provider 配置 (用户可定义多个, 按 priority 排序)."""
    name: str                       # 唯一标识, e.g. "deepseek-main"
    provider_type: ProviderType
    api_base: str                   # e.g. https://api.deepseek.com/v1
    api_key: str                    # 留空表示无鉴权 (ollama 本地)
    model: str                      # e.g. deepseek-chat
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 120.0
    priority: int = 0               # 越小越优先


@dataclass
class ChatMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class UsageRecord:
    """一次调用的 token / 耗时统计."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider: str = ""
    model: str = ""
    step: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@dataclass
class ChatResponse:
    content: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = "stop"
    usage_record: Optional[UsageRecord] = None


# --------------------------------------------------------------------- #
# Provider 分组显示
# --------------------------------------------------------------------- #

PROVIDER_GROUPS: dict[str, str] = {
    "overseas":    "🌐 国际",
    "china":       "🌏 国内",
    "coding_plan": "💻 Coding Plan",
    "aggregator":  "🔀 聚合",
    "local":       "🏠 本地",
}

# --------------------------------------------------------------------- #
# 27+ 厂商预设（每项含 models 列表、group、默认温度）
# --------------------------------------------------------------------- #

# 中文显示名（与 PROVIDER_PRESETS key 一一对应）
PROVIDER_PRESET_DISPLAY_NAMES: dict[str, str] = {
    # --- 国际 ---
    "openai":            "OpenAI",
    "anthropic":         "Anthropic",
    "google":            "Google Gemini",
    "xai":               "xAI Grok",
    "mistral":           "Mistral",
    "cohere":            "Cohere",
    # --- 国内 ---
    "deepseek":          "DeepSeek",
    "moonshot":          "Moonshot",
    "zhipu":             "智谱 GLM",
    "baidu":             "百度文心",
    "alibaba":           "阿里百炼",
    "qwen":              "通义千问",
    "tencent":           "腾讯混元",
    "yi":                "零一万物 Yi",
    "minimax":           "MiniMax",
    "minimax_coding":    "MiniMax Coding",
    "step":              "阶跃星辰 Step",
    "spark":             "讯飞星火",
    "siliconflow":       "SiliconFlow",
    "bailian_coding":    "百炼 Coding Plan",
    # --- 聚合 / 转发 ---
    "openrouter":        "OpenRouter",
    "groq":              "Groq",
    "together":           "Together AI",
    "fireworks":         "Fireworks AI",
    "perplexity":        "Perplexity",
    # --- 本地 ---
    "ollama":            "Ollama",
    # --- 自定义 ---
    "custom":            "自定义",
}


def get_provider_preset(preset_name: str) -> dict:
    """查表, 找不到返回 custom 预设."""
    return PROVIDER_PRESETS.get(preset_name, PROVIDER_PRESETS["custom"])


def list_providers_by_group() -> dict[str, list[str]]:
    """返回 {group_key: [preset_key, ...]}，供 UI 按组填充."""
    out: dict[str, list[str]] = {g: [] for g in PROVIDER_GROUPS}
    for key, p in PROVIDER_PRESETS.items():
        out[p.get("group", "local")].append(key)
    return out


def _m(id, max_out, ctx, enabled=True):
    return {"id": id, "max_output": max_out, "context_window": ctx, "enabled": enabled}


PROVIDER_PRESETS: dict[str, dict] = {
    # ===== 🌐 国际 =====
    "openai": {
        "provider_type": "openai_compat", "group": "overseas",
        "api_base": "https://api.openai.com/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("gpt-4o",               16384, 128000),
            _m("gpt-4o-mini",          16384, 128000),
            _m("gpt-4.5-turbo",        16384, 128000),
            _m("o3",                    131072, 200000),
            _m("o4-mini",              65536, 128000),
        ],
    },
    "anthropic": {
        "provider_type": "anthropic", "group": "overseas",
        "api_base": "https://api.anthropic.com/v1",
        "default_temperature": 1.0, "writing_temperature": 1.0,
        "models": [
            _m("claude-sonnet-4-20250514", 8192, 200000),
            _m("claude-3-5-sonnet-20241022", 8192, 200000),
            _m("claude-3-5-haiku-20240307", 8192, 200000),
            _m("claude-3-opus-20240229", 4096, 200000),
        ],
    },
    "google": {
        "provider_type": "openai_compat", "group": "overseas",
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "default_temperature": 0.9, "writing_temperature": 1.0,
        "models": [
            _m("gemini-2.5-pro-preview-06-05", 8192, 1048576),
            _m("gemini-2.0-flash",               8192, 1048576),
            _m("gemini-1.5-pro",                 8192, 1048576),
            _m("gemini-1.5-flash",               8192, 1048576),
        ],
    },
    "xai": {
        "provider_type": "openai_compat", "group": "overseas",
        "api_base": "https://api.x.ai/v1",
        "default_temperature": 0.6, "writing_temperature": 1.0,
        "models": [
            _m("grok-3",      131072, 131072),
            _m("grok-2",      131072, 131072),
            _m("grok-beta",   131072, 131072),
        ],
    },
    "mistral": {
        "provider_type": "openai_compat", "group": "overseas",
        "api_base": "https://api.mistral.ai/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("mistral-large-latest", 131072, 128000),
            _m("mistral-medium-latest", 131072, 128000),
            _m("mistral-small-latest",  131072, 128000),
        ],
    },
    "cohere": {
        "provider_type": "openai_compat", "group": "overseas",
        "api_base": "https://api.cohere.ai/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("command-r-plus",  131072, 128000),
            _m("command-r",        131072, 128000),
        ],
    },

    # ===== 🌏 国内 =====
    "deepseek": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.deepseek.com",
        "default_temperature": 0.7, "writing_temperature": 1.5,
        "models": [
            _m("deepseek-v4-flash",   393216, 1000000, enabled=True),
            _m("deepseek-v4-pro",     393216, 1000000, enabled=True),
            _m("deepseek-chat",       393216, 1000000, enabled=False),
            _m("deepseek-reasoner",   393216, 1000000, enabled=False),
        ],
    },
    "moonshot": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.moonshot.cn/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("moonshot-v1-8k",   8192,   128000),
            _m("moonshot-v1-32k",  32768,  128000),
            _m("moonshot-v1-128k", 131072, 1000000),
        ],
    },
    "zhipu": {
        "provider_type": "anthropic", "group": "china",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("glm-4",         4096,   128000),
            _m("glm-4-plus",    4096,   128000),
            _m("glm-4-airx",    4096,   128000),
            _m("glm-4-flash",    4096,   128000),
        ],
    },
    "baidu": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("ernie-4.0-8k",         4096,   128000),
            _m("ernie-4.0-8k-preview",  4096,   128000),
            _m("ernie-3.5-8k-preview",  4096,   128000),
            _m("ernie-speed-8k",        4096,   128000),
            _m("ernie-speed-128k",      4096,   128000),
            _m("ernie-lite-8k",        4096,   128000),
        ],
    },
    "alibaba": {
        "provider_type": "anthropic", "group": "china",
        "api_base": "https://dashscope.aliyuncs.com/apps/anthropic",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("qwen3.6-max-preview", 65536,  262144),
            _m("qwen3.6-plus",       65536,  1000000),
            _m("qwen3.5-plus",       65536,  1000000),
            _m("qwen3.5-flash",      65536,  1000000),
            _m("qwen3.5-max",        65536,  262144),
            _m("qwen-turbo",         16384,  1000000),
            _m("qwen-plus",          32768,  1000000),
            _m("qwen-max",           8192,   131072),
        ],
    },
    "qwen": {
        "provider_type": "anthropic", "group": "china",
        "api_base": "https://dashscope.aliyuncs.com/apps/anthropic",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("qwen3.6-max-preview", 65536,  262144),
            _m("qwen3.6-plus",       65536,  1000000),
            _m("qwen3.5-plus",       65536,  1000000),
            _m("qwen3.5-flash",      65536,  1000000),
        ],
    },
    "tencent": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.lkeap.cloud.tencent.com/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("hunyuan-pro",  4096,  128000),
            _m("hunyuan-standard", 4096, 128000),
            _m("hunyuan-flash", 4096,  128000),
        ],
    },
    "yi": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.lingyiwanwu.com/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("yi-large",    4096,   160000),
            _m("yi-medium",   4096,   32000),
            _m("yi-light",    4096,   16000),
        ],
    },
    "minimax": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.minimaxi.com/v1",
        "default_temperature": 0.9, "writing_temperature": 0.9,
        "models": [
            _m("MiniMax-M2.7",           131072, 204800, enabled=True),
            _m("MiniMax-M2.7-highspeed", 131072, 204800, enabled=False),
            _m("MiniMax-M2.5",           131072, 204800, enabled=False),
            _m("MiniMax-M2.5-highspeed", 131072, 204800, enabled=False),
            _m("MiniMax-M2.1",           131072, 204800, enabled=False),
            _m("MiniMax-M2.1-highspeed", 131072, 204800, enabled=False),
            _m("MiniMax-M2",             131072, 204800, enabled=False),
            _m("MiniMax-Text-01",         40000, 1000192, enabled=False),
        ],
    },
    "minimax_coding": {
        "provider_type": "anthropic", "group": "coding_plan",
        "api_base": "https://api.minimaxi.com/anthropic",
        "default_temperature": 0.9, "writing_temperature": 0.9,
        "models": [
            _m("MiniMax-M2.7",  131072, 204800, enabled=True),
            _m("MiniMax-M2.5",  131072, 204800, enabled=True),
            _m("MiniMax-M2.1",  131072, 204800, enabled=False),
            _m("MiniMax-M2",    131072, 204800, enabled=False),
        ],
    },
    "step": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://api.stepfun.com/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("step-1-8k",   8192,  128000),
            _m("step-1-32k",  32768, 128000),
            _m("step-1-128k", 131072, 128000),
        ],
    },
    "spark": {
        "provider_type": "openai_compat", "group": "china",
        "api_base": "https://spark-api-open.xf-yun.com/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("generalv3.5", 4096,  128000),
            _m("generalv3",   4096,  128000),
            _m("generalv2",   4096,  128000),
        ],
    },
    "siliconflow": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://api.siliconflow.cn/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("deepseek-ai/DeepSeek-V3",   16384, 128000),
            _m("deepseek-ai/DeepSeek-V2.5",  16384, 128000),
            _m("Qwen/Qwen2.5-72B-Instruct", 16384, 128000),
            _m("THUDM/GLM-4-9B-Chat",       4096,  128000),
        ],
    },
    "bailian_coding": {
        "provider_type": "anthropic", "group": "coding_plan",
        "api_base": "https://dashscope.aliyuncs.com/apps/anthropic",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("qwen3.5-plus",    65536,  1000000, enabled=True),
            _m("qwen3-max-2026-01-23", 65536, 262144, enabled=True),
            _m("qwen3-coder-plus", 65536, 1000000),
            _m("glm-5",            131072, 200000, enabled=True),
            _m("glm-4.7",          131072, 200000, enabled=True),
            _m("kimi-k2.5",        32768,  262144, enabled=True),
            _m("MiniMax-M2.5",     131072, 204800, enabled=True),
        ],
    },

    # ===== 🔀 聚合 =====
    "openrouter": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://openrouter.ai/api/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("anthropic/claude-3.5-sonnet",       8192, 200000),
            _m("anthropic/claude-3-opus",            8192, 200000),
            _m("openai/gpt-4o",                      16384, 128000),
            _m("deepseek/deepseek-chat-v3",          16384, 128000),
            _m("google/gemini-2.0-flash",             8192, 1048576),
        ],
    },
    "groq": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://api.groq.com/openai/v1",
        "default_temperature": 0.6, "writing_temperature": 1.0,
        "models": [
            _m("llama-3.1-70b-versatile", 131072, 128000),
            _m("llama-3.3-70b-versatile",  131072, 128000),
            _m("mixtral-8x7b-32768",       32768,  128000),
        ],
    },
    "together": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://api.together.xyz/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 131072, 128000),
            _m("meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", 131072, 128000),
            _m("deepseek-ai/DeepSeek-V3",                       16384, 128000),
        ],
    },
    "fireworks": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://api.fireworks.ai/inference/v1",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("accounts/fireworks/models/llama-v3p1-70b-instruct", 131072, 128000),
            _m("accounts/fireworks/models/deepseek-v3",              16384, 128000),
        ],
    },
    "perplexity": {
        "provider_type": "openai_compat", "group": "aggregator",
        "api_base": "https://api.perplexity.ai",
        "default_temperature": 0.7, "writing_temperature": 1.0,
        "models": [
            _m("llama-3.1-sonar-large-128k-online", 131072, 128000),
            _m("sonar",                              32768,  128000),
            _m("sonar-pro",                           32768,  128000),
        ],
    },

    # ===== 🏠 本地 =====
    "ollama": {
        "provider_type": "openai_compat", "group": "local",
        "api_base": "http://localhost:11434/v1",
        "default_temperature": 0.7, "writing_temperature": 0.9,
        "models": [
            _m("llama3.1",    8192,   128000),
            _m("qwen2.5",     8192,   128000),
            _m("deepseek-v3",  8192,   128000),
            _m("mistral",     8192,   128000),
        ],
    },

    # ===== 自定义 =====
    "custom": {
        "provider_type": "openai_compat", "group": "local",
        "api_base": "http://localhost:11434/v1",
        "default_temperature": 0.7, "writing_temperature": 0.9,
        "models": [
            _m("custom-model", 4096, 128000),
        ],
    },
}


# --------------------------------------------------------------------- #
# LLMClient
# --------------------------------------------------------------------- #

class LLMClient:
    """同步 LLM 客户端. 线程安全 (单个 httpx.Client 复用)."""

    def __init__(self) -> None:
        self._providers: list[ProviderConfig] = []
        self._http: Optional[httpx.Client] = None

    # ---- lifecycle ----

    def _get_http(self) -> httpx.Client:
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(timeout=httpx.Timeout(120.0))
        return self._http

    def close(self) -> None:
        if self._http and not self._http.is_closed:
            self._http.close()

    # ---- provider 配置 ----

    def configure(self, providers: list[ProviderConfig]) -> None:
        self._providers = sorted(providers, key=lambda p: p.priority)

    @property
    def providers(self) -> list[ProviderConfig]:
        return list(self._providers)

    # ---- 非流式 ----

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        step: str = "",
    ) -> ChatResponse:
        if not self._providers:
            raise RuntimeError("LLMClient: no providers configured")
        errors: list[str] = []
        for provider in self._providers:
            try:
                return self._call_one(provider, messages, temperature, max_tokens, step)
            except Exception as e:
                log.warning(f"[LLM] {provider.name} failed: {e}")
                errors.append(f"{provider.name}: {e}")
        raise RuntimeError("All providers failed:\n" + "\n".join(errors))

    # ---- 流式 ----

    def chat_stream(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        step: str = "",
    ) -> Iterator[str]:
        if not self._providers:
            raise RuntimeError("LLMClient: no providers configured")
        errors: list[str] = []
        for provider in self._providers:
            try:
                yield from self._call_one_stream(provider, messages, temperature, max_tokens)
                return
            except Exception as e:
                log.warning(f"[LLM] {provider.name} stream failed: {e}")
                errors.append(f"{provider.name}: {e}")
        raise RuntimeError("All providers failed:\n" + "\n".join(errors))

    # ---- 内部: 调一个 provider (非流式) ----

    def _call_one(
        self,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        step: str,
    ) -> ChatResponse:
        t0 = time.time()
        client = self._get_http()

        if provider.provider_type == ProviderType.ANTHROPIC:
            content, tokens_in, tokens_out, model = self._call_anthropic(
                client, provider, messages, temperature, max_tokens,
            )
        else:
            content, tokens_in, tokens_out, model = self._call_openai_compat(
                client, provider, messages, temperature, max_tokens,
            )

        duration_ms = int((time.time() - t0) * 1000)
        usage = UsageRecord(
            provider=provider.name,
            model=model,
            step=step,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
        )
        return ChatResponse(
            content=content,
            model=model,
            provider=provider.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usage_record=usage,
        )

    # ---- 内部: 调一个 provider (流式) ----

    def _call_one_stream(
        self,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        client = self._get_http()
        if provider.provider_type == ProviderType.ANTHROPIC:
            yield from self._call_anthropic_stream(
                client, provider, messages, temperature, max_tokens,
            )
        else:
            yield from self._call_openai_compat_stream(
                client, provider, messages, temperature, max_tokens,
            )

    # ---- OpenAI 兼容 (非流式) ----

    def _call_openai_compat(
        self,
        client: httpx.Client,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int, str]:
        url = f"{provider.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }
        payload = {
            "model": provider.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        resp = client.post(url, json=payload, headers=headers, timeout=provider.timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {}) or {}
        return (
            content,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            data.get("model", provider.model),
        )

    # ---- OpenAI 兼容 (流式 SSE) ----

    def _call_openai_compat_stream(
        self,
        client: httpx.Client,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        url = f"{provider.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }
        payload = {
            "model": provider.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with client.stream("POST", url, json=payload, headers=headers, timeout=provider.timeout) as resp:
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
                delta = obj.get("choices", [{}])[0].get("delta", {}) or {}
                chunk = delta.get("content", "")
                if chunk:
                    yield chunk

    # ---- Anthropic (非流式) ----

    def _call_anthropic(
        self,
        client: httpx.Client,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int, str]:
        url = f"{provider.api_base.rstrip('/')}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        }
        system_parts = [m.content for m in messages if m.role == "system"]
        user_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages if m.role in ("user", "assistant")
        ]
        payload: dict = {
            "model": provider.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        resp = client.post(url, json=payload, headers=headers, timeout=provider.timeout)
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage", {}) or {}
        return (
            text,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            data.get("model", provider.model),
        )

    # ---- Anthropic (流式 SSE) ----

    def _call_anthropic_stream(
        self,
        client: httpx.Client,
        provider: ProviderConfig,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        """Anthropic Messages API 流式 (event-stream 格式).

        Event types:
          - message_start:  {type, message:{id,model,usage:{input_tokens}}}
          - content_block_start:  {type, index, content_block:{type,text}}
          - content_block_delta:  {type, index, delta:{type:"text_delta", text}}
          - content_block_stop:   {type, index}
          - message_delta:        {type, delta:{stop_reason}, usage:{output_tokens}}
          - message_stop:         {type}
        """
        url = f"{provider.api_base.rstrip('/')}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
            "accept": "text/event-stream",
        }
        system_parts = [m.content for m in messages if m.role == "system"]
        user_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages if m.role in ("user", "assistant")
        ]
        payload: dict = {
            "model": provider.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        with client.stream("POST", url, json=payload, headers=headers, timeout=provider.timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                # Anthropic event-stream: 行分两类
                # - "event: <type>"  事件名
                # - "data: <json>"   事件体
                if line.startswith("event:"):
                    continue  # 事件名, data 行紧跟
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
                if delta.get("type") != "text_delta":
                    continue
                chunk = delta.get("text", "")
                if chunk:
                    yield chunk


# --------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------- #

_client_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """单例."""
    global _client_instance
    if _client_instance is None:
        _client_instance = LLMClient()
    return _client_instance


def get_provider_preset(preset_name: str) -> dict:
    """查表, 找不到返回 custom 预设."""
    return PROVIDER_PRESETS.get(preset_name, PROVIDER_PRESETS["custom"])
