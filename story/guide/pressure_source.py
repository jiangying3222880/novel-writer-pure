"""
Pressure Guide Source — 叙事压力信号

从 pressure 服务获取压力信号，转换为 DecisionSignal。
"""
from __future__ import annotations
from story.guide.collector import DecisionSignal


class PressureGuideSource:
    """压力引导源."""
    source_id = "pressure"

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]:
        signals = []
        try:
            from app.services import pressure
            if hasattr(pressure, 'get_pressure'):
                p = pressure.get_pressure(unit_id, project_id=project_id)
                if p:
                    level = getattr(p, 'level', 'normal')
                    score = getattr(p, 'score', 0.5)
                    urgency = level in ('high', 'critical')
                    signals.append(DecisionSignal(
                        guide_id=f"pressure_{unit_id}",
                        source=self.source_id,
                        priority=min(1.0, score),
                        confidence=0.8,
                        advice=f"叙事压力: {level} (score={score:.2f})",
                        dimension="pacing",
                        urgent=urgency,
                    ))
        except Exception:
            pass
        return signals
