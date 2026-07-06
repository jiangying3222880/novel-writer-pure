"""
Reader Agent — 读者视角 Agent

负责评估文本质量和读者体验。
"""
from __future__ import annotations
from app.agents.base import AgentBase, AgentTask, AgentReport


class ReaderAgent(AgentBase):
    """读者 Agent."""

    def __init__(self):
        super().__init__(role="reader")

    def _do_execute(self, task: AgentTask) -> AgentReport:
        context = task.context
        content = context.get("content", "")

        # 评估 (简化版)
        score = 70  # 默认分数
        if len(content) > 1000:
            score = 80
        if "悬念" in content or "冲突" in content:
            score = 85

        return AgentReport(
            ok=True,
            data={
                "score": score,
                "feedback": "内容质量良好，建议增加更多情感描写",
                "engagement": "medium",
            },
        )
