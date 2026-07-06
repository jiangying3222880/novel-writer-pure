"""
Isolation Kernel — Agent 隔离执行器

确保每个 Agent 在独立上下文中运行，不互相干扰。
"""
from __future__ import annotations
import logging
from typing import Any, Optional
from app.agents.base import AgentBase, AgentTask, AgentReport

_logger = logging.getLogger("NovelWriter.agents.isolation")


class IsolationKernel:
    """隔离内核 — 包装 Agent 执行."""

    def __init__(self, agent: AgentBase):
        self.agent = agent
        self._context: dict[str, Any] = {}

    def run(self, task: AgentTask) -> AgentReport:
        """在隔离上下文中执行 Agent."""
        # 创建隔离上下文 (深拷贝)
        isolated_task = AgentTask(
            id=task.id,
            unit_id=task.unit_id,
            project_id=task.project_id,
            context=dict(task.context),
            state=task.state,
            guides=list(task.guides),
        )

        _logger.debug("Isolation: running %s on task %s", self.agent.role, task.id)
        report = self.agent.execute(isolated_task)

        if not report.ok:
            _logger.warning("Isolation: %s failed: %s", self.agent.role, report.error)

        return report

    def run_parallel(self, tasks: list[AgentTask]) -> list[AgentReport]:
        """并行执行多个任务 (同 Agent)."""
        return [self.run(t) for t in tasks]

    def get_history(self) -> list[AgentReport]:
        return self.agent.get_history()

    def get_metrics(self):
        return self.agent.get_metrics()
