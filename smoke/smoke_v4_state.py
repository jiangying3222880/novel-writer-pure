"""
Week 1 verification: StoryState + StateBridge + apply_event
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story import StoryState, StateBridge, apply_event, apply_events, StateDiff
from story.state.story_state import CharacterSnapshot, HookSnapshot

print("1. IMPORTS: OK")

# ===== 2. StoryState from scratch + with_* mutations =====
s = StoryState(unit_id="u1", title="测试单元", pov_character="林凡")

s = s.with_character("林凡", {"trust": 80, "realm": "筑基"})
s = s.with_character("慕容雪", {"trust": 40})
s = s.with_world(time_label="三年后", location="青云山")

print(f"2. STATE BUILD: characters={s.character_names()}, time={s.world.time_label}, loc={s.world.location}")

# ===== 3. apply_event =====
events = [
    {"event_type": "character_state", "entity_name": "林凡", "field_name": "realm", "old_value": "筑基", "new_value": "金丹"},
    {"event_type": "character_relationship", "entity_name": "慕容雪", "field_name": "trust", "old_value": "40", "new_value": "70"},
    {"event_type": "world_time", "field_name": "time", "new_value": "五年后"},
    {"event_type": "hook_plant", "entity_name": "h1", "description": "林凡发现古墓入口", "step_no": 1},
]

s2 = apply_events(s, events)

fan = s2.get_character("林凡")
murong = s2.get_character("慕容雪")
print(f"3. APPLY EVENTS: 林凡.realm={fan.get('realm')}, 慕容雪.trust={murong.get('trust')}, time={s2.world.time_label}, hooks={s2.active_hooks_count()}")

# verify immutable
assert s.get_character("林凡").get("realm") == "筑基", "原始状态被修改了!"
print("   IMMUTABLE: OK (original state unchanged)")

# ===== 4. StateBridge from mock unit =====
class MockUnit:
    id = "u_test"
    project_id = "p1"
    title = "试剑大会"
    unit_type = "battle"
    current_step = 3
    total_steps = 5
    pov_character = "林凡"
    transition_type = "direct"
    synopsis = "林凡在试剑大会上击败了所有对手"
    entry_characters = '{"林凡": {"trust": 80, "realm": "筑基"}, "慕容雪": {"trust": 40}}'
    exit_characters = "{}"
    entry_world = '{"time": "宗门大比日", "location": "天剑峰", "weather": "晴"}'
    exit_world = "{}"
    entry_commitments = '[{"description": "林凡承诺为师父报仇"}]'
    exit_commitments = "[]"
    unit_memories = '["师父临终遗言", "藏剑峰秘道"]'

state = StateBridge.from_unit_v2(MockUnit(), load_hooks=False)
print(f"4. STATEBRIDGE: title={state.title}, chars={state.character_names()}, world.loc={state.world.location}")
print(f"   memories={state.memories}, commitments={len(state.commitments)}")
assert state.title == "试剑大会"
assert "林凡" in state.characters
assert state.commitments[0].description == "林凡承诺为师父报仇"

# ===== 5. StateDiff =====
s_before = StoryState(unit_id="u1").with_character("张三", {"hp": 100})
s_after = s_before.with_character("张三", {"hp": 70}).with_character("李四", {"hp": 50})

diff = StateBridge.diff(s_before, s_after)
print(f"5. DIFF: total={diff.total_changes()}, has_changes={diff.has_changes}")
assert diff.total_changes() == 2

# ===== 6. Hook resolve =====
s3 = StoryState(unit_id="u2").with_hook(HookSnapshot(hook_id="h1", description="伏笔1", status="active"))
assert s3.active_hooks_count() == 1
s4 = apply_event(s3, {"event_type": "hook_payoff", "entity_name": "h1", "description": "伏笔1", "step_no": 5})
print(f"6. HOOK RESOLVE: active={s4.active_hooks_count()}, resolved={s4.hook_by_id('h1').is_resolved}")
assert s4.active_hooks_count() == 0

# ===== 7. Immutable chain =====
original_chars = s.get_character("林凡").get("realm")
s_mutated = apply_event(s, {"event_type": "character_state", "entity_name": "林凡", "field_name": "realm", "new_value": "元婴"})
assert s.get_character("林凡").get("realm") == original_chars
assert s_mutated.get_character("林凡").get("realm") == "元婴"
print("7. IMMUTABLE CHAIN: OK")

print()
print("ALL TESTS PASSED")
