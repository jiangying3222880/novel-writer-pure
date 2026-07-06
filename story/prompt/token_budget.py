"""
Token Budget Optimizer — token预算优化器

智能分配 token 预算，确保关键信息不被截断。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenBudget:
    """Token 预算分配."""
    total: int = 2000
    structural: int = 0
    dynamic: int = 0
    causal: int = 0
    instruction: int = 0
    reserved: int = 200  # 保留给系统提示

    @property
    def available(self) -> int:
        return self.total - self.reserved


def estimate_tokens(text: str) -> int:
    """估算文本 token 数 (中文约 1 token/字)."""
    if not text:
        return 0
    return max(1, len(text))


def allocate_budget(
    total: int = 2000,
    *,
    structural_weight: float = 0.3,
    dynamic_weight: float = 0.3,
    causal_weight: float = 0.2,
    instruction_weight: float = 0.2,
    reserved: int = 200,
) -> TokenBudget:
    """按权重分配 token 预算."""
    available = total - reserved
    return TokenBudget(
        total=total,
        structural=int(available * structural_weight),
        dynamic=int(available * dynamic_weight),
        causal=int(available * causal_weight),
        instruction=int(available * instruction_weight),
        reserved=reserved,
    )


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """将文本截断到指定 token 数."""
    if not text:
        return ""
    tokens = estimate_tokens(text)
    if tokens <= max_tokens:
        return text
    # 按比例截断
    ratio = max_tokens / tokens
    target_chars = int(len(text) * ratio)
    return text[:target_chars] + "...(截断)"


def optimize_suc_tokens(
    structural: str,
    dynamic: str,
    causal: str,
    instruction: str,
    total_budget: int = 2000,
) -> tuple[str, str, str, str]:
    """优化 SUC 各部分的 token 分配."""
    budget = allocate_budget(total_budget)

    return (
        truncate_to_budget(structural, budget.structural),
        truncate_to_budget(dynamic, budget.dynamic),
        truncate_to_budget(causal, budget.causal),
        truncate_to_budget(instruction, budget.instruction),
    )
