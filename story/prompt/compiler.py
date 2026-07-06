"""
Prompt Compiler — converts SUC + StrategyResult into LLM-ready messages.

Produces a structured system prompt and a user prompt.
The output format matches the existing LLM router's expected messages format:
  [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

Can be used alongside existing prompt_assembler.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from story.prompt.suc_builder import StoryUnderstandingContext
from story.decision.strategy import StrategyResult


WRITER_SYSTEM_TEMPLATE = """你是一位专业的小说作家。你将根据提供的上下文和写作指令，创作一个高质量的章节。

## 写作原则
1. 保持角色一致性：角色的性格、动机、语言风格要与已有设定一致
2. 遵循世界规则：不违反已建立的世界观设定
3. 推进叙事：每一步都要推动故事向前发展
4. 场景感强：用具体的动作、对话、环境描写来呈现，而非概括性叙述
5. 节奏适当：根据叙事策略调节张弛，不过度加速或拖沓"""


@dataclass
class CompiledPrompt:
    messages: list[dict[str, str]] = field(default_factory=list)
    system_parts: list[str] = field(default_factory=list)
    user_parts: list[str] = field(default_factory=list)
    token_estimate: int = 0

    def to_messages(self) -> list[dict[str, str]]:
        if self.messages:
            return list(self.messages)
        msgs: list[dict[str, str]] = []
        if self.system_parts:
            msgs.append({"role": "system", "content": "\n\n".join(self.system_parts)})
        if self.user_parts:
            msgs.append({"role": "user", "content": "\n\n".join(self.user_parts)})
        return msgs

    def to_dict(self) -> dict:
        return {
            "messages": self.to_messages(),
            "token_estimate": self.token_estimate,
        }


def compile(
    suc: StoryUnderstandingContext,
    strategy_result: StrategyResult | None = None,
    *,
    unit_title: str = "",
    unit_synopsis: str = "",
    previous_context: str | None = None,
    style_notes: str | None = None,
) -> CompiledPrompt:
    result = CompiledPrompt()

    # ── system prompt ──
    system_lines = [WRITER_SYSTEM_TEMPLATE]

    if style_notes:
        system_lines.append(f"\n## 风格要求\n{style_notes}")

    result.system_parts = system_lines

    # ── user prompt ──
    user_lines: list[str] = []

    # SUC segments (ranked by priority)
    for seg in suc.ranked_segments():
        if seg.content and seg.content != "(无角色状态)" and seg.content != "(无世界状态)" and seg.content != "(无活跃伏笔)":
            user_lines.append(f"## {seg.label}\n{seg.content}")

    # decision instruction
    if strategy_result and strategy_result.instruction:
        user_lines.append(strategy_result.instruction)

    # unit task
    task_block = _build_task_block(unit_title=unit_title, unit_synopsis=unit_synopsis)
    user_lines.append(task_block)

    if previous_context:
        user_lines.append(f"## 上文摘要\n{previous_context}")

    result.user_parts = user_lines

    result.messages = result.to_messages()

    result.token_estimate = sum(
        len(m.get("content", "")) for m in result.messages
    )

    return result


def compile_minimal(
    state,
    strategy_result: StrategyResult | None = None,
    *,
    unit_title: str = "",
    unit_synopsis: str = "",
) -> CompiledPrompt:
    from story.prompt.suc_builder import build_suc
    suc = build_suc(state, max_tokens=1500)
    return compile(
        suc,
        strategy_result=strategy_result,
        unit_title=unit_title or state.title,
        unit_synopsis=unit_synopsis or state.synopsis,
    )


def _build_task_block(
    *,
    unit_title: str = "",
    unit_synopsis: str = "",
) -> str:
    lines = ["## 写作任务"]
    if unit_title:
        lines.append(f"单元标题: {unit_title}")
    if unit_synopsis:
        lines.append(f"单元大纲: {unit_synopsis}")
    lines.append("\n请根据以上所有上下文和叙事策略，创作本章节内容。")
    lines.append("输出要求：完整连贯的叙事文本，包含动作、对话、环境描写。")
    return "\n".join(lines)
