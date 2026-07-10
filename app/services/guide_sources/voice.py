"""voice 源适配器."""
from __future__ import annotations


class VoiceSource:
    source_id = "voice"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.voice_profile import get_guides
        return get_guides(unit_id, project_id=project_id)
