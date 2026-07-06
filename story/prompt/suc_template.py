"""
SUC Template Engine — 结构化上下文模板

将 StoryState 编译为结构化的上下文表示。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from story.state.story_state import StoryState


@dataclass
class SUCTemplate:
    """SUC 模板."""
    structural: str = ""   # WHAT EXISTS
    dynamic: str = ""      # WHAT IS HAPPENING
    causal: str = ""       # WHY IT MATTERS
    instruction: str = ""  # WHAT TO DO


def build_structural(state: StoryState) -> str:
    """构建结构层: 世界中存在什么."""
    lines = []

    # 角色
    if state.characters:
        lines.append("## 角色")
        for name, char in state.characters.items():
            traits_str = ", ".join(f"{k}={v}" for k, v in char.traits.items())
            lines.append(f"- {name}: {traits_str} @ {char.location}")

    # 世界
    w = state.world
    if w.location or w.time_label:
        lines.append("\\n## 世界")
        if w.time_label:
            lines.append(f"- 时间: {w.time_label}")
        if w.location:
            lines.append(f"- 地点: {w.location}")
        if w.weather:
            lines.append(f"- 天气: {w.weather}")

    return "\\n".join(lines)


def build_dynamic(state: StoryState) -> str:
    """构建动态层: 正在发生什么."""
    lines = []

    # 进度
    if state.total_steps > 0:
        pct = state.current_step / state.total_steps * 100
        lines.append(f"## 进度: {state.current_step}/{state.total_steps} ({pct:.0f}%)")

    # 活跃伏笔
    active = state.active_hooks()
    if active:
        lines.append(f"\\n## 活跃伏笔: {len(active)}")
        for h in active:
            lines.append(f"- [{h.hook_type}] {h.description[:60]}")

    # 待履行承诺
    pending = state.pending_commitments()
    if pending:
        lines.append(f"\\n## 待履行承诺: {len(pending)}")
        for c in pending:
            lines.append(f"- {c.description[:60]}")

    return "\\n".join(lines)


def build_causal(state: StoryState) -> str:
    """构建因果层: 为什么重要."""
    lines = []

    # 已解决伏笔
    resolved = [h for h in state.hooks if h.is_resolved]
    if resolved:
        lines.append(f"## 已解决伏笔: {len(resolved)}")
        for h in resolved:
            lines.append(f"- {h.description[:60]}")

    # 记忆
    if state.memories:
        lines.append(f"\\n## 关键记忆: {len(state.memories)}")
        for m in state.memories[:5]:
            lines.append(f"- {m[:60]}")

    return "\\n".join(lines)


def compile_suc(state: StoryState, *, instruction: str = "") -> SUCTemplate:
    """编译完整 SUC."""
    return SUCTemplate(
        structural=build_structural(state),
        dynamic=build_dynamic(state),
        causal=build_causal(state),
        instruction=instruction,
    )
