"""
GuideSource Protocol — 引导源协议定义

每个源实现 GuideSource 协议，输出 DecisionSignal 列表。
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from story.guide.collector import DecisionSignal


@runtime_checkable
class GuideSource(Protocol):
    """引导源协议."""
    source_id: str

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]: ...
