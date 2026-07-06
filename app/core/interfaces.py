"""
接口契约 (B4: 完整做 ~100 行)
- 用 typing.Protocol 定义模块间契约
- 加新模块时实现接口即可
- 类型检查器会提示缺哪些方法
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable, Optional, Any
from dataclasses import dataclass


# ────────────────────── LLM 调用契约 ──────────────────────

@runtime_checkable
class LLMClient(Protocol):
    """LLM 客户端协议 (A5 厂商客户端实现此接口)。"""
    provider: str
    model_name: str

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs,
    ) -> dict:
        """同步调用。返回 {content, usage, finish_reason}。"""
        ...

    async def achat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs,
    ) -> dict:
        """异步调用。"""
        ...


# ────────────────────── 检索契约 ──────────────────────

@runtime_checkable
class Retriever(Protocol):
    """检索器协议 (D2 finder 实现此接口)。"""
    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        返回 [{content, source, score, metadata}, ...]
        """
        ...


# ────────────────────── 记忆契约 ──────────────────────

@runtime_checkable
class Memory(Protocol):
    """记忆系统协议 (E2 实现)。"""
    def store(self, key: str, content: str, level: str, **meta) -> None: ...
    def recall(self, key: str, level: str | None = None) -> list[str]: ...
    def forget(self, key: str) -> None: ...


# ────────────────────── 提示组装契约 ──────────────────────

@runtime_checkable
class PromptAssembler(Protocol):
    """提示组装器协议 (G2 prompt_assembler 实现)。"""
    def build(
        self,
        *,
        project_id: str,
        chapter_id: Optional[str] = None,
        task: str = "write",
    ) -> list[dict]:
        """
        组装 14 段 prompt (B2 拍板: 永久 4 + 按需 10)。
        返回 messages 列表 [{role, content}, ...]
        """
        ...


# ────────────────────── 评估契约 ──────────────────────

@runtime_checkable
class Evaluator(Protocol):
    """评估器协议 (critic / hook / 一致性 实现)。"""
    name: str
    def evaluate(self, chapter_id: str, content: str, **kwargs) -> dict:
        """
        返回 {score: float, dimensions: {...}, issues: [...], summary: str}
        """
        ...


# ────────────────────── Agent 契约 ──────────────────────

@runtime_checkable
class Agent(Protocol):
    """智能体协议 (编排 / 6 问 / subtext 等实现)。"""
    name: str
    role: str                       # main / assistant

    def run(self, context: dict) -> dict:
        """
        接收 context (项目状态/章节任务), 返回结果。
        编排 Agent 返回的 result 给写手 Agent 精炼。
        写手 Agent 返回 {content, token_usage, ...}。
        """
        ...


# ────────────────────── Service 契约 (M2.2 补) ──────────────────────

@runtime_checkable
class Service(Protocol):
    """业务服务协议 (app/services/* 全部实现)。

    任何暴露给 L3+ 层的 service 必须实现此协议, 便于:
      - container.get_protocol(Service) 拿全部服务
      - DI 测试时可注入 mock 实现
    """
    name: str                       # 服务唯一标识, e.g. "project_service"

    def health_check(self) -> dict:
        """返回 {ok: bool, message: str, latency_ms: int}。"""
        ...


# ────────────────────── Validator 契约 (G11-G16) ──────────────────────

@runtime_checkable
class Validator(Protocol):
    """校验器协议 (app/validators/* 实现)。"""
    name: str                       # e.g. "pov", "repetition", "voice"
    category: str                   # pov / props / setting / voice / space / repetition

    def validate(self, text: str, *, context: Optional[dict] = None) -> list[dict]:
        """
        返回 [{start, end, message, severity, suggestion}, ...]
        severity: "error" | "warning" | "info"
        """
        ...


# ────────────────────── Storage 契约 ──────────────────────

@runtime_checkable
class Storage(Protocol):
    """存储协议 (file_store / db / knowledge index 统一接口)。

    任何持久化实现都需提供 read / write / exists / delete 四件套,
    业务层不直接 import 具体存储后端。
    """
    def read(self, key: str) -> Optional[bytes]: ...
    def write(self, key: str, data: bytes) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> bool: ...


# ────────────────────── 通用结果 ──────────────────────

@dataclass
class LLMResult:
    """LLM 调用统一结果。"""
    content: str = ""
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    finish_reason: str = ""
    thinking: str = ""                 # 思考过程 (Claude 3.7 / o1)
    raw: Any = None                    # 原始返回

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": self.cost,
            "duration_ms": self.duration_ms,
            "finish_reason": self.finish_reason,
            "thinking": self.thinking,
        }
