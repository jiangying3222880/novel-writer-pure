"""
Memory Agent — 记忆 Agent

负责管理 L1-L4 记忆系统。
"""
from __future__ import annotations
from app.agents.base import AgentBase, AgentTask, AgentReport


class MemoryAgent(AgentBase):
    """记忆 Agent."""

    def __init__(self):
        super().__init__(role="memory")

    def _do_execute(self, task: AgentTask) -> AgentReport:
        state = task.state

        # 收集记忆信号 (简化版)
        memories = []
        if state:
            # L1: 近期事件
            if state.memories:
                memories.extend(state.memories[:3])

            # L2: 承诺
            pending = state.pending_commitments()
            for c in pending:
                memories.append(f"承诺: {c.description[:50]}")

            # L3: 伏笔
            active = state.active_hooks()
            for h in active:
                memories.append(f"伏笔: {h.description[:50]}")

        return AgentReport(
            ok=True,
            data={
                "memories": memories,
                "memory_count": len(memories),
                "l1_count": len([m for m in memories if m.startswith("承诺")]),
                "l2_count": len([m for m in memories if m.startswith("伏笔")]),
            },
        )
