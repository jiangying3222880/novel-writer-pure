"""
AgentBase v4 — 隔离内核基础类

每个 Agent 在隔离中运行，通过 Report 通信。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
import time
import uuid


@dataclass
class AgentTask:
    """Agent 任务."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    unit_id: str = ""
    project_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    state: Any = None  # StoryState
    guides: list = field(default_factory=list)


@dataclass
class AgentReport:
    """Agent 报告 — 唯一通信通道."""
    agent_id: str = ""
    agent_role: str = ""
    task_id: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "task_id": self.task_id,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentMetrics:
    """Agent 指标."""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_duration_ms: int = 0

    @property
    def avg_duration_ms(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successful_runs / self.total_runs


class AgentBase(ABC):
    """Agent 基类 — 隔离内核."""

    def __init__(self, role: str, agent_id: Optional[str] = None):
        self.role = role
        self.agent_id = agent_id or f"{role}_{uuid.uuid4().hex[:6]}"
        self.metrics = AgentMetrics()
        self._history: list[AgentReport] = []

    @abstractmethod
    def _do_execute(self, task: AgentTask) -> AgentReport:
        """执行任务 (子类实现)."""
        ...

    def execute(self, task: AgentTask) -> AgentReport:
        """执行任务 (带指标追踪)."""
        t0 = time.time()
        self.metrics.total_runs += 1

        try:
            report = self._do_execute(task)
            report.agent_id = self.agent_id
            report.agent_role = self.role
            report.task_id = task.id
            report.duration_ms = int((time.time() - t0) * 1000)

            if report.ok:
                self.metrics.successful_runs += 1
            else:
                self.metrics.failed_runs += 1
            self.metrics.total_duration_ms += report.duration_ms

            self._history.append(report)
            return report

        except Exception as e:
            duration = int((time.time() - t0) * 1000)
            self.metrics.failed_runs += 1
            self.metrics.total_duration_ms += duration
            report = AgentReport(
                agent_id=self.agent_id,
                agent_role=self.role,
                task_id=task.id,
                ok=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )
            self._history.append(report)
            return report

    def get_history(self) -> list[AgentReport]:
        return list(self._history)

    def get_metrics(self) -> AgentMetrics:
        return self.metrics
