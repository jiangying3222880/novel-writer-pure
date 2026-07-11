"""
Event Reducer — Event → State 归约器

纯函数：接收旧 State + Event，返回新 State。
"""
from __future__ import annotations

from story.state.story_state import StoryState, CharacterSnapshot, HookSnapshot, WorldSnapshot


def reduce(state: StoryState, event: dict) -> StoryState:
    """将单个 Event 归约到 State，返回新 State."""
    etype = event.get("event_type", "")
    entity = event.get("entity_name", "")
    field = event.get("field_name", "")
    new_val = event.get("new_value", "")

    if etype in ("character_state", "character_relationship", "character_knowledge",
                  "character_location", "character_inventory"):
        return _reduce_character(state, entity, field, new_val)

    elif etype in ("world_state", "world_location", "world_time"):
        return _reduce_world(state, field, new_val)

    elif etype == "hook_plant":
        return _reduce_hook_plant(state, entity, event)

    elif etype == "hook_payoff":
        return _reduce_hook_payoff(state, entity)

    return state


def reduce_all(state: StoryState, events: list[dict]) -> StoryState:
    """将多个 Event 归约到 State."""
    result = state
    for event in events:
        result = reduce(result, event)
    return result


def _reduce_character(state: StoryState, name: str, field: str, new_val: str) -> StoryState:
    char = state.get_character(name)
    traits = dict(char.traits) if char else {}
    if field in ("_location", "location"):
        return state.with_character(name, {**traits, "_location": new_val})
    elif field in ("_relationship", "relationship"):
        return state.with_character(name, {**traits, "_relationship": new_val})
    else:
        traits[field] = new_val
        return state.with_character(name, traits)


def _reduce_world(state: StoryState, field: str, new_val: str) -> StoryState:
    kwargs = {}
    if field in ("time", "time_label"):
        kwargs["time_label"] = new_val
    elif field == "location":
        kwargs["location"] = new_val
    elif field == "weather":
        kwargs["weather"] = new_val
    if kwargs:
        return state.with_world(**kwargs)
    return state


def _reduce_hook_plant(state: StoryState, hook_id: str, event: dict) -> StoryState:
    desc = event.get("description", hook_id)
    step = event.get("step_no", 0)
    snap = HookSnapshot(
        hook_id=hook_id,
        hook_type="plant",
        description=desc,
        status="active",
        planted_at_step=step,
    )
    return state.with_hook(snap)


def _reduce_hook_payoff(state: StoryState, hook_id: str) -> StoryState:
    existing = state.hook_by_id(hook_id)
    if existing:
        snap = HookSnapshot(
            hook_id=hook_id,
            hook_type=existing.hook_type,
            description=existing.description,
            status="resolved",
            planted_at_step=existing.planted_at_step,
        )
        return state.with_hook(snap)
    return state
