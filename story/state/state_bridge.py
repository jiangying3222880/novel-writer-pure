"""
StateBridge — DB ↔ Runtime state mapping layer.

Translates StoryUnitV2 (DB model) into StoryState (runtime view).
Does NOT write to DB. Does NOT store state.
Pure translation with optional enrichment from external services.
"""
from __future__ import annotations
import json
import logging
from typing import Any

from story.state.story_state import (
    StoryState,
    CharacterSnapshot,
    HookSnapshot,
    WorldSnapshot,
    CommitmentSnapshot,
    StateDiff,
)

_logger = logging.getLogger("NovelWriter.story.state_bridge")


def _parse_json(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _non_empty_json(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, (list, dict)):
        if len(parsed) == 0:
            return None
    return raw


def _parse_characters(raw: str | None) -> dict[str, CharacterSnapshot]:
    data = _parse_json(raw, {})
    if not isinstance(data, dict):
        return {}
    result: dict[str, CharacterSnapshot] = {}
    for name, traits in data.items():
        name = str(name)
        if isinstance(traits, dict):
            result[name] = CharacterSnapshot(
                name=name,
                traits={k: v for k, v in traits.items()
                        if k not in ("_location", "_relationship")},
                location=str(traits.get("_location", traits.get("location", ""))),
                relationship_to_pov=str(traits.get("_relationship", traits.get("relationship_to_pov", ""))),
            )
        else:
            result[name] = CharacterSnapshot(name=name)
    return result


def _parse_world(raw: str | None) -> WorldSnapshot:
    data = _parse_json(raw, {})
    if not isinstance(data, dict):
        return WorldSnapshot()
    return WorldSnapshot(
        time_label=str(data.get("time", data.get("time_label", ""))),
        location=str(data.get("location", data.get("地点", ""))),
        weather=str(data.get("weather", data.get("天气", ""))),
        active_factions=[
            str(f) for f in (data.get("active_factions", data.get("factions", [])))
            if isinstance(f, (str, int))
        ],
        custom={
            k: v for k, v in data.items()
            if k not in ("time", "time_label", "location", "地点",
                         "weather", "天气", "active_factions", "factions")
        },
    )


def _parse_commitments(raw: str | None) -> list[CommitmentSnapshot]:
    data = _parse_json(raw, [])
    if not isinstance(data, list):
        return []
    result: list[CommitmentSnapshot] = []
    for item in data:
        if isinstance(item, dict):
            result.append(CommitmentSnapshot(
                description=str(item.get("description", item.get("desc", item.get("text", "")))),
                status=str(item.get("status", "pending")),
                target_unit_id=str(item.get("target_unit_id", item.get("target", ""))),
                event_id=str(item.get("event_id", "")),
            ))
        elif isinstance(item, str):
            result.append(CommitmentSnapshot(description=item))
    return result


def _parse_memories(raw: str | None) -> list[str]:
    data = _parse_json(raw, [])
    if not isinstance(data, list):
        return []
    return [str(m) for m in data if m]


def _load_hooks(unit_id: str, project_id: str) -> list[HookSnapshot]:
    try:
        from app.services import unit_hook_service as _hook_svc
        hooks = _hook_svc.list_for_unit(unit_id)
        return [
            HookSnapshot(
                hook_id=h.hook_id or "",
                hook_type=h.hook_type or "plant",
                description=h.description or "",
                status="active" if h.hook_type in ("plant", "promise") else "resolved",
                planted_at_step=getattr(h, "step_no", 0),
            )
            for h in hooks
        ]
    except Exception:
        _logger.debug("Failed to load hooks for unit %s", unit_id, exc_info=True)
        return []


class StateBridge:

    @staticmethod
    def from_unit_v2(unit, *, load_hooks: bool = True) -> StoryState:
        project_id = getattr(unit, "project_id", "")

        characters = _parse_characters(
            _non_empty_json(getattr(unit, "entry_characters", None)) or getattr(unit, "exit_characters", None)
        )
        world = _parse_world(
            _non_empty_json(getattr(unit, "entry_world", None)) or getattr(unit, "exit_world", None)
        )
        exit_raw = _non_empty_json(getattr(unit, "exit_commitments", None))
        if exit_raw:
            commitments = _parse_commitments(exit_raw)
        else:
            commitments = _parse_commitments(getattr(unit, "entry_commitments", None))
        memories = _parse_memories(getattr(unit, "unit_memories", None))

        hooks: list[HookSnapshot] = []
        if load_hooks:
            hooks = _load_hooks(getattr(unit, "id", unit.unit_id if hasattr(unit, "unit_id") else ""), project_id)

        return StoryState(
            unit_id=getattr(unit, "id", getattr(unit, "unit_id", "")),
            title=getattr(unit, "title", "") or "",
            unit_type=getattr(unit, "unit_type", "") or "",
            current_step=getattr(unit, "current_step", 0) or 0,
            total_steps=getattr(unit, "total_steps", 0) or 0,
            pov_character=getattr(unit, "pov_character", "") or "",
            transition_type=getattr(unit, "transition_type", "direct") or "direct",
            synopsis=getattr(unit, "synopsis", "") or "",
            characters=characters,
            hooks=hooks,
            world=world,
            commitments=commitments,
            memories=memories,
            phase="entry",
        )

    @staticmethod
    def entry_state(unit) -> StoryState:
        characters = _parse_characters(getattr(unit, "entry_characters", None))
        world = _parse_world(getattr(unit, "entry_world", None))
        commitments = _parse_commitments(getattr(unit, "entry_commitments", None))
        memories = _parse_memories(getattr(unit, "unit_memories", None))

        return StoryState(
            unit_id=getattr(unit, "id", ""),
            title=getattr(unit, "title", "") or "",
            unit_type=getattr(unit, "unit_type", "") or "",
            current_step=0,
            total_steps=getattr(unit, "total_steps", 0) or 0,
            pov_character=getattr(unit, "pov_character", "") or "",
            transition_type=getattr(unit, "transition_type", "direct") or "direct",
            synopsis=getattr(unit, "synopsis", "") or "",
            characters=characters,
            hooks=[],
            world=world,
            commitments=commitments,
            memories=memories,
            phase="entry",
        )

    @staticmethod
    def exit_state(unit) -> StoryState:
        characters = _parse_characters(getattr(unit, "exit_characters", None))
        world = _parse_world(getattr(unit, "exit_world", None))
        commitments = _parse_commitments(getattr(unit, "exit_commitments", None))
        memories = _parse_memories(getattr(unit, "unit_memories", None))

        return StoryState(
            unit_id=getattr(unit, "id", ""),
            title=getattr(unit, "title", "") or "",
            unit_type=getattr(unit, "unit_type", "") or "",
            current_step=getattr(unit, "current_step", 0) or 0,
            total_steps=getattr(unit, "total_steps", 0) or 0,
            pov_character=getattr(unit, "pov_character", "") or "",
            transition_type=getattr(unit, "transition_type", "direct") or "direct",
            synopsis=getattr(unit, "synopsis", "") or "",
            characters=characters,
            hooks=[],
            world=world,
            commitments=commitments,
            memories=memories,
            phase="exit",
        )

    @staticmethod
    def diff(old: StoryState, new: StoryState) -> StateDiff:
        character_changes: list[dict] = []
        all_names = set(old.characters.keys()) | set(new.characters.keys())
        for name in all_names:
            oc = old.characters.get(name)
            nc = new.characters.get(name)
            if oc is None and nc is not None:
                character_changes.append({"name": name, "action": "added", "traits": dict(nc.traits)})
                continue
            if oc is not None and nc is None:
                character_changes.append({"name": name, "action": "removed"})
                continue
            if oc is not None and nc is not None:
                all_fields = set(oc.traits.keys()) | set(nc.traits.keys())
                for field in sorted(all_fields):
                    ov = oc.traits.get(field)
                    nv = nc.traits.get(field)
                    if ov != nv:
                        character_changes.append({
                            "name": name, "field": field,
                            "old": ov, "new": nv, "action": "modified",
                        })
                if oc.location != nc.location:
                    character_changes.append({
                        "name": name, "field": "_location",
                        "old": oc.location, "new": nc.location, "action": "modified",
                    })

        hook_changes: list[dict] = []
        old_ids = {h.hook_id for h in old.hooks}
        new_ids = {h.hook_id for h in new.hooks}
        for hid in old_ids - new_ids:
            hook_changes.append({"hook_id": hid, "action": "removed"})
        for hid in new_ids - old_ids:
            hook_changes.append({"hook_id": hid, "action": "added"})
        for hid in old_ids & new_ids:
            oh = old.hook_by_id(hid)
            nh = new.hook_by_id(hid)
            if oh and nh and oh.status != nh.status:
                hook_changes.append({
                    "hook_id": hid, "field": "status",
                    "old": oh.status, "new": nh.status, "action": "modified",
                })

        world_changes: list[dict] = []
        ow = old.world
        nw = new.world
        for attr in ("time_label", "location", "weather"):
            ov = getattr(ow, attr)
            nv = getattr(nw, attr)
            if ov != nv:
                world_changes.append({"field": attr, "old": ov, "new": nv, "action": "modified"})
        if set(ow.active_factions) != set(nw.active_factions):
            world_changes.append({
                "field": "active_factions",
                "old": list(ow.active_factions),
                "new": list(nw.active_factions),
                "action": "modified",
            })

        commitment_changes: list[dict] = []
        oc_descs = {c.description for c in old.commitments}
        nc_descs = {c.description for c in new.commitments}
        for desc in oc_descs - nc_descs:
            commitment_changes.append({"description": desc, "action": "removed"})
        for desc in nc_descs - oc_descs:
            commitment_changes.append({"description": desc, "action": "added"})

        return StateDiff(
            unit_id=old.unit_id,
            character_changes=character_changes,
            hook_changes=hook_changes,
            world_changes=world_changes,
            commitment_changes=commitment_changes,
        )
