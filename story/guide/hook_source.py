"""
Hook Guide Source — 伏笔管理信号

从 StoryState 的 hooks 获取伏笔信号。
"""
from __future__ import annotations
from story.guide.collector import DecisionSignal


class HookGuideSource:
    """伏笔引导源."""
    source_id = "hook"

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]:
        signals = []
        if state is None:
            return signals

        # 检查活跃伏笔
        active_hooks = state.active_hooks()
        for h in active_hooks:
            age = state.current_step - h.planted_at_step if h.planted_at_step > 0 else 0
            priority = min(1.0, 0.3 + age * 0.1)
            signals.append(DecisionSignal(
                guide_id=f"hook_active_{h.hook_id}",
                source=self.source_id,
                priority=priority,
                confidence=0.9,
                advice=f"活跃伏笔: {h.description[:50]} (age={age} steps)",
                dimension="hook",
                urgent=age > 5,
            ))

        # 检查承诺
        pending = state.pending_commitments()
        for c in pending:
            signals.append(DecisionSignal(
                guide_id=f"commit_{c.description[:20]}",
                source=self.source_id,
                priority=0.6,
                confidence=0.85,
                advice=f"待履行承诺: {c.description[:50]}",
                dimension="character",
            ))

        return signals
