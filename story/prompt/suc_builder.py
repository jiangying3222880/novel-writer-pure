"""
SUC Builder — Story Understanding Context from StoryState.

Produces 4 structured segments from runtime state:
  character  — who is present, their relationships and arcs
  world      — time, location, active factions, rule constraints
  hook       — active hooks, pending payoffs, planted seeds
  tension    — pressure sources, unresolved threads, narrative urgency

Each segment is a dict for the compiler to render.
Does NOT replace prompt_assembler.py — runs in parallel, state-driven.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from story.state.story_state import StoryState


@dataclass
class SucSegment:
    label: str
    content: str = ""
    priority: int = 0
    token_estimate: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "content": self.content,
            "priority": self.priority,
            "token_estimate": self.token_estimate,
            "meta": dict(self.meta),
        }


@dataclass
class StoryUnderstandingContext:
    character: SucSegment = field(default_factory=lambda: SucSegment(label="角色状态", priority=1))
    world: SucSegment = field(default_factory=lambda: SucSegment(label="世界环境", priority=2))
    hook: SucSegment = field(default_factory=lambda: SucSegment(label="伏笔管理", priority=3))
    tension: SucSegment = field(default_factory=lambda: SucSegment(label="叙事张力", priority=4))

    def ranked_segments(self) -> list[SucSegment]:
        return sorted(
            [self.character, self.world, self.hook, self.tension],
            key=lambda s: s.priority,
        )

    def total_tokens(self) -> int:
        return sum(s.token_estimate for s in self.ranked_segments())

    def to_dict(self) -> dict:
        return {
            "character": self.character.to_dict(),
            "world": self.world.to_dict(),
            "hook": self.hook.to_dict(),
            "tension": self.tension.to_dict(),
        }


def build_suc(
    state: StoryState,
    *,
    signals: list | None = None,
    max_tokens: int = 2000,
) -> StoryUnderstandingContext:
    suc = StoryUnderstandingContext()

    suc.character = _build_character_segment(state)
    suc.world = _build_world_segment(state)
    suc.hook = _build_hook_segment(state)
    suc.tension = _build_tension_segment(state, signals=signals)

    _apply_token_budget(suc, max_tokens)

    return suc


def _build_character_segment(state: StoryState) -> SucSegment:
    lines: list[str] = []

    if state.pov_character:
        pov_char = state.get_character(state.pov_character)
        if pov_char:
            lines.append(f"### 主角: {state.pov_character}")
            traits = [f"{k}: {v}" for k, v in pov_char.traits.items()
                      if k not in ("_location", "_relationship")]
            if traits:
                lines.append("状态: " + ", ".join(traits))
            if pov_char.location:
                lines.append(f"位置: {pov_char.location}")
            lines.append("")

    other_chars = [c for name, c in state.characters.items()
                   if name != state.pov_character]
    if other_chars:
        lines.append("### 出场角色")
        for c in other_chars[:6]:
            parts = [c.name]
            traits = [f"{k}: {v}" for k, v in c.traits.items()
                      if k not in ("_location", "_relationship")]
            if traits:
                parts.append(f"({', '.join(traits[:3])})")
            lines.append("  " + " ".join(parts))
        lines.append("")

    content = "\n".join(lines) if lines else "(无角色状态)"
    return SucSegment(
        label="角色状态",
        content=content,
        priority=1,
        token_estimate=_estimate_tokens(content),
        meta={"pov": state.pov_character, "char_count": len(state.characters)},
    )


def _build_world_segment(state: StoryState) -> SucSegment:
    lines: list[str] = []

    w = state.world

    if state.synopsis:
        lines.append(f"### 当前单元: {state.title or '(未命名)'}")
        lines.append(f"剧情: {state.synopsis[:200]}")
        lines.append("")

    if w.time_label:
        lines.append(f"时间: {w.time_label}")
    if w.location:
        lines.append(f"地点: {w.location}")
    if w.weather:
        lines.append(f"天气: {w.weather}")
    if w.active_factions:
        lines.append(f"活跃势力: {', '.join(w.active_factions)}")
    if w.custom:
        for k, v in list(w.custom.items())[:4]:
            lines.append(f"{k}: {v}")

    content = "\n".join(lines) if lines else "(无世界状态)"
    return SucSegment(
        label="世界环境",
        content=content,
        priority=2,
        token_estimate=_estimate_tokens(content),
        meta={"location": w.location, "time": w.time_label},
    )


def _build_hook_segment(state: StoryState) -> SucSegment:
    active_hooks = state.active_hooks()
    if not active_hooks:
        return SucSegment(
            label="伏笔管理",
            content="(无活跃伏笔)",
            priority=3,
            token_estimate=5,
        )

    lines = [f"活跃伏笔: {len(active_hooks)} 个"]
    resolved = [h for h in state.hooks if h.is_resolved]

    for h in active_hooks[:8]:
        planted = f"step {h.planted_at_step}" if h.planted_at_step else "?"
        lines.append(f"  [{h.hook_type}] {h.description[:80]} (埋于 {planted})")

    if resolved:
        lines.append(f"\n已回收伏笔: {len(resolved)} 个")
        for h in resolved[:4]:
            lines.append(f"  ✓ {h.description[:60]}")

    content = "\n".join(lines)
    return SucSegment(
        label="伏笔管理",
        content=content,
        priority=3,
        token_estimate=_estimate_tokens(content),
        meta={
            "active_count": len(active_hooks),
            "resolved_count": len(resolved),
        },
    )


def _build_tension_segment(
    state: StoryState,
    *,
    signals: list | None = None,
) -> SucSegment:
    lines: list[str] = []

    lines.append(f"进度: {state.current_step}/{state.total_steps}")

    if state.transition_type and state.transition_type != "direct":
        lines.append(f"衔接类型: {state.transition_type}")

    pending_c = [c for c in state.commitments if c.is_pending]
    if pending_c:
        lines.append(f"\n待履行承诺: {len(pending_c)} 个")
        for c in pending_c[:5]:
            lines.append(f"  ⏳ {c.description[:80]}")

    if signals:
        urgent_signals = [s for s in signals if hasattr(s, "urgent") and s.urgent]
        if urgent_signals:
            lines.append(f"\n紧迫信号: {len(urgent_signals)} 个")
            for s in urgent_signals[:5]:
                lines.append(f"  ⚡ [{s.source}] {s.advice[:60]}")

    content = "\n".join(lines)
    return SucSegment(
        label="叙事张力",
        content=content,
        priority=4,
        token_estimate=_estimate_tokens(content),
        meta={
            "step": state.current_step,
            "total": state.total_steps,
            "pending_commitments": len(pending_c),
        },
    )


def _apply_token_budget(suc: StoryUnderstandingContext, max_tokens: int) -> None:
    segments = sorted(
        [suc.character, suc.world, suc.hook, suc.tension],
        key=lambda s: s.priority,
    )
    used = 0
    for seg in segments:
        if seg.token_estimate <= 0:
            continue
        available = max_tokens - used
        if available <= 50:
            seg.content = _truncate_content(seg.content, 0)
            seg.token_estimate = 0
            continue
        if seg.token_estimate > available * 0.8:
            target = int(available * 0.8)
            seg.content = _truncate_content(seg.content, target)
            seg.token_estimate = target
        used += seg.token_estimate
        used = min(used, max_tokens)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text))


def _truncate_content(text: str, target_tokens: int) -> str:
    if not text:
        return ""
    target_chars = target_tokens * 2
    if len(text) <= target_chars:
        return text
    lines = text.split("\n")
    result: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) > target_chars:
            result.append("…(截断)")
            break
        result.append(line)
        used += len(line) + 1
    return "\n".join(result)
