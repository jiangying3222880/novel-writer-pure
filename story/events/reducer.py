"""
Event Reducer — Event → State 归约器

纯函数：接收旧 State + Event，返回新 State。
"""
from __future__ import annotations
from typing import Any
from story.state.story_state import StoryState, CharacterSnapshot, HookSnapshot, WorldSnapshot, CommitmentSnapshot
from story.events.types import StoryEvent


def reduce(state: StoryState, event: StoryEvent) -> StoryState:
    """将单个 Event 归约到 State，返回新 State."""
    etype = event.type
    p = event.payload

    if etype in ("character_state", "character_relationship", "character_knowledge",
                  "character_location", "character_inventory"):
        return _reduce_character(state, etype, p)

    elif etype in ("world_state", "world_location", "world_time"):
        return _reduce_world(state, etype, p)

    elif etype == "hook_plant":
        return _reduce_hook_plant(state, p)

    elif etype == "hook_payoff":
        return _reduce_hook_payoff(state, p)

    elif etype in ("promise_made", "promise_broken"):
        return _reduce_commitment(state, etype, p)

    return state


def reduce_all(state: StoryState, events: list[StoryEvent]) -> StoryState:
    """批量归约多个 Events."""
    s = state
    for ev in events:
        s = reduce(s, ev)
    return s


def rebuild(state: StoryState, events: list[dict]) -> StoryState:
    """从原始 dict 事件列表重建 State (兼容旧接口)."""
    s = state
    for ev_dict in events:
        ev = StoryEvent(
            type=ev_dict.get("event_type", ""),
            payload=ev_dict,
            unit_id=ev_dict.get("unit_id", ""),
        )
        s = reduce(s, ev)
    return s


def _reduce_character(state: StoryState, etype: str, p: dict) -> StoryState:
    name = str(p.get("entity_name", ""))
    if not name:
        return state

    current = state.get_character(name)
    if current is None:
        current = CharacterSnapshot(name=name)

    traits = dict(current.traits)
    location = current.location

    if etype == "character_state":
        field = str(p.get("field_name", ""))
        traits[field] = p.get("new_value", p.get("old_value", ""))
    elif etype == "character_relationship":
        field = str(p.get("field_name", "trust"))
        traits[field] = p.get("new_value", p.get("old_value", ""))
    elif etype == "character_knowledge":
        field = str(p.get("field_name", ""))
        traits["knowledge_" + field] = p.get("new_value", p.get("old_value", ""))
    elif etype == "character_location":
        location = str(p.get("new_value", p.get("old_value", "")))
    elif etype == "character_inventory":
        traits["inventory"] = p.get("new_value", p.get("old_value", ""))

    chars = dict(state.characters)
    chars[name] = CharacterSnapshot(
        name=name, traits=traits, location=location,
        relationship_to_pov=current.relationship_to_pov,
    )

    return StoryState(
        unit_id=state.unit_id, title=state.title, unit_type=state.unit_type,
        current_step=state.current_step, total_steps=state.total_steps,
        pov_character=state.pov_character, transition_type=state.transition_type,
        synopsis=state.synopsis, characters=chars, hooks=list(state.hooks),
        world=state.world, commitments=list(state.commitments),
        memories=list(state.memories), phase=state.phase,
    )


def _reduce_world(state: StoryState, etype: str, p: dict) -> StoryState:
    val = str(p.get("new_value", p.get("old_value", "")))

    if etype == "world_time":
        return state.with_world(time_label=val)
    elif etype == "world_location":
        return state.with_world(location=val)
    else:
        field = str(p.get("field_name", ""))
        w = state.world
        custom = dict(w.custom)
        custom[field] = val
        return state.with_world(custom=custom)


def _reduce_hook_plant(state: StoryState, p: dict) -> StoryState:
    hook_id = str(p.get("entity_name", p.get("hook_id", "")))
    description = str(p.get("description", p.get("entity_name", "")))
    step_no = int(p.get("step_no", state.current_step) or 0)

    snap = HookSnapshot(
        hook_id=hook_id or description[:12],
        hook_type="plant",
        description=description,
        status="active",
        planted_at_step=step_no,
    )
    return state.with_hook(snap)


def _reduce_hook_payoff(state: StoryState, p: dict) -> StoryState:
    hook_id = str(p.get("entity_name", p.get("hook_id", "")))
    step_no = int(p.get("step_no", state.current_step) or 0)

    existing = state.hook_by_id(hook_id)
    if existing is None:
        return state

    resolved = HookSnapshot(
        hook_id=existing.hook_id,
        hook_type="payoff",
        description=existing.description,
        status="resolved",
        planted_at_step=existing.planted_at_step,
        paid_at_step=step_no,
        linked_event_ids=list(existing.linked_event_ids),
    )
    return state.with_hook(resolved)


def _reduce_commitment(state: StoryState, etype: str, p: dict) -> StoryState:
    description = str(p.get("description", p.get("entity_name", "")))
    event_id = str(p.get("id", p.get("event_id", "")))

    if etype == "promise_made":
        c = CommitmentSnapshot(description=description, status="pending", event_id=event_id)
        return state.with_commitment(c)

    elif etype == "promise_broken":
        commitments = []
        for c in state.commitments:
            if c.description == description and c.is_pending:
                commitments.append(CommitmentSnapshot(
                    description=c.description, status="broken",
                    target_unit_id=c.target_unit_id, event_id=event_id,
                ))
            else:
                commitments.append(c)
        return StoryState(
            unit_id=state.unit_id, title=state.title, unit_type=state.unit_type,
            current_step=state.current_step, total_steps=state.total_steps,
            pov_character=state.pov_character, transition_type=state.transition_type,
            synopsis=state.synopsis, characters=dict(state.characters),
            hooks=list(state.hooks), world=state.world, commitments=commitments,
            memories=list(state.memories), phase=state.phase,
        )

    return state
