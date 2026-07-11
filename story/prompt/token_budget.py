"""
Token Budget Optimizer — 跨片段优化 token 使用

在 SUC 编译时，根据 token 预算智能分配各段内容的长度。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenBudget:
    """Token 预算配置."""
    max_tokens: int = 4000
    system_ratio: float = 0.3      # system prompt 占比
    context_ratio: float = 0.4     # 上下文(角色/世界/伏笔)占比
    guide_ratio: float = 0.2       # Guide/Decision 占比
    reserve_ratio: float = 0.1     # 保留给输出/意外

    @property
    def system_budget(self) -> int:
        return int(self.max_tokens * self.system_ratio)

    @property
    def context_budget(self) -> int:
        return int(self.max_tokens * self.context_ratio)

    @property
    def guide_budget(self) -> int:
        return int(self.max_tokens * self.guide_ratio)

    @property
    def reserve_budget(self) -> int:
        return int(self.max_tokens * self.reserve_ratio)


def allocate_tokens(
    segments: list[tuple[str, str]],
    budget: TokenBudget,
) -> list[tuple[str, str]]:
    """根据预算分配各段 token 长度.

    Args:
        segments: [(label, content), ...] 各段内容
        budget: token 预算

    Returns:
        截断后的 [(label, truncated_content), ...]
    """
    if not segments:
        return []

    total_chars = sum(len(c) for _, c in segments)
    max_chars = budget.max_tokens * 2  # 粗略: 1 token ≈ 2 中文字

    if total_chars <= max_chars:
        return segments  # 不需要截断

    # 按比例分配
    ratios = {
        "system": budget.system_ratio,
        "context": budget.context_ratio,
        "guide": budget.guide_ratio,
    }

    result = []
    for label, content in segments:
        ratio = ratios.get(label, 0.1)
        char_budget = int(max_chars * ratio)
        if len(content) > char_budget:
            content = content[:char_budget] + "…(已截断)"
        result.append((label, content))

    return result


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数 (中英文混合)."""
    # 中文: ~1.5 token/字, 英文: ~0.25 token/word
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = len(text) - cn_chars
    return int(cn_chars * 1.5 + en_chars * 0.25)
