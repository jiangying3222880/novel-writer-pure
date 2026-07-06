"""
Consistency Guide Source — 逻辑一致性信号

从 consistency 服务获取一致性信号。
"""
from __future__ import annotations
from story.guide.collector import DecisionSignal


class ConsistencyGuideSource:
    """一致性引导源."""
    source_id = "consistency"

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]:
        signals = []
        try:
            from app.services import consistency
            if hasattr(consistency, 'check_unit'):
                issues = consistency.check_unit(unit_id, project_id=project_id)
                for i, issue in enumerate(issues[:5]):
                    severity = getattr(issue, 'severity', 0.5)
                    signals.append(DecisionSignal(
                        guide_id=f"consistency_{unit_id}_{i}",
                        source=self.source_id,
                        priority=severity,
                        confidence=0.85,
                        advice=getattr(issue, 'message', str(issue)),
                        dimension="character",
                        urgent=severity > 0.7,
                    ))
        except Exception:
            pass
        return signals
