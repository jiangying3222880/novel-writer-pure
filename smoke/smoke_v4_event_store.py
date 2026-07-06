"""
smoke_v4_event_store — 事件存储测试

验证 EventStore 的追加、查询、清除功能。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from story.events.types import StoryEvent, EventTypes
from story.events.reducer import reduce, rebuild
from story.state.story_state import StoryState, CharacterSnapshot


def main():
    print("=" * 60)
    print("smoke_v4_event_store — 事件存储测试")
    print("=" * 60)

    # 1. StoryEvent 创建测试
    event = StoryEvent(
        type=EventTypes.CHARACTER_STATE,
        payload={"entity_name": "lin", "field_name": "health", "new_value": "hurt"},
        unit_id="test",
    )
    assert event.id
    assert event.type == "character_state"
    print(f"1. StoryEvent creation: OK (id={event.id[:8]})")

    # 2. Event 序列化测试
    d = event.to_dict()
    event2 = StoryEvent.from_dict(d)
    assert event2.type == event.type
    assert event2.unit_id == event.unit_id
    print("2. StoryEvent serialization: OK")

    # 3. Reducer 测试
    state = StoryState(
        unit_id="test",
        characters={"lin": CharacterSnapshot(name="lin", traits={"trust": 50})},
    )
    new_state = reduce(state, event)
    assert state.get_character("lin").traits.get("health") is None
    assert new_state.get_character("lin").traits.get("health") == "hurt"
    print("3. Reducer: OK (state mutated correctly)")

    # 4. 批量归约测试
    events = [
        StoryEvent(type=EventTypes.CHARACTER_STATE,
                   payload={"entity_name": "lin", "field_name": "trust", "new_value": 60}),
        StoryEvent(type=EventTypes.WORLD_TIME,
                   payload={"new_value": "morning"}),
    ]
    final_state = reduce(new_state, events[0])
    final_state = reduce(final_state, events[1])
    assert final_state.get_character("lin").traits.get("trust") == 60
    assert final_state.world.time_label == "morning"
    print("4. Batch reduce: OK")

    # 5. 重建测试
    state2 = StoryState(unit_id="test")
    raw_events = [
        {"event_type": "character_state", "entity_name": "lin", "field_name": "realm", "new_value": "golden"},
        {"event_type": "world_location", "new_value": "mountain"},
    ]
    rebuilt = rebuild(state2, raw_events)
    assert rebuilt.get_character("lin").traits.get("realm") == "golden"
    assert rebuilt.world.location == "mountain"
    print("5. Rebuild from dict: OK")

    # 6. 不可变性测试
    original_health = state.get_character("lin").traits.get("health")
    assert original_health is None
    print("6. Immutability: OK (original unchanged)")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
