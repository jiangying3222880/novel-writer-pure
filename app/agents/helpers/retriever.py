"""
Retriever (检索 Agent)
业务场景: 按章节任务动态取文风语料 + 桥段 (~200 字, 0 污染).

默认实现: 走 app.knowledge.finder.extract_for_prompt (BM25 + 向量混合).
"""
from __future__ import annotations
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.retriever")


class Retriever(AgentBase):
    """检索 (RAG)."""

    DEFAULT_KIND = ReportKind.RETRIEVE

    def __init__(self, *, name: str = "Retriever", max_chars: int = 200) -> None:
        super().__init__(name=name, role=AgentRole.RETRIEVER)
        self.max_chars = max_chars

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        chapter_id = ctx.get("chapter_id", "")

        # 拼 query: 章节标题 + 题材
        query_parts: list[str] = []
        try:
            from app.services import chapter_service, project_service
            ch = chapter_service.get(chapter_id) or {}
            if ch.get("title"):
                query_parts.append(ch["title"])
            if ch.get("scene_context"):
                query_parts.append(ch["scene_context"][:200])
            pr = project_service.get(project_id) or {}
            if pr.get("genre"):
                query_parts.append(pr["genre"])
        except Exception as e:
            _logger.debug("[retriever] 加载章节/项目失败: %s", e)

        query = " ".join(query_parts).strip()
        if not query:
            return self._build_report(task, {
                "snippets": "",
                "hits": 0,
                "query": "",
            })

        # 走 finder
        try:
            from app.knowledge import finder as _finder
            snippet = _finder.extract_for_prompt(
                query, top_k=3, max_total_chars=self.max_chars,
            )
            return self._build_report(task, {
                "snippets": snippet,
                "hits": 1 if snippet else 0,
                "query": query,
            })
        except Exception as e:
            _logger.warning("[retriever] 检索失败: %s", e)
            return self._build_report(task, {
                "snippets": "",
                "hits": 0,
                "query": query,
                "error": str(e),
            }, warnings=[f"检索失败: {e}"])
