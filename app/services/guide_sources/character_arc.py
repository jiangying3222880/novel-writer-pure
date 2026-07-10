"""character_arc 源适配器."""
from __future__ import annotations


class CharacterArcSource:
    source_id = "character_arc"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.character_arc_service import get_guides
        return get_guides(unit_id, project_id=project_id)
