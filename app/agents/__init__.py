"""
Agent 体系 — Orchestrator (将军) 调度 6 辅助 Agent 协同写作.

将军激活后通过 Orchestrator 编排 MemoryKeeper → Retriever → PressureWatcher
→ StoryTeller → Editor → Critic 七步流程, 替代 writing_engine 的直接函数版.

文件结构:
  app/agents/
    ├── __init__.py         (本文件)
    ├── report.py           (Report 数据类)
    ├── base.py             (AgentBase 基类)
    ├── orchestrator.py     (Orchestrator 编排 — 将军主流程)
    └── helpers/            (6 辅助 Agent)
        ├── __init__.py
        ├── storyteller.py  (✅ 真实 AI 调用)
        ├── editor.py       (✅ 真实 AI 评估)
        ├── critic.py       (✅ 风格比对)
        ├── retriever.py    (✅ BM25+向量检索)
        ├── memory_keeper.py(✅ 4 层记忆拼装)
        └── pressure_watcher.py (✅ 压力感知)
"""
from app.agents.report import Report, ReportKind
from app.agents.base import AgentBase, AgentRole, AgentState
from app.agents.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    OrchestratorResult,
    build_orchestrator,
)

__all__ = [
    "Report", "ReportKind",
    "AgentBase", "AgentRole", "AgentState",
    "Orchestrator", "OrchestratorConfig", "OrchestratorResult",
    "build_orchestrator",
]
