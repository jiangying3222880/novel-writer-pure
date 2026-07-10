"""reader_signal 源适配器."""
from __future__ import annotations


class ReaderSignalSource:
    source_id = "reader_signal"

    def collect(self, unit_id: str, project_id: str = "") -> list:
        from app.services.reader_signal import get_guides
        return get_guides(unit_id, project_id=project_id)
