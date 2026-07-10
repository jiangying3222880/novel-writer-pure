"""style 源适配器."""
from __future__ import annotations


class StyleSource:
    source_id = "style"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.style_fingerprint import get_guides
        return get_guides(unit_id, project_id=project_id)
