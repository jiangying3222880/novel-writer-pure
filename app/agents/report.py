"""
Agent 汇报数据类。
辅助 Agent 完成任务后, 唯一通讯方式 = 通过 Report 汇报给 Orchestrator.
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class ReportKind(str, Enum):
    """汇报类型 (方便 Orchestrator 路由)."""
    MEMORY = "memory"              # 拼装好的 L1-L4 记忆
    CONTEXT = "context"            # 上下文格式化 (世界观/角色/伏笔/风格/心智)
    ANTI_AI = "anti_ai"          # 反 AI 味清单
    PRESSURE = "pressure"          # 压力区段 + 钩子建议
    RETRIEVE = "retrieve"          # RAG 检索结果 (文风+桥段)
    RESEARCH = "research"          # 历史/题材资料检索
    WRITE = "write"                # 写手初稿
    REVISE = "revise"              # 写手改稿
    EDIT = "edit"                  # 编辑评估 (6 维)
    CRITIC = "critic"              # 批评家反馈
    PERSIST = "persist"            # 落库结果
    RETENTION = "retention"        # 追读率指标 (阶段)
    LOG = "log"                    # 调试日志


@dataclass
class Report:
    """
    Agent → Orchestrator 的汇报.
    - ok: 是否成功
    - data: 业务数据 (e.g. {content: "...", score: 75, axes: {...}})
    - error: 失败原因 (ok=False 时填)
    - suggestions: 给 Orchestrator 的建议 (e.g. "建议让写手加冲突")
    """
    agent_id: str
    agent_role: str
    kind: ReportKind
    task_id: str = ""
    ok: bool = True
    data: dict = field(default_factory=dict)
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    duration_ms: int = 0
    created_at: float = field(default_factory=time.time)
    report_id: str = field(default_factory=lambda: "rep_" + uuid.uuid4().hex[:10])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value if isinstance(self.kind, ReportKind) else str(self.kind)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        d = dict(d)
        if "kind" in d and isinstance(d["kind"], str):
            d["kind"] = ReportKind(d["kind"])
        return cls(**d)

    # 便捷: 给 Orchestrator 用的快速构造
    @classmethod
    def fail(cls, agent_id: str, agent_role: str, kind: ReportKind, error: str, *, task_id: str = "") -> "Report":
        return cls(
            agent_id=agent_id, agent_role=agent_role, kind=kind,
            task_id=task_id, ok=False, error=error,
        )

    @classmethod
    def ok_with(cls, agent_id: str, agent_role: str, kind: ReportKind, data: dict, *, task_id: str = "",
                suggestions: Optional[list[str]] = None) -> "Report":
        return cls(
            agent_id=agent_id, agent_role=agent_role, kind=kind,
            task_id=task_id, ok=True, data=data,
            suggestions=suggestions or [],
        )
