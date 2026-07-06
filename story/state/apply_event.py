"""
apply_event — Pure function: StoryState + event → new StoryState.

Never mutates. Always returns new StoryState.
Maps existing unit_event_service event dicts to structured state mutations.
"""
from __future__ import annotations
import logging
from typing import Any

from story.state.story_state import (
    StoryState,
    CharacterSnapshot,
    HookSnapshot,
    CommitmentSnapshot,
)

_logger = logging.getLogger("NovelWriter.story.apply_event")

_EVENT_DISPATCH: dict[str, str] = {
    "character_state": "character",
    "character_relationship": "character",
    "character_knowledge": "character",
    "character_location": "character",
    "character_inventory": "character",
    "world_state": "world",
    "world_location": "world",
    "world_time": "world",
    "hook_plant": "hook",
    "hook_payoff": "hook",
    "promise_made": "commitment",
    "promise_broken": "commitment",
    "revelation": "revelation",
}


def apply_event(state: StoryState, event: dict[str, Any]) -> StoryState:
    event_type = str(event.get("event_type", ""))
    category = _EVENT_DISPATCH.get(event_type, "unknown")

    if category == "character":
        return _apply_character_event(state, event, event_type)
    elif category == "world":
        return _apply_world_event(state, event, event_type)
    elif category == "hook":
        return _apply_hook_event(state, event, event_type)
    elif category == "commitment":
        return _apply_commitment_event(state, event, event_type)
    else:
        _logger.debug("Unknown event type in apply_event: %s", event_type)
        return state


def _apply_character_event(state: StoryState, event: dict, event_type: str) -> StoryState:
    name = str(event.get("entity_name", ""))
    field = str(event.get("field_name", ""))
    old_val = event.get("old_value", "")
    new_val = event.get("new_value", "")

    if not name:
        return state

    current = state.get_character(name)
    if current is None:
        current = CharacterSnapshot(name=name)

    traits = dict(current.traits)

    if event_type == "character_relationship":
        traits[field or "trust"] = _coerce_val(new_val, old_val)
    elif event_type == "character_knowledge":
        traits["knowledge_" + field] = new_val if new_val else old_val
    elif event_type == "character_location":
        pass  # location 更新在下方统一处理
    elif event_type == "character_inventory":
        traits["inventory"] = _coerce_val(new_val, old_val)
    else:
        traits[field] = _coerce_val(new_val, old_val)

    if event_type == "character_location":
        location = str(new_val if new_val is not None else old_val)
    else:
        location = current.location
    relationship = current.relationship_to_pov

    chars = dict(state.characters)
    chars[name] = CharacterSnapshot(
        name=name, traits=traits, location=location, relationship_to_pov=relationship,
    )

    return StoryState(
        unit_id=state.unit_id, title=state.title, unit_type=state.unit_type,
        current_step=state.current_step, total_steps=state.total_steps,
        pov_character=state.pov_character, transition_type=state.transition_type,
        synopsis=state.synopsis, characters=chars, hooks=list(state.hooks),
        world=state.world, commitments=list(state.commitments),
        memories=list(state.memories), phase=state.phase,
    )


def _apply_world_event(state: StoryState, event: dict, event_type: str) -> StoryState:
    field = str(event.get("field_name", ""))
    new_val = event.get("new_value", "")
    old_val = event.get("old_value", "")
    val = str(new_val or old_val)

    if event_type == "world_time":
        return state.with_world(time_label=val)
    elif event_type == "world_location":
        return state.with_world(location=val)
    else:
        w = state.world
        custom = dict(w.custom)
        custom[field] = val
        return state.with_world(custom=custom)


def _apply_hook_event(state: StoryState, event: dict, event_type: str) -> StoryState:
    description = str(event.get("description", event.get("entity_name", "")))
    hook_id = str(event.get("entity_name", event.get("hook_id", "")))
    step_no = int(event.get("step_no", state.current_step))

    if event_type == "hook_plant":
        snap = HookSnapshot(
            hook_id=hook_id or description[:12],
            hook_type="plant",
            description=description,
            status="active",
            planted_at_step=step_no,
        )
        return state.with_hook(snap)

    elif event_type == "hook_payoff":
        existing = state.hook_by_id(hook_id)
        if existing:
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
        else:
            snap = HookSnapshot(
                hook_id=hook_id or description[:12],
                hook_type="payoff",
                description=description,
                status="resolved",
                planted_at_step=0,
                paid_at_step=step_no,
            )
            return state.with_hook(snap)

    return state


def _apply_commitment_event(state: StoryState, event: dict, event_type: str) -> StoryState:
    description = str(event.get("description", event.get("entity_name", "")))
    event_id = str(event.get("id", event.get("event_id", "")))

    if event_type == "promise_made":
        c = CommitmentSnapshot(description=description, status="pending", event_id=event_id)
        return state.with_commitment(c)

    elif event_type == "promise_broken":
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


def apply_events(state: StoryState, events: list[dict]) -> StoryState:
    s = state
    for ev in events:
        s = apply_event(s, ev)
    return s


# 命名约定对齐 GPT v4 设计文档 (Week 2 验收: rebuild_state)
rebuild_state = apply_events


def _coerce_val(new_val: Any, old_val: Any) -> Any:
    if new_val not in (None, ""):
        if isinstance(new_val, str):
            try:
                return int(new_val)
            except ValueError:
                try:
                    return float(new_val)
                except ValueError:
                    pass
        return new_val
    if old_val not in (None, ""):
        if isinstance(old_val, str):
            try:
                return int(old_val)
            except ValueError:
                try:
                    return float(old_val)
                except ValueError:
                    pass
        return old_val
    return old_val
