"""pressure 源适配器."""
from __future__ import annotations


class PressureSource:
    source_id = "pressure"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.pressure import get_guides
        return get_guides(unit_id, project_id=project_id)
