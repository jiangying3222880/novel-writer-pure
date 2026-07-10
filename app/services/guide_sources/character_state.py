"""character_state 源适配器."""
from __future__ import annotations


class CharacterStateSource:
    source_id = "character_state"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.character_state import get_guides
        return get_guides(unit_id, project_id=project_id)
