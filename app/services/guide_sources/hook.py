"""hook 源适配器."""
from __future__ import annotations


class HookSource:
    source_id = "hook"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.unit_hook_service import get_guides
        return get_guides(unit_id, project_id=project_id)
