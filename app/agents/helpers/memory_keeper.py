"""
MemoryKeeper (记忆管家)
业务场景: 拼装 L1-L4 记忆 + 角色 + 压力 (供 Orchestrator 喂给写手).

默认实现: 调 services.memory_manager.assemble_for_writing.
"""
from __future__ import annotations
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.memory_keeper")


class MemoryKeeper(AgentBase):
    """记忆 (L1-L4 + 角色 + 压力 拼装)."""

    DEFAULT_KIND = ReportKind.MEMORY

    def __init__(self, *, name: str = "MemoryKeeper") -> None:
        super().__init__(name=name, role=AgentRole.MEMORY)

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        chapter_id = ctx.get("chapter_id", "")

        try:
            from app.services import memory_manager
            r = memory_manager.assemble_for_writing(
                project_id, chapter_id,
                include_anti_ai_tips=False,    # 反 AI 味由 Orchestrator 单独注入
                max_chars=2000,
            )
            return self._build_report(task, {
                "text": r.full_text,
                "zone": r.pressure_zone,
                "can_open_hook": r.can_open_hook,
                "char_count": len(r.full_text),
                "memory_chunks": len(r.sections) if hasattr(r, "sections") else 0,
            })
        except Exception as e:
            _logger.warning("[memory] 拼装失败: %s", e)
            return self._build_report(task, {
                "text": "",
                "zone": "green",
                "can_open_hook": True,
                "char_count": 0,
            }, warnings=[f"拼装失败: {e}"])
