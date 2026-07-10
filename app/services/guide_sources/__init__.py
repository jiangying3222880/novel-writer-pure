"""
Guide Sources — 适配器注册表

所有引导源在此注册，collect_guides() 统一调度。
"""
from __future__ import annotations

from app.services.guide_sources.pressure import PressureSource
from app.services.guide_sources.memory import MemorySource
from app.services.guide_sources.consistency import ConsistencySource
from app.services.guide_sources.voice import VoiceSource
from app.services.guide_sources.hook import HookSource
from app.services.guide_sources.style import StyleSource
from app.services.guide_sources.character_state import CharacterStateSource
from app.services.guide_sources.character_arc import CharacterArcSource
from app.services.guide_sources.unit_event import UnitEventSource
from app.services.guide_sources.reader_signal import ReaderSignalSource

# 所有源按字母序注册 (与原 collect_guides 顺序一致)
ALL_SOURCES = [
    CharacterArcSource(),
    CharacterStateSource(),
    ConsistencySource(),
    HookSource(),
    MemorySource(),
    PressureSource(),
    ReaderSignalSource(),
    StyleSource(),
    UnitEventSource(),
    VoiceSource(),
]
