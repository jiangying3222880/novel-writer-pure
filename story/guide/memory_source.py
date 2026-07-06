"""
Memory Guide Source — 记忆一致性信号

从 memory_manager 获取记忆信号，转换为 DecisionSignal。
"""
from __future__ import annotations
from story.guide.collector import DecisionSignal


class MemoryGuideSource:
    """记忆引导源."""
    source_id = "memory"

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]:
        signals = []
        try:
            from app.services import memory_manager
            if hasattr(memory_manager, 'get_memory_signals'):
                mems = memory_manager.get_memory_signals(unit_id, project_id=project_id)
                for i, m in enumerate(mems[:5]):
                    signals.append(DecisionSignal(
                        guide_id=f"memory_{unit_id}_{i}",
                        source=self.source_id,
                        priority=getattr(m, 'priority', 0.5),
                        confidence=getattr(m, 'confidence', 0.7),
                        advice=getattr(m, 'advice', str(m)),
                        dimension="hook",
                    ))
        except Exception:
            pass
        return signals
