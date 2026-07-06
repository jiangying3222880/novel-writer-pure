"""
Orchestrator v4 — Agent 编排器

协调多个 Agent 在隔离中执行，合并结果。
"""
from __future__ import annotations
import logging
from typing import Any, Optional
from app.agents.base import AgentTask, AgentReport
from app.agents.isolation import IsolationKernel
from app.agents.writer import WriterAgent
from app.agents.reader import ReaderAgent
from app.agents.critic import CriticAgent
from app.agents.memory_agent import MemoryAgent

_logger = logging.getLogger("NovelWriter.agents.orchestrator_v4")


class OrchestratorV4:
    """v4 编排器 — 协调多个 Agent."""

    def __init__(self):
        self.agents = {
            "writer": IsolationKernel(WriterAgent()),
            "reader": IsolationKernel(ReaderAgent()),
            "critic": IsolationKernel(CriticAgent()),
            "memory": IsolationKernel(MemoryAgent()),
        }

    def run(
        self,
        unit_id: str,
        project_id: str = "",
        *,
        state=None,
        guides: list = None,
        context: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """运行完整编排流程."""
        if context is None:
            context = {}
        if guides is None:
            guides = []

        # Step 1: Memory Agent — 收集记忆
        memory_task = AgentTask(
            unit_id=unit_id,
            project_id=project_id,
            state=state,
            context=context,
        )
        memory_report = self.agents["memory"].run(memory_task)

        # Step 2: Writer Agent — 生成内容
        writer_context = dict(context)
        writer_context["memories"] = memory_report.data.get("memories", [])
        writer_task = AgentTask(
            unit_id=unit_id,
            project_id=project_id,
            state=state,
            context=writer_context,
        )
        writer_report = self.agents["writer"].run(writer_task)

        # Step 3: Reader Agent — 评估
        reader_context = {"content": writer_report.data.get("content", "")}
        reader_task = AgentTask(
            unit_id=unit_id,
            project_id=project_id,
            context=reader_context,
        )
        reader_report = self.agents["reader"].run(reader_task)

        # Step 4: Critic Agent — 检查
        critic_context = {"content": writer_report.data.get("content", "")}
        critic_task = AgentTask(
            unit_id=unit_id,
            project_id=project_id,
            context=critic_context,
        )
        critic_report = self.agents["critic"].run(critic_task)

        # 合并结果
        return {
            "ok": writer_report.ok,
            "content": writer_report.data.get("content", ""),
            "score": reader_report.data.get("score", 0),
            "critic_score": critic_report.data.get("score", 0),
            "issues": critic_report.data.get("issues", []),
            "memories": memory_report.data.get("memories", []),
            "reports": {
                "writer": writer_report.to_dict(),
                "reader": reader_report.to_dict(),
                "critic": critic_report.to_dict(),
                "memory": memory_report.to_dict(),
            },
        }

    def get_metrics(self) -> dict:
        return {
            name: kernel.get_metrics().__dict__
            for name, kernel in self.agents.items()
        }
