"""
Voice Guide Source — 风格一致性信号

从 voice_profile 服务获取风格信号。
"""
from __future__ import annotations
from story.guide.collector import DecisionSignal


class VoiceGuideSource:
    """风格引导源."""
    source_id = "voice"

    def collect(self, unit_id: str, *, project_id: str = "",
                state=None) -> list[DecisionSignal]:
        signals = []
        try:
            from app.services import voice_profile
            if hasattr(voice_profile, 'check_voice'):
                issues = voice_profile.check_voice(unit_id, project_id=project_id)
                for i, issue in enumerate(issues[:3]):
                    signals.append(DecisionSignal(
                        guide_id=f"voice_{unit_id}_{i}",
                        source=self.source_id,
                        priority=getattr(issue, 'priority', 0.5),
                        confidence=0.75,
                        advice=getattr(issue, 'advice', str(issue)),
                        dimension="style",
                    ))
        except Exception:
            pass
        return signals
