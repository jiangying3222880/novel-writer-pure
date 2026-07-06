"""
StoryState — Runtime view of narrative state.

Read-only dataclass representing one unit's current narrative snapshot.
Not a DB shadow — this is a structured, queryable runtime representation
built from StoryUnitV2's JSON blobs.

Design rule: StoryState never writes to DB. It is constructed by StateBridge
and mutated by apply_event() returning new instances.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CharacterSnapshot:
    name: str
    traits: dict[str, Any] = field(default_factory=dict)
    location: str = ""
    relationship_to_pov: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.traits.get(key, default)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "traits": dict(self.traits),
            "location": self.location,
            "relationship_to_pov": self.relationship_to_pov,
        }


@dataclass(frozen=True)
class HookSnapshot:
    hook_id: str
    hook_type: str = "plant"
    description: str = ""
    status: str = "active"
    planted_at_step: int = 0
    paid_at_step: int = -1
    linked_event_ids: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    def to_dict(self) -> dict:
        return {
            "hook_id": self.hook_id,
            "hook_type": self.hook_type,
            "description": self.description,
            "status": self.status,
            "planted_at_step": self.planted_at_step,
            "paid_at_step": self.paid_at_step,
            "linked_event_ids": list(self.linked_event_ids),
        }


@dataclass(frozen=True)
class WorldSnapshot:
    time_label: str = ""
    location: str = ""
    weather: str = ""
    active_factions: list[str] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if key in ("time_label", "time", "timeLabel"):
            return self.time_label
        if key in ("location", "地点", "位置"):
            return self.location
        if key in ("weather", "天气"):
            return self.weather
        return self.custom.get(key, default)

    def to_dict(self) -> dict:
        return {
            "time_label": self.time_label,
            "location": self.location,
            "weather": self.weather,
            "active_factions": list(self.active_factions),
            "custom": dict(self.custom),
        }


@dataclass(frozen=True)
class CommitmentSnapshot:
    description: str
    status: str = "pending"
    target_unit_id: str = ""
    event_id: str = ""

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_fulfilled(self) -> bool:
        return self.status == "fulfilled"

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "status": self.status,
            "target_unit_id": self.target_unit_id,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class StoryState:
    unit_id: str
    title: str = ""
    unit_type: str = ""
    current_step: int = 0
    total_steps: int = 0
    pov_character: str = ""
    transition_type: str = "direct"
    synopsis: str = ""
    characters: dict[str, CharacterSnapshot] = field(default_factory=dict)
    hooks: list[HookSnapshot] = field(default_factory=list)
    world: WorldSnapshot = field(default_factory=WorldSnapshot)
    commitments: list[CommitmentSnapshot] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    phase: str = "entry"
    _ts: float = field(default_factory=time.time)

    # ── queries ──

    def get_character(self, name: str) -> CharacterSnapshot | None:
        return self.characters.get(name)

    def character_names(self) -> list[str]:
        return list(self.characters.keys())

    def active_hooks(self) -> list[HookSnapshot]:
        return [h for h in self.hooks if h.is_active]

    def active_hooks_count(self) -> int:
        return sum(1 for h in self.hooks if h.is_active)

    def pending_commitments(self) -> list[CommitmentSnapshot]:
        return [c for c in self.commitments if c.is_pending]

    def hook_by_id(self, hook_id: str) -> HookSnapshot | None:
        for h in self.hooks:
            if h.hook_id == hook_id:
                return h
        return None

    # ── mutation helpers (return new instance) ──

    def with_character(self, name: str, traits: dict[str, Any]) -> StoryState:
        chars = dict(self.characters)
        existing = chars.get(name)
        if existing:
            merged = dict(existing.traits)
            merged.update(traits)
            chars[name] = CharacterSnapshot(name=name, traits=merged,
                                            location=existing.location,
                                            relationship_to_pov=existing.relationship_to_pov)
        else:
            chars[name] = CharacterSnapshot(name=name, traits=traits)
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=self.current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=chars, hooks=list(self.hooks),
            world=self.world, commitments=list(self.commitments),
            memories=list(self.memories), phase=self.phase,
        )

    def with_hook(self, snap: HookSnapshot) -> StoryState:
        hooks = [h for h in self.hooks if h.hook_id != snap.hook_id]
        hooks.append(snap)
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=self.current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=dict(self.characters),
            hooks=hooks, world=self.world, commitments=list(self.commitments),
            memories=list(self.memories), phase=self.phase,
        )

    def with_world(self, **kwargs) -> StoryState:
        w = WorldSnapshot(
            time_label=kwargs.get("time_label", self.world.time_label),
            location=kwargs.get("location", self.world.location),
            weather=kwargs.get("weather", self.world.weather),
            active_factions=list(kwargs.get("active_factions", self.world.active_factions)),
            custom=dict(kwargs.get("custom", self.world.custom)),
        )
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=self.current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=dict(self.characters),
            hooks=list(self.hooks), world=w, commitments=list(self.commitments),
            memories=list(self.memories), phase=self.phase,
        )

    def with_commitment(self, c: CommitmentSnapshot) -> StoryState:
        commitments = list(self.commitments)
        commitments.append(c)
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=self.current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=dict(self.characters),
            hooks=list(self.hooks), world=self.world, commitments=commitments,
            memories=list(self.memories), phase=self.phase,
        )

    def with_phase(self, phase: str) -> StoryState:
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=self.current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=dict(self.characters),
            hooks=list(self.hooks), world=self.world,
            commitments=list(self.commitments), memories=list(self.memories),
            phase=phase,
        )

    def with_step(self, current_step: int) -> StoryState:
        return StoryState(
            unit_id=self.unit_id, title=self.title, unit_type=self.unit_type,
            current_step=current_step, total_steps=self.total_steps,
            pov_character=self.pov_character, transition_type=self.transition_type,
            synopsis=self.synopsis, characters=dict(self.characters),
            hooks=list(self.hooks), world=self.world,
            commitments=list(self.commitments), memories=list(self.memories),
            phase=self.phase,
        )

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "title": self.title,
            "unit_type": self.unit_type,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "pov_character": self.pov_character,
            "transition_type": self.transition_type,
            "synopsis": self.synopsis,
            "phase": self.phase,
            "characters": {n: c.to_dict() for n, c in self.characters.items()},
            "hooks": [h.to_dict() for h in self.hooks],
            "world": self.world.to_dict(),
            "commitments": [c.to_dict() for c in self.commitments],
            "memories": list(self.memories),
        }


@dataclass(frozen=True)
class StateDiff:
    unit_id: str
    character_changes: list[dict] = field(default_factory=list)
    hook_changes: list[dict] = field(default_factory=list)
    world_changes: list[dict] = field(default_factory=list)
    commitment_changes: list[dict] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.character_changes
            or self.hook_changes
            or self.world_changes
            or self.commitment_changes
        )

    def total_changes(self) -> int:
        return (
            len(self.character_changes)
            + len(self.hook_changes)
            + len(self.world_changes)
            + len(self.commitment_changes)
        )

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "character_changes": list(self.character_changes),
            "hook_changes": list(self.hook_changes),
            "world_changes": list(self.world_changes),
            "commitment_changes": list(self.commitment_changes),
            "total": self.total_changes(),
        }
