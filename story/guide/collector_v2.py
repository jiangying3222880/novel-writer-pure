"""
GuideCollector v4 — 5源信号收集器

从5个独立源收集 DecisionSignal，统一输出。
"""
from __future__ import annotations
import logging
from typing import Optional
from story.guide.collector import DecisionSignal
from story.guide.sources import GuideSource
from story.guide.pressure_source import PressureGuideSource
from story.guide.memory_source import MemoryGuideSource
from story.guide.consistency_source import ConsistencyGuideSource
from story.guide.voice_source import VoiceGuideSource
from story.guide.hook_source import HookGuideSource

_logger = logging.getLogger("NovelWriter.story.guide_collector_v2")


class GuideCollectorV2:
    """5源引导收集器."""

    def __init__(self, sources: Optional[list[GuideSource]] = None):
        if sources is None:
            self.sources = [
                PressureGuideSource(),
                MemoryGuideSource(),
                ConsistencyGuideSource(),
                VoiceGuideSource(),
                HookGuideSource(),
            ]
        else:
            self.sources = list(sources)

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None, max_signals: int = 20) -> list[DecisionSignal]:
        """从所有源收集信号，合并去重，按 priority 排序."""
        all_signals: list[DecisionSignal] = []

        for source in self.sources:
            try:
                signals = source.collect(
                    unit_id, project_id=project_id, state=state,
                )
                all_signals.extend(signals)
            except Exception as e:
                _logger.warning("Source %s failed: %s", source.source_id, e)

        # 去重 (按 guide_id)
        seen = set()
        unique = []
        for s in all_signals:
            if s.guide_id not in seen:
                seen.add(s.guide_id)
                unique.append(s)

        # 排序: urgent 优先, 然后按 priority 降序
        unique.sort(key=lambda s: (-int(s.urgent), -s.priority))

        return unique[:max_signals]
