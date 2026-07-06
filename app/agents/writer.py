"""
Writer Agent — 写作 Agent

负责生成文本内容。
"""
from __future__ import annotations
from app.agents.base import AgentBase, AgentTask, AgentReport


class WriterAgent(AgentBase):
    """写作 Agent."""

    def __init__(self):
        super().__init__(role="writer")

    def _do_execute(self, task: AgentTask) -> AgentReport:
        # 提取上下文
        context = task.context
        refined_prompt = context.get("refined_prompt", "")
        state = task.state

        # 生成内容 (简化版 — 实际会调用 LLM)
        content = f"[Writer] Generated content for unit {task.unit_id}"
        if refined_prompt:
            content += f"\\n\\nPrompt: {refined_prompt[:200]}"

        return AgentReport(
            ok=True,
            data={
                "content": content,
                "char_count": len(content),
                "unit_id": task.unit_id,
            },
        )
