"""
G17.1 Agent 基类 (~200 行)
所有 Agent 的根.

设计要点 (来自决策):
  1. Agent 是单职责: 只看自己的一种能力 (写 / 评估 / 检索 / 拼装 / 压力 / 批评)
  2. 辅助 Agent 之间不互通, 只能汇报给 Orchestrator
  3. 内部状态机: idle → working → done / error / cancelled
  4. 上下文隔离: 每次 execute() 复制 task.context, 不污染
  5. 汇报通过 Report (唯一通讯介质)
  6. 步进支持: step() 单步, execute() 完整

子类协议:
  - 必须实现 _do_execute(self, task: dict) -> Report
  - 不应抛异常, 应把错误放在 Report.error

子类的常用模式:
  - execute(task) → state=working → _do_execute(task) → state=done/error
  - 子类可以缓存 history / 累计 metrics
"""
from __future__ import annotations
import abc
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.base")


class AgentRole(str, Enum):
    """Agent 角色."""
    WRITER = "writer"          # 写手 / 士兵
    EDITOR = "editor"          # 编辑 (评估 6 维)
    CRITIC = "critic"          # 批评家 (风格一致性)
    RETRIEVER = "retriever"    # 检索 (文风+桥段 RAG)
    RESEARCHER = "researcher"  # 研究员 (历史/题材资料)
    CONTEXT_BUILDER = "context_builder"  # 上下文构建 (世界观/角色/风格/心智)
    MEMORY = "memory"          # 记忆 (L1-L4 拼装)
    PRESSURE = "pressure"      # 压力计
    ORCHESTRATOR = "orchestrator"  # 编排/将军


class AgentState(str, Enum):
    """Agent 状态机."""
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class AgentMetrics:
    """Agent 累计统计 (供 Orchestrator 监控)."""
    total_tasks: int = 0
    total_ok: int = 0
    total_err: int = 0
    total_duration_ms: int = 0
    last_run_at: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_ok / self.total_tasks

    @property
    def avg_duration_ms(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.total_duration_ms / self.total_tasks

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "total_ok": self.total_ok,
            "total_err": self.total_err,
            "success_rate": round(self.success_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "last_run_at": self.last_run_at,
        }


class AgentBase(abc.ABC):
    """
    所有 Agent 的基类.

    Attributes:
        id: 唯一 id (10 字符 hex)
        name: 显示名
        role: 角色 (writer/editor/...)
        state: 当前状态
        context: 任务上下文 (per-task dict, 每次 execute 复制)
        history: 历史汇报
        metrics: 累计统计
    """

    # 子类可覆盖: 默认 kind (Report.kind)
    DEFAULT_KIND: ReportKind = ReportKind.LOG

    def __init__(self, *, name: str, role: AgentRole) -> None:
        self.id = "ag_" + uuid.uuid4().hex[:8]
        self.name = name
        self.role = role
        self.state: AgentState = AgentState.IDLE
        self.context: dict = {}
        self.history: list[Report] = []
        self.metrics: AgentMetrics = AgentMetrics()
        # 取消信号 (Orchestrator 注入)
        self._cancelled: bool = False
        _logger.debug("[%s %s] 初始化", self.role.value, self.id)

    # ----------------- 公共 API ----------------- #

    def execute(self, task: dict) -> Report:
        """
        统一入口: 状态机 + 异常捕获 + 汇报收集.
        task 必填字段: id (str), context (dict, 可选), ...
        """
        self.state = AgentState.WORKING
        self.context = dict(task.get("context", {}))
        self._cancelled = False
        t0 = time.time()
        try:
            report = self._do_execute(task)
        except Exception as e:
            _logger.exception("[%s %s] execute 异常", self.role.value, self.id)
            report = Report(
                agent_id=self.id, agent_role=self.role.value,
                kind=self.DEFAULT_KIND, task_id=task.get("id", ""),
                ok=False, error=f"{type(e).__name__}: {e}",
                duration_ms=int((time.time() - t0) * 1000),
            )
            self.state = AgentState.ERROR
        else:
            self.state = AgentState.DONE if report.ok else AgentState.ERROR
        finally:
            report.duration_ms = int((time.time() - t0) * 1000)
        # 累计 metrics
        self.metrics.total_tasks += 1
        if report.ok:
            self.metrics.total_ok += 1
        else:
            self.metrics.total_err += 1
        self.metrics.total_duration_ms += report.duration_ms
        self.metrics.last_run_at = time.time()
        # 记录 history (只保留最近 50, 避免内存膨胀)
        self.history.append(report)
        if len(self.history) > 50:
            self.history = self.history[-50:]
        return report

    def cancel(self) -> None:
        """Orchestrator 主动取消 (下次 _do_execute 内 _check_cancel() 检测)."""
        self._cancelled = True

    def reset(self) -> None:
        """重置状态 (跑下一轮前调)."""
        self.state = AgentState.IDLE
        self.context = {}
        self._cancelled = False

    def last_report(self) -> Optional[Report]:
        return self.history[-1] if self.history else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "metrics": self.metrics.to_dict(),
            "history_count": len(self.history),
        }

    # ----------------- 子类协议 ----------------- #

    @abc.abstractmethod
    def _do_execute(self, task: dict) -> Report:
        """
        子类实现: 执行任务 → 汇报.
        应不抛异常; 错误用 Report.fail() 包装.
        必须把数据放到 Report.data.
        """
        raise NotImplementedError

    # ----------------- 内部工具 (供子类用) ----------------- #

    def _check_cancel(self) -> None:
        """子类在长任务里调, 取消时抛 CancelledError."""
        if self._cancelled:
            self.state = AgentState.CANCELLED
            raise AgentCancelledError(f"{self.name} 已被 Orchestrator 取消")

    def _build_report(self, task: dict, data: dict, *, suggestions: list[str] = None,
                     warnings: list[str] = None) -> Report:
        """便捷: 子类构造成功汇报."""
        return Report.ok_with(
            agent_id=self.id, agent_role=self.role.value,
            kind=self.DEFAULT_KIND, task_id=task.get("id", ""),
            data=data, suggestions=suggestions or [],
        )._replace_warnings(warnings or [])

    def _build_fail(self, task: dict, error: str) -> Report:
        """便捷: 子类构造失败汇报."""
        return Report.fail(
            agent_id=self.id, agent_role=self.role.value,
            kind=self.DEFAULT_KIND, error=error,
            task_id=task.get("id", ""),
        )


# 给 Report 加个私有方法: 替换 warnings (避免外部改 dataclass field)
def _replace_warnings(self: Report, warnings: list[str]) -> "Report":
    self.warnings = list(warnings)
    return self

Report._replace_warnings = _replace_warnings  # type: ignore[attr-defined]


# ============================================================
# 取消异常
# ============================================================
class AgentCancelledError(Exception):
    """Orchestrator 取消 Agent 时, Agent 内部 raise 此异常."""
    pass
