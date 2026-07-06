"""
Critic Agent — 批评 Agent

负责检查风格一致性和逻辑问题。
"""
from __future__ import annotations
from app.agents.base import AgentBase, AgentTask, AgentReport


class CriticAgent(AgentBase):
    """批评 Agent."""

    def __init__(self):
        super().__init__(role="critic")

    def _do_execute(self, task: AgentTask) -> AgentReport:
        context = task.context
        content = context.get("content", "")

        # 检查 (简化版)
        issues = []
        if len(content) < 100:
            issues.append("内容过短")
        if content.count("。") < 3:
            issues.append("句子过少")

        score = max(60, 100 - len(issues) * 10)

        return AgentReport(
            ok=True,
            data={
                "score": score,
                "issues": issues,
                "style_consistent": len(issues) == 0,
            },
        )
