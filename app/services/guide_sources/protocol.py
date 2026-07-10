"""
Guide Source Protocol — 引导源协议

每个源实现此协议，collect_guides() 统一调度。
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class GuideSource(Protocol):
    """引导源协议. 每个源必须实现 source_id 和 collect 方法."""
    source_id: str

    def collect(self, unit_id: str, project_id: str = "") -> list: ...
