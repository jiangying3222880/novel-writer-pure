"""memory 源适配器."""
from __future__ import annotations


class MemorySource:
    source_id = "memory"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.memory import get_guides
        return get_guides(unit_id, project_id=project_id)
